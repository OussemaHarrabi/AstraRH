"""Recruitment API."""

from collections import Counter
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel import explain, trust
from kernel.ai.models import SecurityEvent
from kernel.authz import require_role
from kernel.comms.models import Attachment
from kernel.errors import Conflict, KernelError, NotFound, ValidationFailed
from kernel.explain import DecisionDraft
from kernel.explain.models import DecisionRecord
from kernel.web import request_context
from packs.talent import communications, scoring, service
from packs.talent.models import (
    Application,
    CandidateIdentity,
    CriterionOverride,
    CvDocument,
    ExtractedProfile,
    Interview,
    Job,
    RankingRun,
    Rubric,
    Score,
)

READ_ROLES = {"admin", "hr", "recruiter", "auditor"}
WRITE_ROLES = {"admin", "hr", "recruiter"}
MAX_FILES_PER_UPLOAD = 200

router = APIRouter()


class JobBody(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=10, max_length=20000)
    org_unit: str | None = None


class RubricBody(BaseModel):
    criteria: list[dict[str, Any]]


class OverrideBody(BaseModel):
    criterion_id: str
    value: Decimal = Field(ge=0, le=1)
    reason: str = Field(min_length=3)


class InterviewBody(BaseModel):
    interviewer_email: str | None = None


class BookBody(BaseModel):
    starts_at: str
    ends_at: str


class CancelBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    reschedule: bool = False


class RejectBody(BaseModel):
    reason: str = Field(min_length=3)


def _job_or_404(session: Session, job_id: UUID) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise NotFound("Job not found")
    return job


def _job_json(job: Job, counts: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "external_id": job.external_id,
        "title": job.title,
        "description": job.description,
        "org_unit": job.org_unit,
        "status": job.status,
        "active_rubric_id": str(job.active_rubric_id) if job.active_rubric_id else None,
        "cv_counts": counts or {},
    }


def _rubric_json(rubric: Rubric) -> dict[str, Any]:
    return {
        "id": str(rubric.id),
        "version": rubric.version,
        "status": rubric.status,
        "source": rubric.source,
        "criteria": rubric.criteria,
    }


@router.get("/jobs", summary="List jobs with CV processing counts")
def list_jobs(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        jobs = ctx.session.scalars(select(Job).order_by(Job.created_at)).all()
        statuses = ctx.session.execute(select(CvDocument.job_id, CvDocument.status)).all()
        counts: dict[UUID, Counter] = {}
        for job_id, status in statuses:
            counts.setdefault(job_id, Counter())[status] += 1
        return [_job_json(job, dict(counts.get(job.id, {}))) for job in jobs]


@router.post("/jobs", status_code=201, summary="Create a job. An agent drafts its criteria.")
def create_job(body: JobBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        job = service.create_job(
            ctx.session, ctx.actor.tenant_id, body.title, body.description, body.org_unit
        )
        return _job_json(job)


@router.get("/jobs/{job_id}", summary="A job with its rubric versions")
def get_job(job_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        job = _job_or_404(ctx.session, job_id)
        rubrics = ctx.session.scalars(
            select(Rubric).where(Rubric.job_id == job_id).order_by(Rubric.version.desc())
        ).all()
        return {**_job_json(job), "rubrics": [_rubric_json(r) for r in rubrics]}


@router.post(
    "/jobs/{job_id}/rubrics", status_code=201, summary="Save edited criteria as a new draft"
)
def save_rubric(job_id: UUID, body: RubricBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        _job_or_404(ctx.session, job_id)
        return _rubric_json(
            service.save_rubric(ctx.session, ctx.actor.tenant_id, job_id, body.criteria)
        )


@router.post(
    "/jobs/{job_id}/rubrics/{rubric_id}/activate",
    summary="Approve criteria. Ranking uses only an approved rubric.",
)
def activate_rubric(job_id: UUID, rubric_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        job = _job_or_404(ctx.session, job_id)
        rubric = ctx.session.get(Rubric, rubric_id)
        if rubric is None or rubric.job_id != job_id:
            raise NotFound("Rubric not found")
        service.activate_rubric(ctx.session, job, rubric, ctx.actor.user_id)
        trust.audit.append(
            ctx.session,
            ctx.actor.tenant_id,
            "human",
            ctx.actor.user_id,
            "talent.rubric.activated",
            data={"job_id": str(job_id), "rubric_id": str(rubric_id), "version": rubric.version},
        )
        return _rubric_json(rubric)


@router.post(
    "/jobs/{job_id}/cvs", status_code=202, summary="Upload CVs (PDF, DOCX, HTML, Markdown or TXT)"
)
async def upload_cvs(
    job_id: UUID, request: Request, files: list[UploadFile] = File()
) -> dict[str, Any]:
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise ValidationFailed(f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time")
    uploads = [(file.filename or "upload", await file.read()) for file in files]
    accepted, rejected = [], []
    for filename, data in uploads:
        try:
            with request_context(request) as ctx:
                require_role(ctx.actor, WRITE_ROLES)
                _job_or_404(ctx.session, job_id)
                cv = service.add_cv(ctx.session, ctx.actor.tenant_id, job_id, filename, data)
                accepted.append({"filename": filename, "cv_id": str(cv.id)})
        except (ValidationFailed, Conflict) as exc:
            rejected.append({"filename": filename, "reason": exc.message})
    return {"accepted": accepted, "rejected": rejected}


class AttachmentBody(BaseModel):
    attachment_id: UUID


@router.post(
    "/jobs/{job_id}/cvs/from-email",
    status_code=202,
    summary="Use a CV that arrived by email for this job",
)
def cv_from_email(job_id: UUID, body: AttachmentBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        _job_or_404(ctx.session, job_id)
        attachment = ctx.session.get(Attachment, body.attachment_id)
        if attachment is None:
            raise NotFound("Attachment not found")
        cv = service.add_cv_from_attachment(ctx.session, ctx.actor.tenant_id, job_id, attachment)
        return {"cv_id": str(cv.id), "application_id": str(cv.application_id)}


@router.get("/jobs/{job_id}/cvs", summary="CV processing status")
def list_cvs(job_id: UUID, request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        rows = ctx.session.scalars(
            select(CvDocument).where(CvDocument.job_id == job_id).order_by(CvDocument.created_at)
        )
        return [
            {
                "id": str(cv.id),
                "filename": cv.filename,
                "status": cv.status,
                "status_reason": cv.status_reason,
                "flagged": cv.flagged,
                "flags": cv.flags,
                "parse_method": cv.parse_method,
            }
            for cv in rows
        ]


@router.post("/jobs/{job_id}/rankings", status_code=202, summary="Rank the ready CVs")
def start_ranking(job_id: UUID, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        ranking = service.request_ranking(
            ctx.session, ctx.actor.tenant_id, job_id, ctx.actor.user_id
        )
        return {"ranking_id": str(ranking.id), "status": ranking.status}


def _flag_reasons(session: Session, cv: CvDocument) -> list[str]:
    events = session.scalars(
        select(SecurityEvent).where(
            SecurityEvent.source_type == "cv", SecurityEvent.source_id == str(cv.id)
        )
    ).all()
    reasons = set(cv.flags)
    for event in events:
        reasons.update(event.detail.get("reasons", []))
    return sorted(reasons)


@router.get("/jobs/{job_id}/shortlist", summary="The latest ranked list, with reasons")
def shortlist(job_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        session = ctx.session
        ranking = session.scalar(
            select(RankingRun)
            .where(RankingRun.job_id == job_id)
            .order_by(RankingRun.created_at.desc())
            .limit(1)
        )
        if ranking is None:
            return {"ranking": None, "candidates": [], "unranked": []}
        rows = session.scalars(
            select(Score).where(Score.ranking_id == ranking.id).order_by(Score.rank)
        ).all()
        application_ids = [r.application_id for r in rows]
        applications = {
            a.id: a
            for a in session.scalars(select(Application).where(Application.id.in_(application_ids)))
        }
        identities = {
            i.candidate_id: i
            for i in session.scalars(
                select(CandidateIdentity).where(
                    CandidateIdentity.candidate_id.in_(
                        [a.candidate_id for a in applications.values()]
                    )
                )
            )
        }
        cvs = {
            c.application_id: c
            for c in session.scalars(select(CvDocument).where(CvDocument.job_id == job_id))
        }
        decisions = {
            d.id: d
            for d in session.scalars(
                select(DecisionRecord).where(
                    DecisionRecord.id.in_(
                        [r.decision_record_id for r in rows if r.decision_record_id]
                    )
                )
            )
        }
        candidates = []
        for row in rows:
            application = applications[row.application_id]
            identity = identities.get(application.candidate_id)
            cv = cvs[row.application_id]
            decision = decisions.get(row.decision_record_id)
            candidates.append(
                {
                    "application_id": str(row.application_id),
                    "name": identity.name if identity else None,
                    "rank": row.rank,
                    "score": str(row.score) if row.score is not None else None,
                    "meets_must_haves": row.meets_must_haves,
                    "missing_must_haves": scoring.missing_must_haves(row.inputs),
                    "factors": [
                        {
                            "key": factor.key,
                            "label": factor.label,
                            "weight": str(factor.weight),
                            "value": str(factor.value),
                            "contribution": str(factor.contribution),
                        }
                        for factor in scoring.score(row.inputs).factors
                    ],
                    "stage": application.stage,
                    "decision_record_id": str(row.decision_record_id)
                    if row.decision_record_id
                    else None,
                    "narrative": decision.narrative if decision else None,
                    "flagged": cv.flagged,
                    "flags": _flag_reasons(session, cv) if cv.flagged else [],
                    "parse_method": cv.parse_method,
                }
            )
        ranked_ids = set(application_ids)
        unranked = [
            {"filename": cv.filename, "status": cv.status, "reason": cv.status_reason}
            for cv in cvs.values()
            if cv.application_id not in ranked_ids
        ]
        return {
            "ranking": {
                "id": str(ranking.id),
                "status": ranking.status,
                "created_at": ranking.created_at.isoformat(),
                "finished_at": ranking.finished_at.isoformat() if ranking.finished_at else None,
                "rubric_id": str(ranking.rubric_id),
                "embedding_model": ranking.embedding_model,
                "order_hash": ranking.order_hash,
                "error": ranking.error,
            },
            "candidates": candidates,
            "unranked": unranked,
        }


def _application_or_404(session: Session, application_id: UUID) -> Application:
    application = session.get(Application, application_id)
    if application is None:
        raise NotFound("Application not found")
    return application


@router.get("/applications/{application_id}/profile", summary="What the AI read from this CV")
def application_profile(application_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        _application_or_404(ctx.session, application_id)
        cv = ctx.session.scalar(
            select(CvDocument).where(CvDocument.application_id == application_id)
        )
        profile = ctx.session.scalar(
            select(ExtractedProfile).where(ExtractedProfile.cv_id == cv.id)
        )
        return {
            "blind_text": cv.blind_text,
            "profile": profile.data if profile else None,
            "removed_spans": profile.removed_spans if profile else [],
            "hidden_text_chars": cv.hidden_text_chars,
            "flags": _flag_reasons(ctx.session, cv),
        }


@router.post(
    "/applications/{application_id}/overrides",
    status_code=201,
    summary="Correct one criterion, with a reason. Applies on the next ranking.",
)
def add_override(application_id: UUID, body: OverrideBody, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        _application_or_404(ctx.session, application_id)
        override = CriterionOverride(
            tenant_id=ctx.actor.tenant_id,
            application_id=application_id,
            criterion_id=body.criterion_id,
            value=body.value,
            reason=body.reason,
            actor_id=ctx.actor.user_id,
        )
        ctx.session.add(override)
        ctx.session.flush()
        trust.audit.append(
            ctx.session,
            ctx.actor.tenant_id,
            "human",
            ctx.actor.user_id,
            "talent.criterion.overridden",
            reason=body.reason,
            data={
                "application_id": str(application_id),
                "criterion_id": body.criterion_id,
                "value": str(body.value),
            },
        )
        return {"override_id": str(override.id)}


@router.post(
    "/applications/{application_id}/reject",
    status_code=202,
    summary="Propose a rejection. A different HR person must approve it.",
)
def propose_reject(application_id: UUID, body: RejectBody, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        session = ctx.session
        application = _application_or_404(session, application_id)
        score = session.scalar(
            select(Score)
            .where(Score.application_id == application_id)
            .order_by(Score.created_at.desc())
            .limit(1)
        )
        if score is None or score.decision_record_id is None:
            raise KernelError("Rank this candidate before proposing a rejection")
        proposal = trust.propose(
            session,
            ctx.actor.tenant_id,
            "talent.application.reject",
            {"application_id": str(application_id), "reason": body.reason},
            "Reject this candidate",
            score.decision_record_id,
            f"reject:{application_id}",
            target={"job_id": str(application.job_id)},
            requested_by=ctx.actor.user_id,
        )
        return {"proposal_id": str(proposal.id), "status": proposal.status}


DEFAULT_INTERVIEWER = "karim@cds.example.test"


def _interview_json(interview: Interview) -> dict[str, Any]:
    return {
        "id": str(interview.id),
        "application_id": str(interview.application_id),
        "status": interview.status,
        "slots": interview.slots,
        "participants": interview.participants,
        "starts_at": interview.starts_at.isoformat() if interview.starts_at else None,
        "ends_at": interview.ends_at.isoformat() if interview.ends_at else None,
        "booking_id": str(interview.booking_id) if interview.booking_id else None,
        "created_at": interview.created_at.isoformat(),
    }


@router.post(
    "/applications/{application_id}/interviews",
    status_code=202,
    summary="Find free times in the calendars and prepare the email",
)
def request_interview(
    application_id: UUID, body: InterviewBody, request: Request
) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        _application_or_404(ctx.session, application_id)
        participants = communications.recruiter_emails(
            ctx.session, ctx.actor.user_id, body.interviewer_email or DEFAULT_INTERVIEWER
        )
        interview = communications.request_interview(
            ctx.session, ctx.actor.tenant_id, application_id, participants
        )
        return _interview_json(interview)


@router.get("/jobs/{job_id}/interviews", summary="Interviews for this job")
def list_interviews(job_id: UUID, request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        rows = ctx.session.scalars(
            select(Interview)
            .join(Application, Application.id == Interview.application_id)
            .where(Application.job_id == job_id)
            .order_by(Interview.created_at.desc())
        )
        return [_interview_json(row) for row in rows]


@router.post(
    "/interviews/{interview_id}/book",
    status_code=202,
    summary="Propose booking one of the offered times. A person approves it.",
)
def propose_booking(interview_id: UUID, body: BookBody, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        session = ctx.session
        interview = session.get(Interview, interview_id)
        if interview is None:
            raise NotFound("Interview not found")
        chosen = {"starts_at": body.starts_at, "ends_at": body.ends_at}
        if chosen not in interview.slots:
            raise ValidationFailed("Choose one of the offered times")
        decision = explain.record(
            session,
            ctx.actor.tenant_id,
            DecisionDraft(
                kind="talent.interview_booking",
                question="Should this interview be booked?",
                subject={"interview_id": str(interview_id)},
                outcome={"starts_at": body.starts_at},
                rationale="The candidate chose this time from those offered.",
                limits=["Checked again against the calendars when it is booked."],
            ),
        )
        proposal = trust.propose(
            session,
            ctx.actor.tenant_id,
            "talent.interview.book",
            {"interview_id": str(interview_id), **chosen},
            "Book the interview at the chosen time",
            decision.id,
            f"book:{interview_id}:{body.starts_at}",
            requested_by=ctx.actor.user_id,
            target={"application_id": str(interview.application_id)},
        )
        return {"proposal_id": str(proposal.id), "status": proposal.status}


@router.get("/interviews/{interview_id}", summary="One interview, with its offered times")
def get_interview(interview_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        interview = ctx.session.get(Interview, interview_id)
        if interview is None:
            raise NotFound("Interview not found")
        return _interview_json(interview)


@router.post(
    "/interviews/{interview_id}/cancel",
    status_code=202,
    summary="Propose cancelling, or rescheduling, an interview. A person approves it.",
)
def propose_cancel(interview_id: UUID, body: CancelBody, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        session = ctx.session
        interview = session.get(Interview, interview_id)
        if interview is None:
            raise NotFound("Interview not found")
        if interview.status not in communications.CANCELLABLE:
            raise Conflict(f"An interview that is {interview.status} can't be cancelled")
        verb = "reschedule" if body.reschedule else "cancel"
        decision = explain.record(
            session,
            ctx.actor.tenant_id,
            DecisionDraft(
                kind="talent.interview_cancel",
                question=f"Should this interview be {verb}d?",
                subject={"interview_id": str(interview_id)},
                outcome={"action": verb},
                rationale=body.reason,
                limits=["If it was booked, the candidate gets a cancellation to approve too."],
            ),
        )
        proposal = trust.propose(
            session,
            ctx.actor.tenant_id,
            "talent.interview.cancel",
            {
                "interview_id": str(interview_id),
                "reason": body.reason,
                "reschedule": body.reschedule,
            },
            f"{verb.capitalize()} the interview",
            decision.id,
            f"cancel:{interview_id}",
            requested_by=ctx.actor.user_id,
            target={"application_id": str(interview.application_id)},
        )
        return {"proposal_id": str(proposal.id), "status": proposal.status}


@router.post("/followups/check", summary="Check now for candidates who went quiet")
def check_followups(request: Request) -> dict[str, int]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        return {
            "prepared": communications.sweep_followups(ctx.session, ctx.actor.tenant_id),
        }
