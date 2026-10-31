"""Mask direct identifiers before text reaches a model provider.

Regex covers emails, phones, URLs and national-ID-like numbers. Name detection with Presidio
joins in the ml service during Phase 4. If masking fails, the gateway denies the call.
"""

import re
from dataclasses import dataclass

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{7,}\d(?![\w.])")
LONG_NUMBER = re.compile(r"(?<![\w.])\d{8,}(?![\w.])")
# CV dates look like phone numbers to the pattern above, and must survive masking.
DATE_LIKE = re.compile(
    r"^(?:\d{4}\s*[-–/]\s*\d{4}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})$"
)


@dataclass(frozen=True)
class MaskResult:
    text: str
    counts: dict[str, int]


def mask(text: str) -> MaskResult:
    counts: dict[str, int] = {}

    def apply(pattern: re.Pattern, label: str, value: str) -> str:
        value, count = pattern.subn(f"[{label}]", value)
        if count:
            counts[label] = count
        return value

    def mask_phone(match: re.Match) -> str:
        if DATE_LIKE.match(match.group()):
            return match.group()
        counts["PHONE"] = counts.get("PHONE", 0) + 1
        return "[PHONE]"

    masked = apply(EMAIL, "EMAIL", text)
    masked = apply(URL, "URL", masked)
    masked = PHONE.sub(mask_phone, masked)
    masked = apply(LONG_NUMBER, "NUMBER", masked)
    return MaskResult(masked, counts)
