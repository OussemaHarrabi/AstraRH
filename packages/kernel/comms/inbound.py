"""Turn raw inbound mail into inbox messages and stored attachments. Runs in the worker.

Everything here is untrusted: the parser reads headers and text only, attachments pass the same
upload gate as a recruiter's upload, and the body only ever reaches the quarantined reader.
"""

import html
import logging
import os
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel import files
from kernel.comms import ingest
from kernel.comms.models import Attachment, InboundMail
from kernel.db import utcnow
from kernel.errors import SecurityCheckUnavailable, ValidationFailed
from kernel.events import event_type, publish

BATCH = 20
MAX_BODY_CHARS = 20_000
MAX_ATTACHMENTS = 5
OWN_SENDERS = {"no-reply@cds.example.test"}
TAG = re.compile(r"<[^>]+>")
HIDDEN_BLOCKS = re.compile(r"<(script|style|head)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")

log = logging.getLogger("astra.inbound")


@event_type("comms.attachment.received.v1")
class AttachmentReceived(BaseModel):
    attachment_id: UUID
    message_id: UUID
    thread_id: UUID


def _text_of(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_subtype() == "html":
        content = html.unescape(TAG.sub(" ", HIDDEN_BLOCKS.sub(" ", content)))
    content = re.sub(r"[ \t]+", " ", content)
    return re.sub(r"\n{3,}", "\n\n", content).strip()[:MAX_BODY_CHARS]


def _safe_filename(name: str | None, index: int) -> str:
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = SAFE_NAME.sub("_", base)[:120].lstrip(".")
    return base or f"attachment-{index}"


def _store_attachments(
    session: Session, tenant_id: UUID, message: EmailMessage, message_id: UUID, thread_id: UUID
) -> None:
    for index, part in enumerate(message.iter_attachments(), start=1):
        filename = _safe_filename(part.get_filename(), index)
        if part.get_content_type() == "text/calendar":
            continue  # a calendar reply, not a document
        content = part.get_content()
        data = content.encode() if isinstance(content, str) else bytes(content)
        attachment = Attachment(
            tenant_id=tenant_id,
            message_id=message_id,
            filename=filename,
            size=len(data),
            status="rejected",
        )
        if index > MAX_ATTACHMENTS:
            attachment.reason = f"Only the first {MAX_ATTACHMENTS} attachments are kept"
        else:
            try:
                stored = files.put(tenant_id, filename, data)
            except ValidationFailed as exc:
                attachment.reason = exc.message
            else:
                attachment.status = "stored"
                attachment.file_key = stored.key
                attachment.sha256 = stored.sha256
                attachment.content_type = stored.content_type
        session.add(attachment)
        session.flush()
        if attachment.status == "stored":
            publish(
                session,
                tenant_id,
                AttachmentReceived(
                    attachment_id=attachment.id, message_id=message_id, thread_id=thread_id
                ),
            )


def _process(session: Session, tenant_id: UUID, mail: InboundMail) -> None:
    message = BytesParser(policy=policy.default).parsebytes(mail.raw)
    sender = parseaddr(str(message.get("From", "")))[1].lower()
    if "@" not in sender:
        mail.status, mail.reason = "rejected", "No sender address"
        return
    if sender in OWN_SENDERS or message.get("Auto-Submitted", "no").lower() != "no":
        mail.status, mail.reason = "ignored", "Sent by a machine, so not answered"
        return
    recipients = [address.lower() for _, address in getaddresses(message.get_all("To", []))]
    recipient = mail.mailbox if mail.mailbox in recipients else (recipients or [mail.mailbox])[0]
    try:
        sent_at = parsedate_to_datetime(str(message["Date"])) if message["Date"] else None
    except (TypeError, ValueError):
        sent_at = None
    if sent_at is not None and (sent_at.tzinfo is None or sent_at > utcnow()):
        sent_at = None  # a missing or future date can't be trusted for ordering
    stored = ingest(
        session,
        tenant_id,
        provider_id=mail.provider_id,
        direction="in",
        sender=sender,
        recipient=recipient,
        subject=str(message.get("Subject", "")).strip()[:500] or "(no subject)",
        body=_text_of(message) or "(no text)",
        sent_at=sent_at,
    )
    if stored is None:
        mail.status, mail.reason = "ignored", "Already in the inbox"
        return
    _store_attachments(session, tenant_id, message, stored.id, stored.thread_id)
    mail.status, mail.message_id = "ingested", stored.id


def process_pending(session: Session, tenant_id: UUID, limit: int = BATCH) -> int:
    """Each message in its own savepoint, so one bad email can't block the rest."""
    pending = session.scalars(
        select(InboundMail)
        .where(InboundMail.status == "pending")
        .order_by(InboundMail.received_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for mail in pending:
        try:
            with session.begin_nested():
                _process(session, tenant_id, mail)
        except SecurityCheckUnavailable:
            log.warning("File storage unavailable, inbound mail %s retried later", mail.id)
            continue
        except Exception as exc:  # malformed mail must not stop the queue
            log.warning("Inbound mail %s rejected: %s", mail.id, type(exc).__name__)
            mail.status, mail.reason = "rejected", "The message could not be read"
        mail.processed_at = utcnow()
        mail.raw = mail.raw if mail.status == "rejected" else None
    return len(pending)
