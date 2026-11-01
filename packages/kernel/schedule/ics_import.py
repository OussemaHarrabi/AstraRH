"""Read busy time out of an iCalendar export (Google, Outlook, Apple) or a free/busy file.

Only when someone is busy is kept. Event titles, places and guests are dropped on purpose:
HR needs to know a recruiter is busy, not what they are doing.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr

from kernel.schedule import TIMEZONE

MAX_BYTES = 2 * 1024 * 1024
MAX_BLOCKS = 5000
MAX_OCCURRENCES = 500
LONGEST_BLOCK = timedelta(days=14)
DURATION = re.compile(
    r"^(?P<sign>[+-])?P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


@dataclass(frozen=True)
class BusyTime:
    starts_at: datetime
    ends_at: datetime


class CalendarFileInvalid(ValueError):
    pass


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _split(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    name, *raw_params = head.split(";")
    params = {}
    for param in raw_params:
        key, _, param_value = param.partition("=")
        params[key.upper()] = param_value.strip('"')
    return name.upper(), params, value


def _zone(params: dict[str, str]) -> ZoneInfo:
    name = params.get("TZID")
    if not name:
        return TIMEZONE
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # Outlook writes Windows zone names. Local time is the safest reading.
        return TIMEZONE


def _when(value: str, params: dict[str, str]) -> tuple[datetime, bool]:
    """Returns the moment, and whether it was a whole day."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        day = datetime.strptime(value, "%Y%m%d").date()
        return datetime.combine(day, time(0), tzinfo=TIMEZONE), True
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC), False
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=_zone(params)), False


def _duration(value: str) -> timedelta:
    match = DURATION.match(value.strip())
    if not match:
        raise ValueError(f"Unreadable duration {value!r}")
    parts = {k: int(v) for k, v in match.groupdict().items() if v and k != "sign"}
    length = timedelta(
        weeks=parts.get("weeks", 0),
        days=parts.get("days", 0),
        hours=parts.get("hours", 0),
        minutes=parts.get("minutes", 0),
        seconds=parts.get("seconds", 0),
    )
    return -length if match.group("sign") == "-" else length


def _event_blocks(props: list[tuple[str, dict, str]], start: datetime, end: datetime):
    first: dict[str, tuple[dict, str]] = {}
    rrule = None
    exdates: set[datetime] = set()
    for name, params, value in props:
        if name == "RRULE":
            rrule = value
        elif name == "EXDATE":
            for item in value.split(","):
                exdates.add(_when(item, params)[0])
        else:
            first.setdefault(name, (params, value))
    if first.get("TRANSP", ({}, ""))[1].upper() == "TRANSPARENT":
        return
    if first.get("STATUS", ({}, ""))[1].upper() == "CANCELLED":
        return
    if "DTSTART" not in first:
        return
    begins, whole_day = _when(first["DTSTART"][1], first["DTSTART"][0])
    if "DTEND" in first:
        length = _when(first["DTEND"][1], first["DTEND"][0])[0] - begins
    elif "DURATION" in first:
        length = _duration(first["DURATION"][1])
    else:
        length = timedelta(days=1) if whole_day else timedelta(0)
    rule = None
    if rrule is not None:
        # Checked even for events we then skip, so a broken file is never half-imported quietly.
        try:
            rule = rrulestr(rrule, dtstart=begins)
        except (ValueError, TypeError) as exc:
            raise CalendarFileInvalid("A repeating event has a rule we can't read") from exc
    if length <= timedelta(0) or length > LONGEST_BLOCK:
        return
    if rule is None:
        if begins < end and start < begins + length:
            yield BusyTime(begins, begins + length)
        return
    for count, occurrence in enumerate(rule.xafter(start - length, inc=True)):
        if occurrence >= end or count >= MAX_OCCURRENCES:
            break
        if occurrence not in exdates:
            yield BusyTime(occurrence, occurrence + length)


def _freebusy_blocks(props: list[tuple[str, dict, str]], start: datetime, end: datetime):
    for name, params, value in props:
        if name != "FREEBUSY" or params.get("FBTYPE", "BUSY").upper() == "FREE":
            continue
        for period in value.split(","):
            first, _, second = period.partition("/")
            begins = _when(first, params)[0]
            ends = begins + _duration(second) if second.startswith(("P", "+", "-")) else None
            ends = ends or _when(second, params)[0]
            if timedelta(0) < ends - begins <= LONGEST_BLOCK and begins < end and start < ends:
                yield BusyTime(begins, ends)


def read_busy(data: bytes, start: datetime, end: datetime) -> list[BusyTime]:
    """Busy time between start and end. Raises CalendarFileInvalid for anything unreadable."""
    if len(data) > MAX_BYTES:
        raise CalendarFileInvalid("The calendar file is larger than 2 MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CalendarFileInvalid("The calendar file is not UTF-8 text") from exc
    lines = _unfold(text)
    if not lines or lines[0].upper() != "BEGIN:VCALENDAR":
        raise CalendarFileInvalid("This is not an iCalendar (.ics) file")
    found: list[BusyTime] = []
    component: str | None = None
    depth = 0
    props: list[tuple[str, dict, str]] = []
    try:
        for line in lines:
            name, params, value = _split(line)
            if name == "BEGIN":
                if component is None and value.upper() in ("VEVENT", "VFREEBUSY"):
                    component, depth, props = value.upper(), 0, []
                elif component is not None:
                    depth += 1  # an alarm or similar inside the event
                continue
            if name == "END" and component is not None:
                if depth:
                    depth -= 1
                    continue
                reader = _event_blocks if component == "VEVENT" else _freebusy_blocks
                found.extend(reader(props, start, end))
                component = None
                if len(found) > MAX_BLOCKS:
                    raise CalendarFileInvalid("The calendar has too many events to import")
                continue
            if component is not None and not depth:
                props.append((name, params, value))
    except (ValueError, OverflowError) as exc:
        if isinstance(exc, CalendarFileInvalid):
            raise
        raise CalendarFileInvalid("The calendar file has a date we can't read") from exc
    return sorted(set(found), key=lambda block: block.starts_at)


__all__ = ["BusyTime", "CalendarFileInvalid", "MAX_BYTES", "read_busy"]
