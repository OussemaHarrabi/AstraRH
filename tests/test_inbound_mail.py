"""Live inbound mail: the executor copies it in, the worker reads it, CVs become applications."""

import smtplib
from email.message import EmailMessage
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from conftest import TEST_PASSWORD, as_role, make_user
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from kernel import registry, web
from kernel.adapters import mail, mailbox
from kernel.comms import inbound
from kernel.comms.models import Attachment, InboundMail, Message, Thread
from kernel.db import global_session, tenant_session, utcnow
from kernel.events import EventOutbox
from kernel.identity.models import Tenant
from packs.talent import communications, service
from packs.talent.models import Application, CandidateIdentity, CvDocument, Job

ROOT = Path(__file__).resolve().parents[1]
CV = (ROOT / "data/demo/cvs/cv_02_regular.pdf").read_bytes()
MAILBOX = "hr@cds.example.test"

app = FastAPI()
web.install(app)
registry.mount_pack_routers(app)


def raw_mail(sender, subject, body="Hello, please find my CV attached.", files=(), **headers):
    message = EmailMessage()
    message["From"] = f"Someone <{sender}>"
    message["To"] = MAILBOX
    message["Subject"] = subject
    message["Message-ID"] = f"<{uuid4().hex}@mail.example.test>"
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    message.set_content(body)
    for filename, data, maintype, subtype in files:
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return message.as_bytes()


def deliver(tenant, raw) -> InboundMail:
    with as_role("worker"), tenant_session(tenant) as session:
        mail_row = InboundMail(
            tenant_id=tenant,
            provider_id=f"test:{uuid4().hex}",
            mailbox=MAILBOX,
            raw=raw,
            size=len(raw),
            received_at=utcnow(),
        )
        session.add(mail_row)
        session.flush()
        inbound.process_pending(session, tenant)
        return mail_row


def run_cv_subscriber(tenant) -> None:
    with as_role("worker"), tenant_session(tenant) as session:
        for event in session.scalars(
            select(EventOutbox).where(EventOutbox.type == "comms.attachment.received.v1")
        ):
            communications.cv_from_email(session, event)


@pytest.fixture
def job(tenant):
    with as_role("worker"), tenant_session(tenant) as session:
        row = Job(
            tenant_id=tenant,
            external_id=f"J{uuid4().hex[:6].upper()}",
            title="Data Engineer",
            description="Pipelines in Python and SQL.",
        )
        session.add(row)
        session.flush()
        return row


def test_a_cv_sent_for_a_named_job_becomes_an_application(tenant, job):
    sender = f"amira.{uuid4().hex[:6]}@mail.example.test"
    row = deliver(
        tenant,
        raw_mail(
            sender, f"Application {job.external_id}", files=[("cv.pdf", CV, "application", "pdf")]
        ),
    )
    run_cv_subscriber(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        stored = session.get(InboundMail, row.id)
        assert stored.status == "ingested" and stored.raw is None  # the raw copy is dropped
        message = session.get(Message, stored.message_id)
        assert message.sender == sender and "CV attached" in message.body
        attachment = session.scalars(
            select(Attachment).where(Attachment.message_id == message.id)
        ).one()
        assert attachment.status == "used"
        application = session.get(Application, UUID(attachment.used_for["id"]))
        assert application.job_id == job.id
        cv = session.scalars(
            select(CvDocument).where(CvDocument.application_id == application.id)
        ).one()
        assert cv.filename == "cv.pdf"
        identity = session.scalars(
            select(CandidateIdentity).where(
                CandidateIdentity.candidate_id == application.candidate_id
            )
        ).one()
        assert identity.email == sender


def test_a_cv_with_no_named_job_waits_for_a_recruiter(tenant, job):
    sender = f"sami.{uuid4().hex[:6]}@mail.example.test"
    deliver(tenant, raw_mail(sender, "My CV", files=[("cv.pdf", CV, "application", "pdf")]))
    run_cv_subscriber(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        attachment = session.scalars(
            select(Attachment)
            .join(Message, Message.id == Attachment.message_id)
            .where(Message.sender == sender)
        ).one()
        assert attachment.status == "stored" and attachment.used_for is None
        thread_id = session.get(Message, attachment.message_id).thread_id

    recruiter = make_user(tenant, roles=("recruiter",))
    with as_role("owner"), global_session() as session:
        slug = session.get(Tenant, tenant).slug
    with as_role("api"):
        http = TestClient(app, base_url="http://testserver")
        login = http.post(
            "/auth/login",
            json={"tenant": slug, "email": recruiter.email, "password": TEST_PASSWORD},
        )
        assert login.status_code == 200
        http.headers["x-csrf-token"] = http.cookies[web.CSRF_COOKIE]

        view = http.get(f"/comms/threads/{thread_id}").json()
        listed = view["messages"][0]["attachments"]
        assert [(a["filename"], a["status"]) for a in listed] == [("cv.pdf", "stored")]

        url = f"/packs/talent/jobs/{job.id}/cvs/from-email"
        filed = http.post(url, json={"attachment_id": str(attachment.id)})
        assert filed.status_code == 202, filed.text
        again = http.post(url, json={"attachment_id": str(attachment.id)})
        assert again.status_code == 409

        used = http.get(f"/comms/threads/{thread_id}").json()["messages"][0]["attachments"][0]
        assert used["used_for"]["id"] == filed.json()["application_id"]


def test_a_known_candidate_is_not_given_a_second_application_automatically(tenant, job):
    sender = f"lina.{uuid4().hex[:6]}@mail.example.test"
    subject = f"Application {job.external_id}"
    attached = [("cv.pdf", CV, "application", "pdf")]
    deliver(tenant, raw_mail(sender, subject, files=attached))
    run_cv_subscriber(tenant)
    deliver(
        tenant,
        raw_mail(sender, f"Re: {subject}", files=[("cv2.pdf", CV + b"\n", "application", "pdf")]),
    )
    run_cv_subscriber(tenant)
    with as_role("worker"), tenant_session(tenant) as session:
        statuses = sorted(
            a.status
            for a in session.scalars(
                select(Attachment)
                .join(Message, Message.id == Attachment.message_id)
                .where(Message.sender == sender)
            )
        )
        assert statuses == ["stored", "used"]
        threads = session.scalars(select(Thread).where(Thread.party_email == sender)).all()
        assert len(threads) == 1  # the reply joined the first conversation


def test_attachments_that_fail_the_upload_gate_are_kept_only_as_a_record(tenant):
    sender = f"x.{uuid4().hex[:6]}@mail.example.test"
    deliver(
        tenant,
        raw_mail(
            sender,
            "CV",
            files=[
                ("../../etc/run.exe", b"MZ\x90\x00", "application", "octet-stream"),
                ("cv.pdf", b"not a pdf", "application", "pdf"),
            ],
        ),
    )
    with as_role("worker"), tenant_session(tenant) as session:
        rows = session.scalars(
            select(Attachment)
            .join(Message, Message.id == Attachment.message_id)
            .where(Message.sender == sender)
            .order_by(Attachment.filename)
        ).all()
        assert [(a.filename, a.status, a.file_key) for a in rows] == [
            ("cv.pdf", "rejected", None),
            ("run.exe", "rejected", None),
        ]
        assert "not a real PDF" in rows[0].reason
        events = session.scalars(
            select(EventOutbox).where(EventOutbox.type == "comms.attachment.received.v1")
        ).all()
        assert events == []


def test_our_own_and_automatic_mail_is_not_put_in_the_inbox(tenant):
    own = deliver(tenant, raw_mail(mail.SENDER_ADDRESS, "Interview times"))
    auto = deliver(
        tenant,
        raw_mail("bot@mail.example.test", "Out of office", Auto_Submitted="auto-replied"),
    )
    with as_role("worker"), tenant_session(tenant) as session:
        for row in (own, auto):
            assert session.get(InboundMail, row.id).status == "ignored"
        assert (
            session.scalar(select(Message.id).where(Message.provider_id == own.provider_id)) is None
        )


def test_html_only_mail_is_read_as_text_without_scripts(tenant):
    message = EmailMessage()
    message["From"] = "h@mail.example.test"
    message["To"] = MAILBOX
    message["Subject"] = "Question"
    message.set_content(
        "<html><head><style>p{}</style></head><body><p>When is the interview?</p>"
        "<script>alert(1)</script></body></html>",
        subtype="html",
    )
    row = deliver(tenant, message.as_bytes())
    with as_role("worker"), tenant_session(tenant) as session:
        body = session.get(Message, session.get(InboundMail, row.id).message_id).body
        assert body == "When is the interview?"


def test_the_executor_can_store_mail_but_never_read_it(tenant):
    with as_role("executor"), tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO comms.inbound_mail (id, tenant_id, provider_id, mailbox, raw, size, "
                "received_at, status, created_at) VALUES (gen_random_uuid(), :t, :p, :m, 'x', 1, "
                "now(), 'pending', now())"
            ),
            {"t": tenant, "p": f"test:{uuid4().hex}", "m": MAILBOX},
        )
    with as_role("executor"), tenant_session(tenant) as session:
        assert session.execute(text("SELECT provider_id FROM comms.inbound_mail")).all()
    for role, sql in (
        ("executor", "SELECT raw FROM comms.inbound_mail"),
        ("executor", "SELECT * FROM comms.message"),
        ("api", "SELECT provider_id FROM comms.inbound_mail"),
    ):
        with as_role(role), pytest.raises(ProgrammingError), tenant_session(tenant) as session:
            session.execute(text(sql))


def test_the_executor_pulls_the_mailbox_once(tenant):
    address = f"hr-{uuid4().hex[:8]}@cds.example.test"
    message = EmailMessage()
    message["From"] = "nour@mail.example.test"
    message["To"] = address
    message["Subject"] = "Availability"
    message.set_content("I can do Tuesday morning.")
    with smtplib.SMTP("mailpit", 1025, timeout=10) as client:
        client.send_message(message)
    with as_role("executor"):
        assert mailbox.poll(tenant, address) == 1
        assert mailbox.poll(tenant, address) == 0
    with as_role("worker"), tenant_session(tenant) as session:
        assert inbound.process_pending(session, tenant) >= 1
        stored = session.scalars(select(Message).where(Message.recipient == address)).one()
        assert stored.body == "I can do Tuesday morning."


def test_mailbox_config_ignores_malformed_pairs(monkeypatch):
    monkeypatch.setenv("INBOUND_MAILBOXES", "cds=hr@cds.example.test, broken, x=, =a@b")
    assert mailbox.mailboxes() == {"cds": "hr@cds.example.test"}


def test_replies_go_back_to_the_hr_mailbox():
    built = mail.build({"to": "a@example.test", "subject": "Hi", "body": "Hello"}, "k")
    assert built["Reply-To"] == MAILBOX


def test_mailpit_is_reachable_from_tests():
    assert httpx.get("http://mailpit:8025/api/v1/info", timeout=5).status_code == 200


def test_the_subject_names_a_job_by_exact_reference_or_unique_title(tenant):
    with as_role("worker"), tenant_session(tenant) as session:
        tag = uuid4().hex[:4].upper()
        for ref, title in [(f"Q{tag}1", f"Analyst {tag}"), (f"Q{tag}12", f"Analyst {tag}")]:
            session.add(Job(tenant_id=tenant, external_id=ref, title=title, description="x"))
        session.flush()
        assert service.job_for_subject(session, f"CV for Q{tag}1").external_id == f"Q{tag}1"
        assert service.job_for_subject(session, f"CV for Q{tag}12").external_id == f"Q{tag}12"
        assert service.job_for_subject(session, f"CV for analyst {tag}") is None  # two jobs
        assert service.job_for_subject(session, "Hello") is None
        session.rollback()
