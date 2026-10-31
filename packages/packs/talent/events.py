from uuid import UUID

from pydantic import BaseModel

from kernel.events import event_type


@event_type("talent.job.created.v1")
class JobCreated(BaseModel):
    job_id: UUID


@event_type("talent.cv.uploaded.v1")
class CvUploaded(BaseModel):
    cv_id: UUID
    job_id: UUID
    application_id: UUID


@event_type("talent.cv.processed.v1")
class CvProcessed(BaseModel):
    cv_id: UUID
    job_id: UUID
    status: str


@event_type("talent.ranking.requested.v1")
class RankingRequested(BaseModel):
    ranking_id: UUID
    job_id: UUID


@event_type("talent.ranking.completed.v1")
class RankingCompleted(BaseModel):
    ranking_id: UUID
    job_id: UUID
    candidates: int


@event_type("talent.application.stage_changed.v1")
class StageChanged(BaseModel):
    application_id: UUID
    job_id: UUID
    from_stage: str
    to_stage: str
