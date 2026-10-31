"""Email adapter. The Message-ID derives from the idempotency key, so a send can be reconciled."""

import os
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

from kernel.canonical import sha256_hex
from kernel.schedule import ics
from kernel.trust import AdapterRejected

DEFAULT_ALLOWED_DOMAINS = "example.test,mail.example.test,cds.example.test"
SENDER_ADDRESS = "no-reply@cds.example.test"
SENDER = f"AstraRH <{SENDER_ADDRESS}>"
SMTP_TIMEOUT_SECONDS = 10


def message_id(key: str) -> str:
    return f"<{sha256_hex(key)[:40]}@astrarh.example.test>"


def _allowed_domains() -> set[str]:
    return set(os.environ.get("MAIL_ALLOWED_DOMAINS", DEFAULT_ALLOWED_DOMAINS).split(","))


def build(payload: dict[str, Any], key: str) -> EmailMessage:
    """Check the payload and build the message. No network, so it can be tested on its own."""
    recipient = str(payload.get("to", ""))
    domain = recipient.rsplit("@", 1)[-1].lower()
    if "@" not in recipient or domain not in _allowed_domains():
        raise AdapterRejected(f"Destination domain {domain!r} is not allowed")
    if not payload.get("subject") or not payload.get("body"):
        raise AdapterRejected("An email needs a subject and a body")

    message = EmailMessage()
    message["From"] = SENDER
    message["To"] = recipient
    message["Subject"] = payload["subject"]
    message["Message-ID"] = message_id(key)
    message.set_content(payload["body"])
    if payload.get("invite"):
        try:
            calendar = ics.render(payload["invite"], SENDER_ADDRESS)
        except ValueError as exc:  # pydantic's ValidationError is a ValueError
            raise AdapterRejected(f"The calendar invite is invalid: {exc}") from exc
        if recipient not in payload["invite"]["attendees"]:
            raise AdapterRejected("The invite must list the person it is sent to")
        message.add_attachment(
            calendar,
            subtype="calendar",
            filename="invite.ics",
            params={"method": payload["invite"]["method"]},
        )
    return message


def send(payload: dict[str, Any], key: str) -> str:
    message = build(payload, key)
    with smtplib.SMTP(
        os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]), timeout=SMTP_TIMEOUT_SECONDS
    ) as client:
        client.send_message(message)
    return message["Message-ID"]


def find(key: str) -> str | None:
    """Ask the mailbox whether this send arrived. Mailpit's API stands in for a real provider's."""
    wanted = message_id(key)
    response = httpx.get(
        f"http://{os.environ['SMTP_HOST']}:8025/api/v1/search",
        params={"query": f"message-id:{wanted.strip('<>')}"},
        timeout=SMTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return wanted if response.json().get("messages_count", 0) > 0 else None
