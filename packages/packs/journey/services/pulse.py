"""Canonical D7/30/60/90 pulse questions.

Structured self-report only. Free text is stored for a human to read; nothing
here infers sentiment, mood or flight risk.
"""

from typing import Any

PULSE_QUESTIONS: dict[str, list[dict[str, Any]]] = {
    "day7": [
        {
            "id": "role_clarity",
            "type": "scale",
            "text": "I know what my role is expected to deliver in the first 30 days.",
        },
        {
            "id": "access_ready",
            "type": "scale",
            "text": "I have the accounts and tools I need to do my work.",
        },
        {
            "id": "buddy_contact",
            "type": "scale",
            "text": "I know who my buddy is and how to reach them.",
        },
        {
            "id": "first_week_tasks",
            "type": "scale",
            "text": "I know which tasks are due this week.",
        },
        {
            "id": "blockers_text",
            "type": "text",
            "required": False,
            "text": "What is blocking you right now?",
        },
    ],
    "day30": [
        {
            "id": "role_clarity",
            "type": "scale",
            "text": "I know what my role is expected to deliver by day 60.",
        },
        {
            "id": "first_contribution",
            "type": "scale",
            "text": "I have completed a first contribution with evidence.",
        },
        {
            "id": "manager_feedback",
            "type": "scale",
            "text": "I have received specific feedback from my manager.",
        },
        {
            "id": "team_context",
            "type": "scale",
            "text": "I know who to ask for each part of my work.",
        },
        {
            "id": "blockers_text",
            "type": "text",
            "required": False,
            "text": "What is blocking you right now?",
        },
    ],
    "day60": [
        {
            "id": "independent_work",
            "type": "scale",
            "text": "I can complete my core tasks without step-by-step help.",
        },
        {
            "id": "wider_context",
            "type": "scale",
            "text": "I understand how my work affects other teams.",
        },
        {
            "id": "learning_progress",
            "type": "scale",
            "text": "I have made progress on the gaps in my role profile.",
        },
        {
            "id": "manager_support",
            "type": "scale",
            "text": "I have a useful 1:1 cadence with my manager.",
        },
        {
            "id": "blockers_text",
            "type": "text",
            "required": False,
            "text": "What is blocking you right now?",
        },
    ],
    "day90": [
        {
            "id": "role_readiness",
            "type": "scale",
            "text": "I have what I need to do my role independently.",
        },
        {
            "id": "contribution",
            "type": "scale",
            "text": "I have delivered work that the team uses.",
        },
        {
            "id": "training_application",
            "type": "scale",
            "text": "I have applied at least one thing from my training at work.",
        },
        {
            "id": "team_integration",
            "type": "scale",
            "text": "I know who to ask and how decisions are made.",
        },
        {
            "id": "blockers_text",
            "type": "text",
            "required": False,
            "text": "What is blocking you right now?",
        },
    ],
}


def questions_for(kind: str) -> list[dict[str, Any]]:
    """A copy so a request cannot mutate the module-level survey definition."""
    return [dict(question) for question in PULSE_QUESTIONS.get(kind, [])]
