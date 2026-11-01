"""What every check returns. Pure: no database, no clock, no model."""

from dataclasses import dataclass

BLOCKING = "blocking"
REVIEW = "review"
WARNING = "warning"


@dataclass(frozen=True)
class IssueSpec:
    code: str
    severity: str
    field: str | None
    message: str
    next_action: str
    owner_role: str
