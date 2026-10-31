"""Injection detection: one layer, never the only one. Isolation is the real defence.

Heuristics always run. The remote classifier adds recall when configured. If it is configured
and fails, the input is flagged for human review instead of treated as clean (fail closed).
"""

import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field

log = logging.getLogger("astra.guard")

PATTERNS = {
    "instruction_override": (
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|system)\b"
        r".{0,40}\b(instruction|prompt|rule|direction)s?\b",
        r"\b(ignore[zr]?|oublie[zr]?)\b.{0,40}\b(instructions?|consignes?|r[eè]gles?)\b",
        r"تجاهل.{0,30}(التعليمات|الأوامر)",
    ),
    "role_manipulation": (
        r"\byou are now\b",
        r"\bact as (an?|the) (admin|administrator|system|recruiter|developer)\b",
        r"\bnew (system )?(instructions?|prompt)\b",
        r"\b(system|assistant)\s*:\s",
        r"\btu es maintenant\b",
    ),
    "ranking_manipulation": (
        r"\b(rank|score|rate|shortlist|recommend|select|hire)\b.{0,40}"
        r"\b(me|this candidate|this applicant)\b.{0,40}\b(first|top|highest|#?1|best|immediately)\b",
        r"\b(give|assign)\b.{0,30}\b(highest|maximum|perfect|top|100)\b.{0,20}\b(score|rating|rank)\b",
        r"\bclasse[zr]?\b.{0,40}\b(premier|premi[eè]re|meilleur)\b",
    ),
    "exfiltration": (
        r"\b(send|forward|email|post|upload)\b.{0,60}\b(to|at)\b.{0,40}(https?://|[\w.+-]+@[\w-]+\.\w+)",
        r"\b(reveal|print|show|repeat|output)\b.{0,40}\b(system prompt|your instructions|api key|password)\b",
    ),
    "tool_invocation": (
        r"\b(call|invoke|execute|use)\b.{0,20}\b(tool|function|command)\b",
        r"<\s*/?\s*(tool_use|function_calls?|invoke|system)\b",
    ),
}
COMPILED = {
    name: [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]
    for name, patterns in PATTERNS.items()
}
REMOTE_CHUNK_CHARS = 1500
REMOTE_MAX_CHUNKS = 3


@dataclass
class GuardVerdict:
    flagged: bool
    reasons: list[str] = field(default_factory=list)
    remote_checked: bool = False
    remote_failed: bool = False


def heuristic_scan(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text)
    return [
        name
        for name, patterns in COMPILED.items()
        if any(pattern.search(normalized) for pattern in patterns)
    ]


def remote_enabled() -> bool:
    return bool(os.environ.get("GROQ_API_KEY")) and os.environ.get("GUARD_REMOTE", "off") == "on"


def _remote_scan(text: str) -> bool:
    """True when Groq's prompt guard labels any sampled chunk as malicious."""
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["GROQ_API_KEY"],
        base_url="https://api.groq.com/openai/v1",
        timeout=15,
        max_retries=1,
    )
    chunks = [
        text[i : i + REMOTE_CHUNK_CHARS]
        for i in range(
            0, min(len(text), REMOTE_CHUNK_CHARS * REMOTE_MAX_CHUNKS), REMOTE_CHUNK_CHARS
        )
    ]
    for chunk in chunks:
        response = client.chat.completions.create(
            model=os.environ["LLM_GUARD_MODEL"],
            messages=[{"role": "user", "content": chunk}],
            max_completion_tokens=8,
        )
        label = (response.choices[0].message.content or "").upper()
        if "MALICIOUS" in label or "JAILBREAK" in label or "INJECTION" in label:
            return True
    return False


def scan(text: str) -> GuardVerdict:
    reasons = heuristic_scan(text)
    verdict = GuardVerdict(flagged=bool(reasons), reasons=reasons)
    if remote_enabled():
        verdict.remote_checked = True
        try:
            if _remote_scan(text):
                verdict.flagged = True
                verdict.reasons.append("remote_classifier")
        except Exception as exc:  # noqa: BLE001 - any failure of this check must fail closed
            log.warning("Remote guard failed: %s", type(exc).__name__)
            verdict.flagged = True
            verdict.remote_failed = True
            verdict.reasons.append("guard_unavailable")
    return verdict
