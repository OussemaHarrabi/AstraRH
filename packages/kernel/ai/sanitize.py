"""Clean untrusted text and report what was hidden in it. The findings are shown to humans."""

import html
import re
import unicodedata
from dataclasses import dataclass, field

ZERO_WIDTH = {chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD)}
BIDI_CONTROLS = {chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))}
TAG_CHARS = range(0xE0000, 0xE0080)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
HTML_BLOCK = re.compile(r"<(script|style)\b.*?</\1\s*>", re.DOTALL | re.IGNORECASE)
HTML_TAG = re.compile(r"</?[a-zA-Z][^<>]{0,500}>")
MAX_CHARS = 200_000


@dataclass
class SanitizedText:
    text: str
    findings: list[str] = field(default_factory=list)
    truncated: bool = False


def sanitize(raw: str) -> SanitizedText:
    findings: list[str] = []

    hidden = sum(1 for ch in raw if ch in ZERO_WIDTH)
    if hidden:
        findings.append(f"zero_width_characters:{hidden}")
    bidi = sum(1 for ch in raw if ch in BIDI_CONTROLS)
    if bidi:
        findings.append(f"bidi_controls:{bidi}")
    tags = sum(1 for ch in raw if ord(ch) in TAG_CHARS)
    if tags:
        findings.append(f"unicode_tag_characters:{tags}")

    text = "".join(
        ch
        for ch in raw
        if ch not in ZERO_WIDTH and ch not in BIDI_CONTROLS and ord(ch) not in TAG_CHARS
    )

    comments = HTML_COMMENT.findall(text)
    if comments:
        findings.append(f"html_comments:{len(comments)}")
    text = HTML_COMMENT.sub(" ", text)
    if HTML_BLOCK.search(text):
        findings.append("script_or_style_block")
    text = HTML_BLOCK.sub(" ", text)
    if HTML_TAG.search(text):
        findings.append("html_tags")
    text = HTML_TAG.sub(" ", text)
    text = html.unescape(text)

    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) != "Cc")
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    truncated = len(text) > MAX_CHARS
    if truncated:
        findings.append("oversized_input_truncated")
        text = text[:MAX_CHARS]
    return SanitizedText(text=text, findings=findings, truncated=truncated)
