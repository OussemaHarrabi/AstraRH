"""Calendar invites (RFC 5545), so a booked interview lands in the candidate's own calendar.

The proposal stores the invite as plain fields, so the reviewer sees exactly what is sent and the
approval hash covers it. The file is only rendered at send time.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field

PRODUCT = "-//AstraRH//Interviews//EN"
# Strict enough that an address can't smuggle a new line or a property into the file.
EMAIL = r"^[^@\s:;,]+@[^@\s:;,]+$"


class Invite(BaseModel):
    uid: str = Field(pattern=r"^[A-Za-z0-9._@-]{1,255}$")
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime
    attendees: list[Annotated[str, Field(pattern=EMAIL)]] = Field(min_length=1)
    method: str = Field(pattern="^(REQUEST|CANCEL)$")
    sequence: int = Field(ge=0, default=0)
    description: str = ""


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after a space."""
    raw = line.encode()
    if len(raw) <= 75:
        return line
    parts, start = [], 0
    while start < len(raw):
        end = min(start + (75 if not parts else 74), len(raw))
        while end < len(raw) and (raw[end] & 0xC0) == 0x80:
            end -= 1  # never split inside a UTF-8 character
        parts.append(raw[start:end].decode())
        start = end
    return "\r\n ".join(parts)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def render(data: dict[str, Any], organizer: str, now: datetime | None = None) -> str:
    invite = Invite.model_validate(data)
    if invite.ends_at <= invite.starts_at:
        raise ValueError("An invite must end after it starts")
    cancelled = invite.method == "CANCEL"
    lines = [
        "BEGIN:VCALENDAR",
        f"PRODID:{PRODUCT}",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        f"METHOD:{invite.method}",
        "BEGIN:VEVENT",
        f"UID:{invite.uid}",
        f"SEQUENCE:{invite.sequence}",
        f"DTSTAMP:{_stamp(now or datetime.now(UTC))}",
        f"DTSTART:{_stamp(invite.starts_at)}",
        f"DTEND:{_stamp(invite.ends_at)}",
        f"SUMMARY:{_escape(invite.title)}",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
        f"ORGANIZER:mailto:{organizer}",
        *(
            f"ATTENDEE;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{email}"
            for email in invite.attendees
        ),
    ]
    if invite.description:
        lines.append(f"DESCRIPTION:{_escape(invite.description)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
