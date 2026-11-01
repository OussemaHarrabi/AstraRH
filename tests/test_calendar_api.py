"""A recruiter's calendar: busy time by hand or from a calendar file, free time, bookings."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import TEST_PASSWORD, as_role, declare_action, make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from kernel import schedule, web
from kernel.db import global_session, tenant_session, utcnow
from kernel.identity.models import Tenant
from kernel.schedule import TIMEZONE
from kernel.schedule.ics_import import CalendarFileInvalid, read_busy
from kernel.schedule.models import BusyBlock
from kernel.trust.models import AuditEvent

app = FastAPI()
web.install(app)

WINDOW = (datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC))


def ics(*events: str) -> bytes:
    body = "\r\n".join(events)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN", body, "END:VCALENDAR", ""]
    return "\r\n".join(lines).encode()


def event(*lines: str) -> str:
    return "\r\n".join(["BEGIN:VEVENT", "UID:x@test", *lines, "END:VEVENT"])


@pytest.fixture(autouse=True)
def actions():
    declare_action("kernel.calendar.change", risk="R1", channel="internal")


@pytest.fixture
def slug(tenant):
    with as_role("owner"), global_session() as session:
        return session.get(Tenant, tenant).slug


def signed_in(slug, user) -> TestClient:
    http = TestClient(app, base_url="http://testserver", raise_server_exceptions=True)
    response = http.post(
        "/auth/login", json={"tenant": slug, "email": user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    http.headers["x-csrf-token"] = http.cookies[web.CSRF_COOKIE]
    return http


# ----- Reading calendar files -----


def test_times_in_utc_in_a_named_zone_and_whole_days():
    blocks = read_busy(
        ics(
            event("DTSTART:20261109T080000Z", "DTEND:20261109T090000Z", "SUMMARY:Secret"),
            event(
                "DTSTART;TZID=Europe/Paris:20261110T100000",
                "DTEND;TZID=Europe/Paris:20261110T110000",
            ),
            event("DTSTART;VALUE=DATE:20261111", "DTEND;VALUE=DATE:20261112"),
            event("DTSTART:20261112T090000Z", "DURATION:PT1H30M"),
        ),
        *WINDOW,
    )
    assert [(b.starts_at.astimezone(UTC), b.ends_at - b.starts_at) for b in blocks] == [
        (datetime(2026, 11, 9, 8, tzinfo=UTC), timedelta(hours=1)),
        (datetime(2026, 11, 10, 9, tzinfo=UTC), timedelta(hours=1)),
        (datetime(2026, 11, 11, tzinfo=TIMEZONE).astimezone(UTC), timedelta(days=1)),
        (datetime(2026, 11, 12, 9, tzinfo=UTC), timedelta(minutes=90)),
    ]


def test_repeating_events_skip_their_exceptions_and_stay_in_the_window():
    blocks = read_busy(
        ics(
            event(
                "DTSTART;TZID=Africa/Tunis:20261102T090000",
                "DTEND;TZID=Africa/Tunis:20261102T093000",
                "RRULE:FREQ=WEEKLY;BYDAY=MO",
                "EXDATE;TZID=Africa/Tunis:20261109T090000",
            )
        ),
        *WINDOW,
    )
    days = [b.starts_at.astimezone(TIMEZONE).date().isoformat() for b in blocks]
    assert days == ["2026-11-02", "2026-11-16", "2026-11-23", "2026-11-30"]


def test_free_cancelled_and_out_of_window_events_are_not_busy():
    blocks = read_busy(
        ics(
            event("DTSTART:20261109T080000Z", "DTEND:20261109T090000Z", "TRANSP:TRANSPARENT"),
            event("DTSTART:20261109T100000Z", "DTEND:20261109T110000Z", "STATUS:CANCELLED"),
            event("DTSTART:20270109T100000Z", "DTEND:20270109T110000Z"),
            event(
                "DTSTART:20261109T120000Z",
                "DTEND:20261109T130000Z",
                "BEGIN:VALARM",
                "TRIGGER:-PT15M",
                "END:VALARM",
            ),
        ),
        *WINDOW,
    )
    assert [b.starts_at.hour for b in blocks] == [12]


def test_free_busy_files_are_read():
    blocks = read_busy(
        ics(
            "BEGIN:VFREEBUSY",
            "FREEBUSY;FBTYPE=BUSY:20261109T080000Z/20261109T090000Z,20261110T080000Z/PT2H",
            "FREEBUSY;FBTYPE=FREE:20261111T080000Z/PT8H",
            "END:VFREEBUSY",
        ),
        *WINDOW,
    )
    assert [(b.starts_at.day, b.ends_at - b.starts_at) for b in blocks] == [
        (9, timedelta(hours=1)),
        (10, timedelta(hours=2)),
    ]


def test_folded_lines_are_joined():
    data = ics(event("DTSTART:20261109T08", " 0000Z", "DTEND:20261109T090000Z"))
    assert len(read_busy(data, *WINDOW)) == 1


@pytest.mark.parametrize(
    "data",
    [
        b"not a calendar",
        b"\xff\xfe\x00garbage",
        ics(event("DTSTART:2026-11-09", "DTEND:20261109T090000Z")),
        ics(event("DTSTART:20261109T080000Z", "RRULE:FREQ=SOMETIMES")),
        b"BEGIN:VCALENDAR\r\n" + b"X" * (2 * 1024 * 1024),
    ],
)
def test_unreadable_files_are_refused(data):
    with pytest.raises(CalendarFileInvalid):
        read_busy(data, *WINDOW)


# ----- The calendar API -----


def test_a_recruiter_imports_their_calendar_and_a_new_file_replaces_it(tenant, slug):
    recruiter = make_user(tenant, roles=["recruiter"])
    http = signed_in(slug, recruiter)
    soon = (utcnow() + timedelta(days=3)).strftime("%Y%m%dT100000Z")
    later = (utcnow() + timedelta(days=4)).strftime("%Y%m%dT100000Z")
    first = ics(
        event(f"DTSTART:{soon}", "DURATION:PT1H"), event(f"DTSTART:{later}", "DURATION:PT1H")
    )
    manual = http.post(
        "/calendar/busy",
        json={
            "starts_at": (utcnow() + timedelta(days=5)).isoformat(),
            "ends_at": (utcnow() + timedelta(days=5, hours=1)).isoformat(),
            "label": "Dentist",
        },
    )
    assert manual.status_code == 201
    response = http.post("/calendar/import", files={"file": ("me.ics", first, "text/calendar")})
    assert response.json() == {"participant": recruiter.email.lower(), "imported": 2}
    second = ics(event(f"DTSTART:{soon}", "DURATION:PT1H"))
    assert (
        http.post("/calendar/import", files={"file": ("me.ics", second, "text/calendar")}).json()[
            "imported"
        ]
        == 1
    )

    view = http.get("/calendar/busy", params={"to": (utcnow() + timedelta(days=10)).isoformat()})
    sources = sorted(item["source"] for item in view.json()["items"])
    assert sources == ["ics", "manual"]
    assert {item["label"] for item in view.json()["items"]} == {"Busy", "Dentist"}

    with as_role("worker"), tenant_session(tenant) as session:
        changes = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "kernel.calendar.change")
        ).all()
        assert len(changes) == 3


def test_free_time_avoids_imported_busy_time(tenant, slug):
    recruiter = make_user(tenant, roles=["recruiter"])
    http = signed_in(slug, recruiter)
    before = http.get("/calendar/free", params={"count": 1}).json()["slots"][0]
    start = datetime.fromisoformat(before["starts_at"]).astimezone(UTC)
    whole_day = ics(
        event(
            f"DTSTART:{start.strftime('%Y%m%dT000000Z')}",
            "DURATION:PT23H59M",
        )
    )
    http.post("/calendar/import", files={"file": ("me.ics", whole_day, "text/calendar")})
    after = http.get("/calendar/free", params={"count": 1}).json()["slots"][0]
    assert after["starts_at"] != before["starts_at"]


def test_a_recruiter_cannot_touch_someone_elses_calendar_but_hr_can(tenant, slug):
    recruiter = make_user(tenant, roles=["recruiter"])
    other = make_user(tenant, roles=["recruiter"])
    hr = make_user(tenant, roles=["hr"])
    http = signed_in(slug, recruiter)
    assert http.get("/calendar/busy", params={"participant": other.email}).status_code == 403
    body = {
        "participant": other.email,
        "starts_at": (utcnow() + timedelta(days=2)).isoformat(),
        "ends_at": (utcnow() + timedelta(days=2, hours=1)).isoformat(),
    }
    assert http.post("/calendar/busy", json=body).status_code == 403

    added = signed_in(slug, hr).post("/calendar/busy", json=body)
    assert added.status_code == 201
    assert http.delete(f"/calendar/busy/{added.json()['id']}").status_code == 403
    assert signed_in(slug, other).delete(f"/calendar/busy/{added.json()['id']}").status_code == 204


def test_people_without_a_calendar_role_are_refused(tenant, slug):
    employee = make_user(tenant, roles=["employee"])
    http = signed_in(slug, employee)
    assert http.get("/calendar/busy").status_code == 403
    assert http.get("/calendar/free").status_code == 403
    assert http.get("/calendar/bookings").status_code == 403


@pytest.mark.parametrize(
    "change",
    [
        {"ends_at": "BEFORE"},
        {"starts_at": "2026-11-09T10:00:00", "ends_at": "2026-11-09T11:00:00"},
        {"ends_at": "LONG"},
    ],
)
def test_nonsense_busy_time_is_refused(tenant, slug, change):
    http = signed_in(slug, make_user(tenant, roles=["recruiter"]))
    start = utcnow() + timedelta(days=1)
    body = {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()}
    special = {
        "BEFORE": (start - timedelta(hours=1)).isoformat(),
        "LONG": (start + timedelta(days=15)).isoformat(),
    }
    body.update({k: special.get(v, v) for k, v in change.items()})
    assert http.post("/calendar/busy", json=body).status_code == 422


def test_bad_calendar_files_get_a_clear_error(tenant, slug):
    http = signed_in(slug, make_user(tenant, roles=["recruiter"]))
    response = http.post("/calendar/import", files={"file": ("x.ics", b"hello", "text/calendar")})
    assert response.status_code == 422
    assert "iCalendar" in response.json()["message"]


def test_bookings_show_who_is_in_them(tenant, slug):
    recruiter = make_user(tenant, roles=["recruiter"])
    hr = make_user(tenant, roles=["hr"])
    starts_at = (utcnow() + timedelta(days=6)).replace(microsecond=0)
    with as_role("worker"), tenant_session(tenant) as session:
        schedule.book(
            session,
            tenant,
            [recruiter.email.lower(), "panel@cds.example.test"],
            starts_at,
            starts_at + timedelta(minutes=45),
            "Interview: Data Engineer",
            {"interview_id": "x"},
        )
        schedule.book(
            session,
            tenant,
            ["someone@cds.example.test"],
            starts_at,
            starts_at + timedelta(minutes=45),
            "Interview: Designer",
            {},
        )
    mine = signed_in(slug, recruiter).get("/calendar/bookings").json()["items"]
    assert [b["title"] for b in mine] == ["Interview: Data Engineer"]
    assert mine[0]["participants"] == sorted([recruiter.email.lower(), "panel@cds.example.test"])
    everyone = signed_in(slug, hr).get("/calendar/bookings").json()["items"]
    assert len(everyone) == 2
    view = signed_in(slug, recruiter).get("/calendar/busy").json()["items"]
    assert [item["kind"] for item in view] == ["booking"]


def test_another_company_cannot_see_or_delete_busy_time(tenant, other_tenant, slug):
    recruiter = make_user(tenant, roles=["recruiter"])
    with as_role("worker"), tenant_session(other_tenant) as session:
        block = BusyBlock(
            tenant_id=other_tenant,
            participant=recruiter.email.lower(),
            starts_at=utcnow() + timedelta(days=1),
            ends_at=utcnow() + timedelta(days=1, hours=1),
        )
        session.add(block)
        session.flush()
        block_id = block.id
    http = signed_in(slug, recruiter)
    assert http.get("/calendar/busy").json()["items"] == []
    assert http.delete(f"/calendar/busy/{block_id}").status_code == 404
