"""Identity separation. Runs on the device, before any model sees the CV.

Contact details are taken out and stored apart. Name, email, phone and lines stating age, gender,
nationality, marital status or address are removed from the text used for reading and scoring.
So neither the model nor the score can depend on them.
"""

import re
from dataclasses import dataclass

from kernel.ai import pii

BLIND_TOKEN = "[CANDIDATE]"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
NAME_LINE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+){1,4}$")
NOT_A_NAME = re.compile(
    r"\b(engineer|developer|ingénieur|ingénieure|développeur|développeuse|manager|analyst|"
    r"assistant|assistante|designer|consultant|technician|comptable|accountant|stagiaire|"
    r"curriculum|vitae|resume|cv|summary|profil|experience|expérience|education|formation)\b",
    re.IGNORECASE,
)
PROTECTED_LINE = re.compile(
    r"^\s*(date of birth|birth ?date|dob|born|né|née|date de naissance|age|âge|gender|sex|sexe|"
    r"nationality|nationalité|marital status|situation familiale|married|marié|mariée|"
    r"address|adresse|religion|photo)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class Blinded:
    name: str | None
    email: str | None
    phone: str | None
    text: str
    removed_lines: int


def _guess_name(text: str) -> str | None:
    for line in text.splitlines()[:5]:
        candidate = line.strip()
        if candidate and NAME_LINE.match(candidate) and not NOT_A_NAME.search(candidate):
            return candidate
    return None


def blind(text: str) -> Blinded:
    name = _guess_name(text)
    email_match = EMAIL.search(text)
    phone_match = PHONE.search(text)
    working, removed = PROTECTED_LINE.subn("", text)
    # Mask contact details first: an email address often contains the person's name.
    working = pii.mask(working).text
    if name:
        parts = [re.escape(name), *(re.escape(p) for p in re.split(r"[ '\-]", name) if len(p) >= 3)]
        working = re.sub(
            rf"(?<!\w)(?:{'|'.join(parts)})(?!\w)", BLIND_TOKEN, working, flags=re.IGNORECASE
        )
    return Blinded(
        name=name,
        email=email_match.group() if email_match else None,
        phone=phone_match.group().strip() if phone_match else None,
        text=re.sub(r"\n{3,}", "\n\n", working).strip(),
        removed_lines=removed,
    )
