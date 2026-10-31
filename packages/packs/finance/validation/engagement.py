"""Engagement checks. Pure: no database, no clock, no model.

Each rule returns an issue with a severity, so the workflow can create the right task:
    blocking  cannot proceed until the cause is fixed
    review    needs a named person's decision, recorded with a reason
Which documents are required and which fixed-term reasons are recognised are configuration, not
legal advice, and must be checked against the labour code before real use.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

CDI, CDD, CIVP = "CDI", "CDD", "CIVP"
ENGAGEMENT_TYPES = {CDI, CDD, CIVP}

BLOCKING = "blocking"
REVIEW = "review"

# Placeholders, not the labour code. Anything else goes to a person for review.
RECOGNISED_CDD_REASONS = {"REPLACEMENT", "SEASONAL", "TEMPORARY_INCREASE", "PROJECT"}
STANDARD_WEEKLY_HOURS_LIMIT = Decimal(48)
CIVP_MAX_MONTHS = 12

REQUIRED_DOCUMENTS = {
    CDI: ("identity", "contract"),
    CDD: ("identity", "contract"),
    CIVP: ("identity", "diploma", "aneti_approval", "contract"),
}
DOCUMENT_TYPES = {doc for docs in REQUIRED_DOCUMENTS.values() for doc in docs}


@dataclass(frozen=True)
class IssueSpec:
    code: str
    severity: str
    field: str | None
    message: str
    next_action: str
    owner_role: str


@dataclass(frozen=True)
class EngagementView:
    type: str
    starts_on: date | None
    ends_on: date | None
    job_title: str
    weekly_hours: Decimal | None
    cdd_reason_code: str | None
    has_base_salary: bool
    verified_documents: frozenset[str]


def add_months(day: date, months: int) -> date:
    """The same day months later, or the month's last day when it does not exist."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    for candidate in range(day.day, 27, -1):
        try:
            return date(year, month, candidate)
        except ValueError:
            continue
    return date(year, month, min(day.day, 28))


def validate(view: EngagementView) -> list[IssueSpec]:
    issues: list[IssueSpec] = []

    def add(code, severity, field, message, next_action, owner="HR") -> None:
        issues.append(IssueSpec(code, severity, field, message, next_action, owner))

    if view.type not in ENGAGEMENT_TYPES:
        add(
            "ENGAGEMENT_TYPE_UNKNOWN",
            BLOCKING,
            "type",
            f"{view.type!r} is not CDI, CDD or CIVP.",
            "Choose the engagement type",
        )
        return issues
    if not view.job_title.strip():
        add(
            "JOB_TITLE_MISSING",
            BLOCKING,
            "job_title",
            "The job title is empty.",
            "Enter the job title",
        )
    if view.starts_on is None:
        add(
            "START_DATE_MISSING",
            BLOCKING,
            "starts_on",
            "There is no start date.",
            "Enter the start date",
        )
    if view.ends_on is not None and view.starts_on is not None and view.ends_on < view.starts_on:
        add(
            "DATES_INVALID",
            BLOCKING,
            "ends_on",
            "The end date is before the start date.",
            "Correct the dates",
        )

    if view.type == CDI and view.ends_on is not None:
        add(
            "CDI_HAS_END_DATE",
            BLOCKING,
            "ends_on",
            "An open-ended contract has an end date.",
            "Remove the end date or choose CDD",
        )
    if view.type in {CDD, CIVP} and view.ends_on is None:
        add(
            f"{view.type}_END_DATE_MISSING",
            BLOCKING,
            "ends_on",
            f"A {view.type} needs an end date.",
            "Enter the end date",
        )
    if (
        view.type == CIVP
        and view.starts_on is not None
        and view.ends_on is not None
        and view.ends_on > add_months(view.starts_on, CIVP_MAX_MONTHS)
    ):
        add(
            "CIVP_DURATION_REVIEW",
            REVIEW,
            "ends_on",
            f"The placement is longer than {CIVP_MAX_MONTHS} months. New ordinary placements "
            "are limited to 12 months (to verify with ANETI).",
            "Send for HR review against current ANETI rules",
        )
    if view.type == CDD:
        reason = (view.cdd_reason_code or "").strip().upper()
        if reason not in RECOGNISED_CDD_REASONS:
            shown = reason or "no reason"
            add(
                "CDD_REASON_REVIEW",
                REVIEW,
                "cdd_reason_code",
                f"The fixed-term reason ({shown}) is missing or not on the local list. A person "
                "must confirm it is permitted and supported.",
                "Send for local HR and legal review",
                "HR_LEGAL",
            )

    if view.weekly_hours is None or view.weekly_hours <= 0:
        add(
            "WEEKLY_HOURS_MISSING",
            BLOCKING,
            "weekly_hours",
            "Weekly hours are missing or not above zero.",
            "Enter the weekly hours",
        )
    elif view.weekly_hours > STANDARD_WEEKLY_HOURS_LIMIT:
        add(
            "WEEKLY_HOURS_REVIEW",
            REVIEW,
            "weekly_hours",
            f"{view.weekly_hours} weekly hours is above {STANDARD_WEEKLY_HOURS_LIMIT} "
            "(limit to verify).",
            "Confirm the hours are permitted",
        )

    if view.type != CIVP and not view.has_base_salary:
        add(
            "NO_BASE_SALARY",
            BLOCKING,
            "pay_items",
            "There is no base salary in force on the start date.",
            "Enter the base salary",
            "FINANCE",
        )

    for document in REQUIRED_DOCUMENTS[view.type]:
        if document not in view.verified_documents:
            add(
                "DOCUMENT_NOT_VERIFIED",
                BLOCKING,
                f"documents.{document}",
                f"The {document.replace('_', ' ')} document is not verified.",
                "Request document verification",
            )
    return issues
