"""Turn an untrusted file into text, and separate out what a human reader could not see.

Hidden text (white on white, microscopic fonts, off-page, invisible render mode, hidden HTML) is
how people attack CV screeners. It is found and removed here, deterministically, before any model
is involved, and reported as a finding.

Order for every format: detect hidden text, remove it from the file itself, check that nothing
hidden is left, then let Docling read the layout (reading order, headings, tables). If Docling
fails or something hidden survives the clean-up, the plain extractor below is used instead, so a
parser problem never lets hidden text through and never loses a CV.
"""

import ctypes
import io
import logging
import os
import re
import shutil
import threading
import zipfile
from dataclasses import dataclass, field

import pdfplumber
import pypdfium2
import pypdfium2.raw as pdfium
import pytesseract
from bs4 import BeautifulSoup, Comment
from docx import Document

log = logging.getLogger(__name__)

MAX_PAGES = 15
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_TEXT_FILE_BYTES = 5 * 1024 * 1024
MIN_VISIBLE_FONT_SIZE = 3.0
WHITE_THRESHOLD = 0.92
WHITE_RGB_MIN = round(WHITE_THRESHOLD * 255)
MIN_TEXT_CHARS_PER_DOC = 40
OCR_DPI_SCALE = 2.5
OCR_LANGUAGES = "eng+fra+ara"
OCR_TIMEOUT_SECONDS = 30
DOCLING_TIMEOUT_SECONDS = 60
DOCLING_THREADS = int(os.environ.get("DOCLING_THREADS", "4"))
DOCLING_ARTIFACTS_PATH = os.environ.get("DOCLING_ARTIFACTS_PATH")  # baked into the ml image

ACCEPTED = (".pdf", ".docx", ".html", ".htm", ".md", ".txt")


class UnreadableDocument(Exception):  # noqa: N818 - a definite outcome for the caller
    pass


@dataclass
class ParseResult:
    text: str
    hidden_text: str
    pages: int
    method: str
    findings: list[str] = field(default_factory=list)
    # The visible text line by line, as a person reads it. Docling joins lines into paragraphs,
    # so identity removal looks for names and protected lines here.
    lines: str = ""


# --- Docling ------------------------------------------------------------------------------------

_converters: dict[bool, object] = {}
_docling_lock = threading.Lock()


def _converter(ocr: bool):
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    if ocr not in _converters:
        options = PdfPipelineOptions(
            artifacts_path=DOCLING_ARTIFACTS_PATH,
            do_ocr=ocr,
            do_table_structure=True,
            document_timeout=DOCLING_TIMEOUT_SECONDS,
            accelerator_options=AcceleratorOptions(num_threads=DOCLING_THREADS, device="cpu"),
        )
        if ocr:
            options.ocr_options = TesseractCliOcrOptions(
                lang=OCR_LANGUAGES.split("+"), force_full_page_ocr=True
            )
        _converters[ocr] = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.HTML],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
        )
    return _converters[ocr]


def warm_up() -> None:
    """Load the layout and table models now, so the first CV of the day isn't slow."""
    from docling.datamodel.base_models import InputFormat

    with _docling_lock:
        _converter(False).initialize_pipeline(InputFormat.PDF)


def docling_available() -> bool:
    try:
        import docling  # noqa: F401
    except ImportError:
        return False
    return True


def _docling(name: str, data: bytes, ocr: bool = False) -> str | None:
    """Docling's reading of an already-cleaned file, or None so the caller falls back."""
    if not docling_available() or (ocr and not shutil.which("tesseract")):
        return None
    from docling.datamodel.base_models import ConversionStatus
    from docling_core.types.io import DocumentStream

    try:
        with _docling_lock:
            result = _converter(ocr).convert(
                DocumentStream(name=name, stream=io.BytesIO(data)),
                max_num_pages=MAX_PAGES,
                raises_on_error=False,
            )
        if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
            log.warning("docling could not read the file: %s", result.status)
            return None
        # No escaping: "name\_x@mail" would no longer look like an email to the identity removal.
        text = result.document.export_to_markdown(
            image_placeholder="", escape_underscores=False, escape_html=False
        )
    except Exception:
        log.exception("docling failed, using the plain extractor")
        return None
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) >= MIN_TEXT_CHARS_PER_DOC else None


# --- PDF ----------------------------------------------------------------------------------------


@dataclass
class _PdfScan:
    text: str
    hidden: list[str]
    findings: set[str]
    pages: int


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


def _scan_pdf(data: bytes) -> _PdfScan:
    """Character-level check: what a reader sees, and what is hidden from them."""
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
    return _PdfScan(text, hidden_chars, findings, page_count)


def _object_text(obj, textpage) -> str:
    size = pdfium.FPDFTextObj_GetText(obj, textpage, None, 0)
    if size <= 2:
        return ""
    buffer = ctypes.create_string_buffer(size)
    pdfium.FPDFTextObj_GetText(
        obj, textpage, ctypes.cast(buffer, ctypes.POINTER(pdfium.FPDF_WCHAR)), size
    )
    return buffer.raw[: size - 2].decode("utf-16-le", errors="ignore")


def _text_object_hidden_reason(obj, width: float, height: float) -> str | None:
    if pdfium.FPDFTextObj_GetTextRenderMode(obj) == pdfium.FPDF_TEXTRENDERMODE_INVISIBLE:
        return "invisible_render_mode"
    r, g, b, a = (ctypes.c_uint() for _ in range(4))
    if pdfium.FPDFPageObj_GetFillColor(obj, r, g, b, a) and (
        a.value == 0 or min(r.value, g.value, b.value) >= WHITE_RGB_MIN
    ):
        return "invisible_colour"
    size = ctypes.c_float()
    if pdfium.FPDFTextObj_GetFontSize(obj, size):
        m = obj.get_matrix()
        if size.value * abs(m.a * m.d - m.b * m.c) ** 0.5 < MIN_VISIBLE_FONT_SIZE:
            return "microscopic_font"
    left, bottom, right, top = obj.get_bounds()
    if right < 0 or left > width or top < 0 or bottom > height:
        return "off_page"
    return None


def _clean_pdf(data: bytes) -> tuple[bytes, set[str], list[str]]:
    """Delete hidden text objects from the PDF itself, so no later reader can see them."""
    document = pypdfium2.PdfDocument(data)
    findings: set[str] = set()
    removed_text: list[str] = []
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                width, height = page.get_size()
                textpage = page.get_textpage()
                doomed = []
                # Includes text nested inside form objects.
                for obj in page.get_objects(filter=[pdfium.FPDF_PAGEOBJ_TEXT]):
                    reason = _text_object_hidden_reason(obj, width, height)
                    if reason:
                        findings.add(f"hidden_text:{reason}")
                        if reason == "invisible_render_mode":  # the character scan misses this
                            removed_text.append(_object_text(obj, textpage))
                        doomed.append(obj)
                textpage.close()  # pdfium requires this before text objects are removed
                for obj in doomed:
                    page.remove_obj(obj)
                    obj.close()
                if doomed:
                    page.gen_content()
            finally:
                page.close()
        output = io.BytesIO()
        document.save(output)
    finally:
        document.close()
    return output.getvalue(), findings, removed_text


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


def _parse_pdf(data: bytes) -> ParseResult:
    scan = _scan_pdf(data)
    findings = set(scan.findings)
    hidden = list(scan.hidden)

    if len(scan.text) < MIN_TEXT_CHARS_PER_DOC:
        # Scanned: OCR reads the rendered page, so it only sees what a person sees.
        findings.add("scanned_document_ocr")
        lines = _ocr_pdf(data)
        text = _docling("cv.pdf", data, ocr=True)
        method = "docling_ocr"
        if text is None:
            text, method = lines, "ocr"
        return ParseResult(
            text, "".join(hidden).strip(), scan.pages, method, sorted(findings), lines
        )

    try:
        clean, removed_findings, removed_text = _clean_pdf(data)
    except Exception:
        log.exception("could not clean the PDF, using the character-level text")
        return ParseResult(
            scan.text, "".join(hidden).strip(), scan.pages, "pdf_text", sorted(findings), scan.text
        )
    findings |= removed_findings
    hidden.extend(removed_text)

    recheck = _scan_pdf(clean)
    if recheck.hidden:
        # Something hidden survived the clean-up (for example inside a form object).
        # Docling would read it, so it is not used for this file.
        findings.add("hidden_text:not_removable")
        return ParseResult(
            scan.text, "".join(hidden).strip(), scan.pages, "pdf_text", sorted(findings), scan.text
        )

    text = _docling("cv.pdf", clean)
    method = "docling"
    if text is None:
        text, method = recheck.text, "pdf_text"
    return ParseResult(
        text, "".join(hidden).strip(), scan.pages, method, sorted(findings), recheck.text
    )


# --- DOCX ---------------------------------------------------------------------------------------


def _open_docx(data: bytes):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnreadableDocument("This DOCX cannot be opened") from exc
    if sum(info.file_size for info in archive.infolist()) > MAX_DOCX_UNCOMPRESSED_BYTES:
        raise UnreadableDocument("This DOCX expands to an unreasonable size")
    try:
        return Document(io.BytesIO(data))
    except Exception as exc:
        raise UnreadableDocument("This DOCX cannot be read") from exc


def _docx_paragraphs(document) -> list:
    paragraphs = list(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                paragraphs.extend(cell.paragraphs)
    for section in document.sections:
        for part in (section.header, section.footer):
            paragraphs.extend(part.paragraphs)
    return paragraphs


def _run_is_hidden(run) -> bool:
    colour = run.font.color.rgb if run.font.color and run.font.color.type else None
    tiny = run.font.size is not None and run.font.size.pt < MIN_VISIBLE_FONT_SIZE
    white = colour is not None and str(colour).upper() in {"FFFFFF", "FEFEFE", "FDFDFD"}
    return bool(run.font.hidden or tiny or white)


def _parse_docx(data: bytes) -> ParseResult:
    document = _open_docx(data)
    findings: set[str] = set()
    hidden: list[str] = []
    visible_lines: list[str] = []
    for paragraph in _docx_paragraphs(document):
        visible_runs = []
        for run in paragraph.runs:
            if _run_is_hidden(run):
                findings.add("hidden_text:docx_hidden_run")
                hidden.append(run.text)
                run._element.getparent().remove(run._element)  # gone from the file Docling reads
            else:
                visible_runs.append(run.text)
        line = "".join(visible_runs).strip()
        if line:
            visible_lines.append(line)

    clean = io.BytesIO()
    document.save(clean)
    lines = "\n".join(visible_lines)
    text = _docling("cv.docx", clean.getvalue())
    method = "docling"
    if text is None:
        text, method = lines, "docx_text"
    return ParseResult(text, " ".join(hidden).strip(), 1, method, sorted(findings), lines)


# --- HTML and Markdown --------------------------------------------------------------------------

HIDING_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(\.0+)?\s*(;|$)"
    r"|font-size\s*:\s*0|color\s*:\s*(#fff\b|#ffffff\b|white\b|rgba?\(\s*255\s*,\s*255\s*,\s*255)",
    re.IGNORECASE,
)
NEVER_SHOWN_TAGS = ("script", "style", "noscript", "template", "head", "iframe", "object")


def _decode_text(data: bytes) -> str:
    if len(data) > MAX_TEXT_FILE_BYTES:
        raise UnreadableDocument("This text file is too large")
    if b"\x00" in data:
        raise UnreadableDocument("This is not a text file")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UnreadableDocument("Text files must be UTF-8") from exc


def _clean_html(markup: str) -> tuple[str, list[str], set[str]]:
    soup = BeautifulSoup(markup, "html.parser")
    hidden: list[str] = []
    findings: set[str] = set()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        if comment.strip():
            hidden.append(comment.strip())
            findings.add("hidden_text:html_comment")
        comment.extract()
    for tag in soup.find_all(NEVER_SHOWN_TAGS):
        if tag.name != "head" and tag.get_text(strip=True):
            hidden.append(tag.get_text(" ", strip=True))
            findings.add("hidden_text:html_hidden_element")
        tag.decompose()
    for tag in soup.find_all(True):
        if tag.decomposed:
            continue
        style = tag.get("style") or ""
        if tag.has_attr("hidden") or HIDING_STYLE.search(style):
            text = tag.get_text(" ", strip=True)
            if text:
                hidden.append(text)
                findings.add("hidden_text:html_hidden_element")
            tag.decompose()
    return str(soup), hidden, findings


def _parse_html(data: bytes) -> ParseResult:
    clean, hidden, findings = _clean_html(_decode_text(data))
    soup = BeautifulSoup(clean, "html.parser")
    lines = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
    text = _docling("cv.html", clean.encode("utf-8"))
    method = "docling"
    if text is None:
        text, method = lines, "html_text"
    return ParseResult(text, " ".join(hidden).strip(), 1, method, sorted(findings), lines)


def _parse_markdown(data: bytes) -> ParseResult:
    """Markdown is already text. HTML inside it can still hide things from a reader."""
    markup = _decode_text(data)
    if "<" not in markup:
        return ParseResult(markup.strip(), "", 1, "markdown", [])
    clean, hidden, findings = _clean_html(markup)
    text = BeautifulSoup(clean, "html.parser").get_text()
    return ParseResult(text.strip(), " ".join(hidden).strip(), 1, "markdown", sorted(findings))


def parse_document(filename: str, data: bytes) -> ParseResult:
    suffix = os.path.splitext(filename.lower())[1]
    if suffix == ".pdf":
        result = _parse_pdf(data)
    elif suffix == ".docx":
        result = _parse_docx(data)
    elif suffix in (".html", ".htm"):
        result = _parse_html(data)
    elif suffix == ".md":
        result = _parse_markdown(data)
    elif suffix == ".txt":
        result = ParseResult(_decode_text(data), "", 1, "plain_text", [])
    else:
        raise UnreadableDocument("Only PDF, DOCX, HTML, Markdown and TXT are accepted")
    if not result.lines:
        result.lines = result.text
    if len(result.text.strip()) < MIN_TEXT_CHARS_PER_DOC:
        raise UnreadableDocument("No readable text was found in this document")
    return result
