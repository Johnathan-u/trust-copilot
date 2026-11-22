"""Evidence parsers: PDF (DOC-03), DOCX (DOC-04), XLSX (DOC-05)."""

from pathlib import Path
from typing import Iterator

from app.services.evidence_format import DocxUnreadableError, EvidenceFormatError, LegacyOfficeError
from app.services.pdf_text import extract_page_texts, require_text


def parse_pdf(path: str | Path) -> Iterator[dict]:
    """Extract text and structure from PDF (DOC-03).

    Yields one item per page that has text. Raises pdf_text.PdfNoTextError when no page
    has a text layer (image-only scan; no OCR), and PdfUnreadableError /
    PdfEncryptedError for damaged or password-protected files. Their messages are
    user-readable and become the document's index_error.
    """
    page_texts = require_text(extract_page_texts(path))
    for i, text in enumerate(page_texts):
        if text.strip():
            yield {"page": i + 1, "text": text.strip()}


def parse_docx(path: str | Path) -> Iterator[dict]:
    """Extract text from DOCX (DOC-04).

    A package that cannot be opened raises DocxUnreadableError. Its message is
    fixed and has no path. A missing python-docx install yields nothing. Legacy
    .doc is rejected by parse_evidence and is not passed here.
    """
    try:
        from docx import Document
    except ImportError:
        return
    try:
        doc = Document(path)
    except Exception as exc:
        raise DocxUnreadableError(detail=type(exc).__name__) from exc
    for i, para in enumerate(doc.paragraphs):
        if para.text.strip():
            yield {"section": i, "text": para.text.strip()}
    for tbl in doc.tables:
        for row in tbl.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                yield {"text": " | ".join(cells)}


def parse_xlsx_evidence(path: str | Path) -> Iterator[dict]:
    """Extract text from XLSX evidence (DOC-05)."""
    from app.services.xlsx_parser import iter_sheets

    for sheet_name, rows in iter_sheets(path):
        for ri, row in enumerate(rows):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                yield {"sheet": sheet_name, "row": ri + 1, "text": " | ".join(cells)}


def parse_plain_text(path: str | Path) -> list[dict]:
    """Extract text from plain .txt for evidence indexing."""
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    return [{"text": text}]


def parse_evidence(path: str | Path) -> list[dict]:
    """Dispatch to the parser for this extension.

    .doc and .xls raise LegacyOfficeError before any office library is imported,
    whether or not python-docx or openpyxl is installed. A .docx that is not a
    readable package raises DocxUnreadableError. A readable file with no text
    returns an empty list.
    """
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".pdf":
        return list(parse_pdf(path))
    if ext in {".doc", ".xls"}:
        raise LegacyOfficeError()
    if ext == ".docx":
        try:
            return list(parse_docx(path))
        except EvidenceFormatError:
            raise
        except Exception as exc:
            raise DocxUnreadableError(detail=type(exc).__name__) from exc
    if ext == ".xlsx":
        return list(parse_xlsx_evidence(path))
    if ext == ".txt":
        return parse_plain_text(path)
    return []
