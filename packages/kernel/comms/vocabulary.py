"""Sorting labels, kept free of agent code so the API can import them without a model stack."""

from typing import Literal

MessageType = Literal[
    "application",
    "availability",
    "reschedule",
    "question",
    "offer_or_salary",
    "legal_or_complaint",
    "visa_or_permit",
    "policy_question",
    "internal",
    "spam",
    "other",
]

Urgency = Literal["high", "normal", "low"]
