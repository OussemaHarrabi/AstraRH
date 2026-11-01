"""Candidate conversations: reply drafts, follow-ups and interview scheduling.

Replies and reminders are built from one candidate's own file, and always wait for approval.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kernel import explain, schedule, trust
from kernel.ai import AgentContext, load_prompt
from kernel.ai.graphs import AgentState, agent_node
from kernel.comms.models import Classification, Message, Thread
from kernel.db import tenant_session, utcnow
from kernel.events import publish
from kernel.explain import DecisionDraft, Evidence
from kernel.identity.models import UserAccount
from packs.talent.blind import BLIND_TOKEN
from packs.talent.events import FollowupDue, InterviewBooked, InterviewRequested
from packs.talent.models import (
    Application,
    CandidateIdentity,
    Followup,
    Interview,
    Job,
)

# load_prompt looks for a prompts folder beside the path it is given.
PROMPT_ANCHOR = str(Path(__file__).parent / "agents" / "communications")
FOLLOWUP_AFTER = timedelta(days=3)
FOLLOWUP_MAX = 2
FOLLOWUP_STAGES = {"applied", "shortlisted", "interview"}
SKIP_REPLY_TYPES = {"spam", "internal", "policy_question"}
NAME_SLOT = "{name}"
DRAFT_NOT_CONSIDERED = ["Other candidates' files", "Name of school or university", "Age", "Gender"]

# A draft that promises something is refused, since only a person can commit the company.
COMMITMENT = re.compile(
    r"(\byou (are|have been) (hired|selected|accepted|rejected)\b|\bjob offer\b|\bwe (will|are going to) hire\b"
    r"|\bguarantee\w*\b|\b\d[\d\s.,]*\s?(tnd|dt|eur|€|\$|usd|dinars?)\b|\bsalary of\b"
    r"|\bvous êtes (embauché|retenu|recruté)\b|\bsalaire de\b)",
    re.IGNORECASE,
)


class ReplyDraft(BaseModel):
    subject: str
    body: str


def candidate_by_email(
    session: Session, email: str
) -> tuple[Application, CandidateIdentity, Job] | None:
    row = session.execute(
        select(Application, CandidateIdentity, Job)
        .join(CandidateIdentity, CandidateIdentity.candidate_id == Application.candidate_id)
        .join(Job, Job.id == Application.job_id)
        .where(func.lower(CandidateIdentity.email) == email.lower())
        .order_by(Application.created_at.desc())
        .limit(1)
    ).first()
    return (row[0], row[1], row[2]) if row else None


def draft_problem(session: Session, body: str, candidate_id: UUID) -> str | None:
    """Deterministic checks a draft must pass before a person ever sees it."""
    if COMMITMENT.search(body):
        return "makes a commitment only a person can make"
    others = session.execute(
        select(CandidateIdentity.name, CandidateIdentity.email).where(
            CandidateIdentity.candidate_id != candidate_id
        )
    ).all()
    lowered = body.casefold()
    for name, email in others:
        if name and name.casefold() in lowered:
            return "mentions another candidate"
        if email and email.casefold() in lowered:
            return "mentions another candidate"
    return None


def _fill_name(body: str, identity: CandidateIdentity) -> str:
    first = (identity.name or "").split(" ")[0] or "there"
    return body.replace(NAME_SLOT, first).replace(BLIND_TOKEN, first)


# ----- Reply drafter -----


class ReplyState(AgentState, total=False):
    skip: bool


@agent_node
def draft_reply(ctx: AgentContext, state: dict) -> dict:
    session = ctx.session
    event = state["event"]
    message = session.get(Message, UUID(event["message_id"]))
    classification = session.scalar(
        select(Classification).where(Classification.message_id == message.id)
    )
    found = candidate_by_email(session, message.sender)
    # Sensitive messages go to a person with no draft: writing one could frame their answer.
    if (
        found is None
        or classification.needs_human
        or classification.flagged
        or classification.type in SKIP_REPLY_TYPES
    ):
        return {"skip": True}
    application, identity, job = found

    # The candidate's own file and nothing else. Their message arrives as validated fields.
    facts = "\n".join(
        [
            f"Job applied for: {job.title}",
            f"Application stage: {application.stage}",
            f"What the message is about: {classification.type}",
            f"What they want: {classification.summary}",
            f"Subject: {message.subject}",
        ]
    )
    prompt = load_prompt(PROMPT_ANCHOR, "reply_drafter")
    draft = ctx.llm("fast", prompt, facts, ReplyDraft)
    problem = draft_problem(session, draft.body, application.candidate_id)
    if problem:
        trust.audit.append(
            session,
            ctx.tenant_id,
            "agent",
            "talent.reply_drafter",
            "reply.draft_refused",
            "denied",
            reason=problem,
            data={"message_id": str(message.id)},
        )
        return {"skip": True}

    evidence = []
    if classification.quote:
        evidence.append(
            Evidence(
                ref="E1",
                source_type="email",
                source_id=str(message.id),
                quote=classification.quote,
            )
        )
    decision = ctx.record_decision(
        DecisionDraft(
            kind="talent.reply",
            question="Should this reply go to the candidate?",
            subject={"application_id": str(application.id), "thread_id": str(message.thread_id)},
            outcome={"action": "draft_reply", "message_type": classification.type},
            rationale=(
                f"Drafted because the candidate wrote about {classification.type.replace('_', ' ')}. "
                f"Uses only their own application for {job.title}."
            ),
            evidence=evidence,
            not_considered=DRAFT_NOT_CONSIDERED,
            limits=["An AI draft. Check it before sending."],
            versions={"prompt_hash": prompt.hash, "model": ctx.model_used or "none"},
        )
    )
    subject = draft.subject or f"Re: {message.subject}"
    ctx.propose(
        "kernel.email.send",
        {"to": message.sender, "subject": subject, "body": _fill_name(draft.body, identity)},
        f"Reply to {identity.name or 'a candidate'} about {job.title}",
        decision.id,
        f"reply:{message.id}",
        target={
            "application_id": str(application.id),
            "thread_id": str(message.thread_id),
            "job_id": str(job.id),
        },
    )
    return {}


def build_reply_drafter() -> StateGraph:
    graph = StateGraph(ReplyState)
    graph.add_node("draft_reply", draft_reply)
    graph.add_edge(START, "draft_reply")
    graph.add_edge("draft_reply", END)
    return graph


# ----- Follow-ups -----


def due_followups(session: Session, now: datetime | None = None) -> list[dict[str, Any]]:
    """Who went quiet. Deterministic, and it stops on a reply, rejection, hire or the limit."""
    now = now or utcnow()
    rows = session.execute(
        select(Application, CandidateIdentity)
        .join(CandidateIdentity, CandidateIdentity.candidate_id == Application.candidate_id)
        .where(Application.stage.in_(FOLLOWUP_STAGES), CandidateIdentity.email.is_not(None))
    ).all()
    due = []
    for application, identity in rows:
        thread_ids = session.scalars(
            select(Thread.id).where(Thread.party_email == identity.email.lower())
        ).all()
        if not thread_ids:
            continue
        last = session.execute(
            select(Message.direction, Message.sent_at, Message.thread_id)
            .where(Message.thread_id.in_(thread_ids))
            .order_by(Message.sent_at.desc())
            .limit(1)
        ).first()
        if last is None or last.direction != "out" or last.sent_at > now - FOLLOWUP_AFTER:
            continue
        sent = session.scalar(
            select(func.count())
            .select_from(Followup)
            .where(Followup.application_id == application.id)
        )
        if sent >= FOLLOWUP_MAX:
            continue
        due.append(
            {
                "application_id": application.id,
                "thread_id": last.thread_id,
                "sequence": sent + 1,
                "last_sent_at": last.sent_at,
            }
        )
    return due


def sweep_followups(session: Session, tenant_id: UUID) -> int:
    items = due_followups(session)
    for item in items:
        publish(
            session,
            tenant_id,
            FollowupDue(
                application_id=item["application_id"],
                thread_id=item["thread_id"],
                sequence=item["sequence"],
            ),
        )
    return len(items)


@agent_node
def draft_followup(ctx: AgentContext, state: dict) -> dict:
    session = ctx.session
    event = state["event"]
    application = session.get(Application, UUID(event["application_id"]))
    sequence = int(event["sequence"])
    existing = session.scalar(
        select(Followup.id).where(
            Followup.application_id == application.id, Followup.sequence == sequence
        )
    )
    if existing:
        return {}
    identity = session.scalar(
        select(CandidateIdentity).where(CandidateIdentity.candidate_id == application.candidate_id)
    )
    job = session.get(Job, application.job_id)
    thread = session.get(Thread, UUID(event["thread_id"]))
    facts = "\n".join(
        [
            f"Job applied for: {job.title}",
            f"Reminder number: {sequence}",
            f"Earlier subject: {thread.subject}",
        ]
    )
    prompt = load_prompt(PROMPT_ANCHOR, "followup")
    draft = ctx.llm("fast", prompt, facts, ReplyDraft)
    if draft_problem(session, draft.body, application.candidate_id):
        return {}
    decision = ctx.record_decision(
        DecisionDraft(
            kind="talent.followup",
            question="Should this reminder go out?",
            subject={"application_id": str(application.id)},
            outcome={"action": "reminder", "sequence": sequence},
            rationale=(
                f"No reply for at least {FOLLOWUP_AFTER.days} days after our last message. "
                f"This is reminder {sequence} of at most {FOLLOWUP_MAX}."
            ),
            not_considered=DRAFT_NOT_CONSIDERED,
            versions={"prompt_hash": prompt.hash, "model": ctx.model_used or "none"},
        )
    )
    proposal = ctx.propose(
        "kernel.email.send",
        {"to": identity.email, "subject": draft.subject, "body": _fill_name(draft.body, identity)},
        f"Remind {identity.name or 'a candidate'} about {job.title}",
        decision.id,
        f"followup:{application.id}:{sequence}",
        target={
            "application_id": str(application.id),
            "thread_id": str(thread.id),
            "job_id": str(job.id),
        },
    )
    session.add(
        Followup(
            tenant_id=ctx.tenant_id,
            application_id=application.id,
            sequence=sequence,
            proposal_id=proposal.id,
        )
    )
    return {}


def build_followup() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("draft_followup", draft_followup)
    graph.add_edge(START, "draft_followup")
    graph.add_edge("draft_followup", END)
    return graph


# ----- Scheduling -----


def _slot_lines(slots: list[dict[str, str]]) -> str:
    lines = []
    for slot in slots:
        start = datetime.fromisoformat(slot["starts_at"]).astimezone(schedule.TIMEZONE)
        lines.append(f"- {start.strftime('%A %d %B at %H:%M')} (Tunis time)")
    return "\n".join(lines)


@agent_node
def propose_slots(ctx: AgentContext, state: dict) -> dict:
    """Real free time from the calendars, by arithmetic. A person approves the email."""
    session = ctx.session
    interview = session.get(Interview, UUID(state["event"]["interview_id"]))
    application = session.get(Application, interview.application_id)
    identity = session.scalar(
        select(CandidateIdentity).where(CandidateIdentity.candidate_id == application.candidate_id)
    )
    job = session.get(Job, application.job_id)
    slots = schedule.find_slots(session, interview.participants)
    if not slots or not identity.email:
        interview.status = "no_slots"
        return {}
    interview.slots = [slot.as_json() for slot in slots]
    interview.status = "slots_proposed"
    first = (identity.name or "").split(" ")[0] or "there"
    body = (
        f"Hello {first},\n\nThank you for your application for {job.title}. "
        "We would like to meet you. Would one of these times suit you?\n\n"
        f"{_slot_lines(interview.slots)}\n\n"
        "Please reply with the time you prefer.\n\nThe recruitment team"
    )
    decision = ctx.record_decision(
        DecisionDraft(
            kind="talent.interview_slots",
            question="Should these interview times be offered?",
            subject={"application_id": str(application.id), "interview_id": str(interview.id)},
            outcome={"slots": len(slots)},
            rationale=(
                f"The earliest working-hours times when all {len(interview.participants)} "
                "interviewers are free, at least 24 hours ahead, on separate days."
            ),
            evidence=[
                Evidence(
                    ref=f"E{index}",
                    source_type="calendar",
                    source_id=str(interview.id),
                    quote=f"Free: {slot['starts_at']} to {slot['ends_at']}",
                )
                for index, slot in enumerate(interview.slots, start=1)
            ],
            limits=["Calendars can change, so the slot is checked again at booking."],
            view_roles=["admin", "hr", "recruiter", "auditor"],
        )
    )
    ctx.propose(
        "kernel.email.send",
        {
            "to": identity.email,
            "subject": f"Interview for {job.title}: please choose a time",
            "body": body,
        },
        f"Offer interview times to {identity.name or 'a candidate'}",
        decision.id,
        f"interview_slots:{interview.id}",
        target={"application_id": str(application.id), "job_id": str(job.id)},
    )
    return {}


def build_scheduler() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("propose_slots", propose_slots)
    graph.add_edge(START, "propose_slots")
    graph.add_edge("propose_slots", END)
    return graph


def request_interview(
    session: Session, tenant_id: UUID, application_id: UUID, participants: list[str]
) -> Interview:
    interview = Interview(
        tenant_id=tenant_id,
        application_id=application_id,
        participants=participants,
        status="requested",
    )
    session.add(interview)
    session.flush()
    publish(session, tenant_id, InterviewRequested(interview_id=interview.id))
    return interview


def recruiter_emails(session: Session, actor_id: UUID, interviewer: str | None) -> list[str]:
    user = session.get(UserAccount, actor_id)
    return [email for email in [user.email, interviewer] if email]


def book_interview(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    """Effect of an approved booking. A slot that stopped being free fails here, safely."""
    interview = session.get(Interview, UUID(payload["interview_id"]), with_for_update=True)
    application = session.get(Application, interview.application_id)
    job = session.get(Job, application.job_id)
    starts_at = datetime.fromisoformat(payload["starts_at"])
    ends_at = datetime.fromisoformat(payload["ends_at"])
    booking = schedule.book(
        session,
        tenant_id,
        interview.participants,
        starts_at,
        ends_at,
        f"Interview: {job.title}",
        {"interview_id": str(interview.id)},
    )
    interview.status = "booked"
    interview.booking_id = booking.id
    interview.starts_at = starts_at
    interview.ends_at = ends_at
    if application.stage != "interview":
        application.stage = "interview"
    publish(session, tenant_id, InterviewBooked(interview_id=interview.id, booking_id=booking.id))
    _propose_confirmation(session, tenant_id, interview, application, job, starts_at, key)
    return f"booking:{booking.id}"


def _propose_confirmation(
    session: Session,
    tenant_id: UUID,
    interview: Interview,
    application: Application,
    job: Job,
    starts_at: datetime,
    key: str,
) -> None:
    identity = session.scalar(
        select(CandidateIdentity).where(CandidateIdentity.candidate_id == application.candidate_id)
    )
    if not identity or not identity.email:
        return
    first = (identity.name or "").split(" ")[0] or "there"
    when = starts_at.astimezone(schedule.TIMEZONE).strftime("%A %d %B at %H:%M")
    decision = explain.record(
        session,
        tenant_id,
        DecisionDraft(
            kind="talent.interview_confirmation",
            question="Should this confirmation go out?",
            subject={"interview_id": str(interview.id)},
            outcome={"action": "confirm_interview"},
            rationale="A person approved this booking, and the slot was free when it was made.",
        ),
    )
    trust.propose(
        session,
        tenant_id,
        "kernel.email.send",
        {
            "to": identity.email,
            "subject": f"Interview confirmed: {job.title}",
            "body": (
                f"Hello {first},\n\nYour interview for {job.title} is confirmed for {when} "
                "(Tunis time).\n\nThe recruitment team"
            ),
        },
        f"Confirm the interview with {identity.name or 'the candidate'}",
        decision.id,
        f"interview_confirm:{interview.id}:{uuid4().hex}",
        target={"application_id": str(application.id), "job_id": str(job.id)},
    )


def sweep_all_tenants(tenant_ids: list[UUID]) -> int:
    total = 0
    for tenant_id in tenant_ids:
        with tenant_session(tenant_id) as session:
            total += sweep_followups(session, tenant_id)
    return total
