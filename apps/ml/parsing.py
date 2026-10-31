"""Turn an untrusted file into text, and separate out what a human reader could not see.

Hidden text (white on white, microscopic fonts, off-page) is how people attack CV screeners.
It is removed here, deterministically, before any model is involved, and reported as a finding.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field

import pdfplumber
import pypdfium2
import pytesseract
from docx import Document

MAX_PAGES = 15
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MIN_VISIBLE_FONT_SIZE = 3.0
WHITE_THRESHOLD = 0.92
MIN_TEXT_CHARS_PER_DOC = 40
OCR_DPI_SCALE = 2.5
OCR_LANGUAGES = "eng+fra+ara"
OCR_TIMEOUT_SECONDS = 30


class UnreadableDocument(Exception):  # noqa: N818 - a definite outcome for the caller
    pass


@dataclass
class ParseResult:
    text: str
    hidden_text: str
    pages: int
    method: str
    findings: list[str] = field(default_factory=list)


def _is_invisible_colour(colour) -> bool:
    if colour is None:
        return False
    values = colour if isinstance(colour, list | tuple) else [colour]
    if not values or not all(isinstance(v, int | float) for v in values):
        return False
    if len(values) in (1, 3):
        return all(v >= WHITE_THRESHOLD for v in values)
    if len(values) == 4:  # CMYK: white is all zeros
        return all(v <= 1 - WHITE_THRESHOLD for v in values)
    return False


def _char_hidden_reason(char: dict, page) -> str | None:
    if _is_invisible_colour(char.get("non_stroking_color")):
        return "invisible_colour"
    if char.get("size", 12) < MIN_VISIBLE_FONT_SIZE:
        return "microscopic_font"
    x0, top = char.get("x0", 0), char.get("top", 0)
    if x0 < 0 or x0 > page.width or top < 0 or top > page.height:
        return "off_page"
    return None


def _visible_only(reasons: dict[int, str | None]):
    def keep(obj: dict) -> bool:
        return obj.get("object_type") != "char" or not reasons.get(id(obj))

    return keep


def _parse_pdf(data: bytes) -> ParseResult:
    findings: set[str] = set()
    visible_pages: list[str] = []
    hidden_chars: list[str] = []
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:
        raise UnreadableDocument("This PDF cannot be opened") from exc
    with pdf:
        if pdf.doc.encryption:
            raise UnreadableDocument("Encrypted PDFs are not accepted")
        page_count = len(pdf.pages)
        if page_count > MAX_PAGES:
            raise UnreadableDocument(f"This PDF has more than {MAX_PAGES} pages")
        for page in pdf.pages:
            reasons = {id(c): _char_hidden_reason(c, page) for c in page.chars}
            for char in page.chars:
                reason = reasons[id(char)]
                if reason:
                    findings.add(f"hidden_text:{reason}")
                    hidden_chars.append(char.get("text", ""))
            visible = page.filter(_visible_only(reasons))
            visible_pages.append(visible.extract_text() or "")

    text = "\n\n".join(p.strip() for p in visible_pages if p.strip())
    if len(text) >= MIN_TEXT_CHARS_PER_DOC:
        method = "pdf_text"
    else:
        text = _ocr_pdf(data)
        method = "ocr"
        findings.add("scanned_document_ocr")
    return ParseResult(text, "".join(hidden_chars).strip(), page_count, method, sorted(findings))


def _ocr_pdf(data: bytes) -> str:
    try:
        document = pypdfium2.PdfDocument(data)
    except Exception as exc:
        raise UnreadableDocument("This PDF cannot be rendered") from exc
    pages = []
    for index in range(min(len(document), MAX_PAGES)):
        image = document[index].render(scale=OCR_DPI_SCALE).to_pil()
        try:
            pages.append(
                pytesseract.image_to_string(image, lang=OCR_LANGUAGES, timeout=OCR_TIMEOUT_SECONDS)
            )
        except RuntimeError as exc:
            raise UnreadableDocument("Reading this scanned document took too long") from exc
    return "\n\n".join(p.strip() for p in pages if p.strip())


def _parse_docx(data: bytes) -> ParseResult:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnreadableDocument("This DOCX cannot be opened") from exc
    if sum(info.file_size for info in archive.infolist()) > MAX_DOCX_UNCOMPRESSED_BYTES:
        raise UnreadableDocument("This DOCX expands to an unreasonable size")
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise UnreadableDocument("This DOCX cannot be read") from exc

    findings: set[str] = set()
    hidden: list[str] = []
    paragraphs: list[str] = []
    all_paragraphs = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                all_paragraphs.extend(cell.paragraphs)
    for paragraph in all_paragraphs:
        visible_runs = []
        for run in paragraph.runs:
            colour = run.font.color.rgb if run.font.color and run.font.color.type else None
            tiny = run.font.size is not None and run.font.size.pt < MIN_VISIBLE_FONT_SIZE
            white = colour is not None and str(colour).upper() in {"FFFFFF", "FEFEFE", "FDFDFD"}
            if run.font.hidden or tiny or white:
                findings.add("hidden_text:docx_hidden_run")
                hidden.append(run.text)
            else:
                visible_runs.append(run.text)
        line = "".join(visible_runs).strip()
        if line:
            paragraphs.append(line)
    return ParseResult(
        "\n".join(paragraphs), " ".join(hidden).strip(), 1, "docx_text", sorted(findings)
    )


def parse_document(filename: str, data: bytes) -> ParseResult:
    suffix = re.sub(r"^.*(\.[^.]+)$", r"\1", filename.lower())
    if suffix == ".pdf":
        result = _parse_pdf(data)
    elif suffix == ".docx":
        result = _parse_docx(data)
    elif suffix == ".txt":
        result = ParseResult(data.decode("utf-8"), "", 1, "plain_text", [])
    else:
        raise UnreadableDocument("Only PDF, DOCX and TXT are accepted")
    if len(result.text.strip()) < MIN_TEXT_CHARS_PER_DOC:
        raise UnreadableDocument("No readable text was found in this document")
    return result
