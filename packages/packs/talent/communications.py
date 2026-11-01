"""Candidate conversations: reply drafts, follow-ups and interview scheduling.

Replies and reminders are built from one candidate's own file, and always wait for approval.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kernel import explain, schedule, trust
from kernel.ai import AgentContext, load_prompt
from kernel.ai.graphs import AgentState, agent_node
from kernel.ai.reader import EvidenceSpan
from kernel.comms.models import Attachment, Classification, Message, Thread
from kernel.db import tenant_session, utcnow
from kernel.errors import Conflict, ValidationFailed
from kernel.events import EventOutbox, publish, subscribe
from kernel.explain import DecisionDraft, Evidence
from kernel.identity.models import UserAccount
from kernel.trust.models import Proposal
from packs.talent import service
from packs.talent.blind import BLIND_TOKEN
from packs.talent.events import (
    FollowupDue,
    InterviewBooked,
    InterviewCancelled,
    InterviewRequested,
)
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
    if classification.type in TIME_TYPES and answer_about_times(
        ctx, message, classification, application, identity, job
    ):
        return {}

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


# ----- A candidate's answer about times -----

TIME_TYPES = {"availability", "reschedule"}
TIME_LIMIT = "Read from the candidate's email by an AI. Check their message before approving."


class SlotChoice(BaseModel):
    choice: int | None = Field(default=None, ge=1, le=10)
    evidence: EvidenceSpan


def _numbered_slots(slots: list[dict[str, str]]) -> str:
    return "\n".join(
        f"{index}. "
        + datetime.fromisoformat(slot["starts_at"])
        .astimezone(schedule.TIMEZONE)
        .strftime("%A %d %B at %H:%M")
        + " (Tunis time)"
        for index, slot in enumerate(slots, start=1)
    )


def _latest_interview(session: Session, application_id: UUID, status: str) -> Interview | None:
    return session.scalar(
        select(Interview)
        .where(Interview.application_id == application_id, Interview.status == status)
        .order_by(Interview.created_at.desc())
        .limit(1)
    )


def _in_reply(quote: str | None, body: str) -> bool:
    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().casefold()

    return bool(quote and quote.strip()) and norm(quote) in norm(body)


def pick_offered_slot(
    ctx: AgentContext, message: Message, interview: Interview
) -> tuple[dict[str, str], str] | None:
    """Which offered time the candidate chose, as a number the model can only pick from the list.

    Code then checks the number is in range and the quote is really in the candidate's words.
    Anything unclear, or flagged as an attempt to steer the model, goes to a person instead.
    """
    prompt = load_prompt(PROMPT_ANCHOR, "slot_picker")
    result = ctx.read_untrusted(
        f"Times offered:\n{_numbered_slots(interview.slots)}\n\n"
        f"Candidate's reply:\nSubject: {message.subject}\n\n{message.body}",
        prompt,
        SlotChoice,
        "email",
        str(message.id),
        tier="fast",
    )
    choice = result.data.choice
    quote = result.data.evidence.quote
    if result.flagged or choice is None or not 1 <= choice <= len(interview.slots):
        return None
    if not _in_reply(quote, message.body):
        return None
    return interview.slots[choice - 1], quote.strip()


def answer_about_times(
    ctx: AgentContext,
    message: Message,
    classification: Classification,
    application: Application,
    identity: CandidateIdentity,
    job: Job,
) -> bool:
    """Proposes the booking or the reschedule the candidate asked for. True if it did."""
    session = ctx.session
    name = identity.name or "the candidate"
    target = {
        "application_id": str(application.id),
        "thread_id": str(message.thread_id),
        "job_id": str(job.id),
    }
    offered = _latest_interview(session, application.id, "slots_proposed")
    if offered is not None:
        picked = pick_offered_slot(ctx, message, offered)
        if picked is None:
            return False  # no clear choice: the normal reply drafter answers, a person approves
        chosen, quote = picked
        decision = ctx.record_decision(
            DecisionDraft(
                kind="talent.interview_booking",
                question="Should this interview be booked?",
                subject={"application_id": str(application.id), "interview_id": str(offered.id)},
                outcome={"starts_at": chosen["starts_at"]},
                rationale="In their reply the candidate chose this time from those offered.",
                evidence=[
                    Evidence(ref="E1", source_type="email", source_id=str(message.id), quote=quote)
                ],
                not_considered=DRAFT_NOT_CONSIDERED,
                limits=[TIME_LIMIT, "Checked again against the calendars when it is booked."],
                versions={"model": ctx.model_used or "none"},
            )
        )
        ctx.propose(
            "talent.interview.book",
            {"interview_id": str(offered.id), **chosen},
            f"Book {name}'s interview at the time they chose",
            decision.id,
            f"book:{offered.id}:{chosen['starts_at']}",
            target=target,
        )
        return True

    booked = _latest_interview(session, application.id, "booked")
    if classification.type != "reschedule" or booked is None:
        return False
    evidence = []
    if _in_reply(classification.quote, message.body):
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
            kind="talent.interview_cancel",
            question="Should this interview be moved?",
            subject={"application_id": str(application.id), "interview_id": str(booked.id)},
            outcome={"action": "reschedule"},
            rationale="The candidate asked to move their interview.",
            evidence=evidence,
            not_considered=DRAFT_NOT_CONSIDERED,
            limits=[TIME_LIMIT, "New times are found and offered only after a person approves."],
            versions={"model": ctx.model_used or "none"},
        )
    )
    ctx.propose(
        "talent.interview.cancel",
        {
            "interview_id": str(booked.id),
            "reason": "The candidate asked to move it",
            "reschedule": True,
        },
        f"Move {name}'s interview: they asked for another time",
        decision.id,
        f"cancel:{booked.id}",
        target=target,
    )
    return True


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
    owner = hold_owner(interview.id)
    slots = schedule.find_slots(session, interview.participants, ignore_owner=owner)
    if not slots or not identity.email:
        interview.status = "no_slots"
        return {}
    expires_at = schedule.hold(session, ctx.tenant_id, interview.participants, slots, owner)
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
            limits=[
                "Calendars can change, so the slot is checked again at booking.",
                f"The times are held for this candidate until {expires_at.isoformat()}.",
            ],
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
        target={
            "application_id": str(application.id),
            "job_id": str(job.id),
            "interview_id": str(interview.id),
        },
    )
    return {}


def hold_owner(interview_id: UUID) -> str:
    return f"talent.interview:{interview_id}"


@subscribe("trust.proposal.rejected.v1", "talent.release_rejected_slots")
def release_rejected_slots(session: Session, event: EventOutbox) -> None:
    """A person decided not to offer these times, so other candidates may be offered them."""
    if event.payload["action_type"] != "kernel.email.send":
        return
    proposal = session.get(Proposal, UUID(event.payload["proposal_id"]))
    interview_id = proposal.target.get("interview_id")
    if not interview_id or not proposal.idempotency_key.startswith("interview_slots:"):
        return
    interview = session.get(Interview, UUID(interview_id), with_for_update=True)
    if interview is None or interview.status != "slots_proposed":
        return
    schedule.release(session, hold_owner(interview.id))
    interview.status = "slots_declined"


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
        owner=hold_owner(interview.id),
    )
    interview.status = "booked"
    interview.booking_id = booking.id
    interview.starts_at = starts_at
    interview.ends_at = ends_at
    if application.stage != "interview":
        application.stage = "interview"
    publish(session, tenant_id, InterviewBooked(interview_id=interview.id, booking_id=booking.id))
    _propose_confirmation(session, tenant_id, interview, application, job, starts_at, ends_at)
    return f"booking:{booking.id}"


def _propose_confirmation(
    session: Session,
    tenant_id: UUID,
    interview: Interview,
    application: Application,
    job: Job,
    starts_at: datetime,
    ends_at: datetime,
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
                "(Tunis time). The calendar invite is attached.\n\nThe recruitment team"
            ),
            "invite": invite_fields(
                interview, job, identity.email, starts_at, ends_at, "REQUEST", sequence=0
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


def invite_uid(interview_id: UUID) -> str:
    """One UID per interview, so a cancellation replaces the event in the candidate's calendar."""
    return f"interview-{interview_id}@astrarh.example.test"


def invite_fields(
    interview: Interview,
    job: Job,
    candidate_email: str,
    starts_at: datetime,
    ends_at: datetime,
    method: str,
    sequence: int,
) -> dict[str, Any]:
    return {
        "uid": invite_uid(interview.id),
        "title": f"Interview: {job.title}",
        "starts_at": starts_at.isoformat(),
        "ends_at": ends_at.isoformat(),
        "attendees": [candidate_email, *interview.participants],
        "method": method,
        "sequence": sequence,
    }


CANCELLABLE = {"requested", "slots_proposed", "no_slots", "slots_declined", "booked"}


def cancel_interview(session: Session, tenant_id: UUID, payload: dict[str, Any], key: str) -> str:
    """Effect of an approved cancellation. Frees the calendars and, if booked, tells the candidate.

    With `reschedule`, a new interview request follows, so fresh times get offered.
    """
    interview = session.get(Interview, UUID(payload["interview_id"]), with_for_update=True)
    if interview.status == "cancelled":
        return f"interview:{interview.id}:already_cancelled"
    if interview.status not in CANCELLABLE:
        raise trust.AdapterRejected(f"An interview that is {interview.status} can't be cancelled")
    application = session.get(Application, interview.application_id)
    job = session.get(Job, application.job_id)
    was_booked = interview.status == "booked" and interview.booking_id is not None
    schedule.release(session, hold_owner(interview.id))
    if was_booked:
        schedule.cancel(session, interview.booking_id)
    interview.status = "cancelled"
    reason = str(payload.get("reason") or "").strip()
    publish(session, tenant_id, InterviewCancelled(interview_id=interview.id, reason=reason))
    if was_booked:
        _propose_cancellation(
            session, tenant_id, interview, application, job, reason, bool(payload.get("reschedule"))
        )
    if payload.get("reschedule"):
        replacement = request_interview(
            session, tenant_id, application.id, list(interview.participants)
        )
        return f"interview:{interview.id}:rescheduled:{replacement.id}"
    return f"interview:{interview.id}:cancelled"


def _propose_cancellation(
    session: Session,
    tenant_id: UUID,
    interview: Interview,
    application: Application,
    job: Job,
    reason: str,
    reschedule: bool = False,
) -> None:
    identity = session.scalar(
        select(CandidateIdentity).where(CandidateIdentity.candidate_id == application.candidate_id)
    )
    if not identity or not identity.email:
        return
    first = (identity.name or "").split(" ")[0] or "there"
    when = interview.starts_at.astimezone(schedule.TIMEZONE).strftime("%A %d %B at %H:%M")
    decision = explain.record(
        session,
        tenant_id,
        DecisionDraft(
            kind="talent.interview_cancellation",
            question="Should this cancellation go out?",
            subject={"interview_id": str(interview.id)},
            outcome={"action": "cancel_interview"},
            rationale="A person approved cancelling this interview.",
            limits=[f"Reason given: {reason}"] if reason else [],
        ),
    )
    trust.propose(
        session,
        tenant_id,
        "kernel.email.send",
        {
            "to": identity.email,
            "subject": (
                f"Interview moved: {job.title}"
                if reschedule
                else f"Interview cancelled: {job.title}"
            ),
            "body": (
                f"Hello {first},\n\nYour interview for {job.title} on {when} (Tunis time) is "
                "cancelled so we can find a new time. New times will follow shortly.\n\n"
                "The recruitment team"
                if reschedule
                else f"Hello {first},\n\nWe have to cancel your interview for {job.title} on "
                f"{when} (Tunis time). We are sorry for the change and will be in touch about "
                "next steps.\n\nThe recruitment team"
            ),
            "invite": invite_fields(
                interview,
                job,
                identity.email,
                interview.starts_at,
                interview.ends_at,
                "CANCEL",
                sequence=1,
            ),
        },
        f"Tell {identity.name or 'the candidate'} the interview is cancelled",
        decision.id,
        f"interview_cancel:{interview.id}",
        target={"application_id": str(application.id), "job_id": str(job.id)},
    )


@subscribe("comms.attachment.received.v1", "talent.cv_from_email")
def cv_from_email(session: Session, event: EventOutbox) -> None:
    """A CV sent for a job the subject names becomes an application. Otherwise it waits in the
    inbox for a recruiter to file it, since guessing the job would put a person in the wrong pile."""
    attachment = session.get(Attachment, UUID(event.payload["attachment_id"]))
    message = session.get(Message, attachment.message_id)
    if attachment.status != "stored" or candidate_by_email(session, message.sender):
        return  # already a candidate: a person decides whether this is a new application
    job = service.job_for_subject(session, message.subject)
    if job is None:
        return
    try:
        with session.begin_nested():
            service.add_cv_from_attachment(session, event.tenant_id, job.id, attachment)
    except (Conflict, ValidationFailed) as exc:
        attachment.reason = exc.message
