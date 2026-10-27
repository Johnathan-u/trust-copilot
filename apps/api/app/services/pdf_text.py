"""PDF text extraction behind one interface (TC-01-003a, replaces PyMuPDF).

Backend: pypdf (BSD-3-Clause). Text-bearing PDFs only. There is no OCR, so a PDF
without a text layer (for example a scan) fails with ``PdfNoTextError``. Callers
depend on this module, not on the PDF library, so the backend can be swapped again
without touching the parsers.

pypdf is a hard import: if it is missing, importing this module fails, which fails
API startup (``app.main`` imports it) and worker startup (``app.worker`` imports the
parsers at module level). There is no per-request "library missing" path.

Every ``PdfTextError`` has a fixed, user-readable message as its ``str()``. It never
contains the file path, the backend's exception text or a traceback, so the worker can
store it as the job error / document ``index_error`` and the API can return it as-is.
The internal cause is kept on ``.detail`` and logged server-side only.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pypdf
from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

BACKEND = "pypdf"
BACKEND_VERSION = pypdf.__version__

NO_TEXT_MESSAGE = (
    "This PDF has no text layer; OCR isn't supported. "
    "Upload a text-based PDF, DOCX or XLSX instead."
)
ENCRYPTED_MESSAGE = (
    "PDF is encrypted or corrupt: it is password-protected. " "Upload an unencrypted copy."
)
UNREADABLE_MESSAGE = (
    "PDF is encrypted or corrupt: the file could not be read. " "Re-export it and upload it again."
)


class PdfTextError(ValueError):
    """Base class for PDF text extraction failures (always explicit, never silent).

    ``str(err)`` is the fixed user-facing message; ``err.detail`` is internal only.
    """

    user_message = UNREADABLE_MESSAGE

    def __init__(self, detail: str | None = None):
        super().__init__(self.user_message)
        self.detail = detail


class PdfUnreadableError(PdfTextError):
    """The file is not a PDF, or is too damaged to read."""

    user_message = UNREADABLE_MESSAGE


class PdfEncryptedError(PdfTextError):
    """The PDF needs a password to open. Only empty-user-password PDFs are opened."""

    user_message = ENCRYPTED_MESSAGE


class PdfNoTextError(PdfTextError):
    """The PDF has no extractable text layer (e.g. image-only scan). OCR is not supported."""

    user_message = NO_TEXT_MESSAGE


def _fail(cls: type[PdfTextError], what: str, e: BaseException | None = None) -> PdfTextError:
    detail = what if e is None else f"{what}: {type(e).__name__}: {e}"
    # Server-side log only; the path is deliberately not included.
    logger.warning("pdf_text: %s (%s)", cls.__name__, detail)
    return cls(detail)


def _reader(path: str | Path) -> PdfReader:
    try:
        reader = PdfReader(str(path))
    except (PdfReadError, Exception) as e:  # noqa: BLE001 - pypdf raises assorted errors
        raise _fail(PdfUnreadableError, "open failed", e) from e
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception as e:  # noqa: BLE001 - e.g. AES without cryptography, bad handler
            raise _fail(PdfEncryptedError, "decrypt failed", e) from e
        if not ok:
            raise _fail(PdfEncryptedError, "user password required")
    return reader


def extract_page_texts(path: str | Path) -> list[str]:
    """Return the text of every page, in page order (index 0 is page 1).

    Pages without text are returned as "" so page numbers stay aligned. Text follows
    the content-stream order, as PyMuPDF ``page.get_text()`` did. Raises
    PdfUnreadableError or PdfEncryptedError, never returns a partial result silently.
    """
    reader = _reader(path)
    try:
        pages = reader.pages
        count = len(pages)
    except Exception as e:  # noqa: BLE001
        raise _fail(PdfUnreadableError, "page tree unreadable", e) from e
    if count == 0:
        raise _fail(PdfUnreadableError, "no readable pages")
    texts = []
    for i in range(count):
        try:
            texts.append(pages[i].extract_text() or "")
        except Exception as e:  # noqa: BLE001
            raise _fail(PdfUnreadableError, f"content unreadable on page {i + 1}", e) from e
    return texts


def has_text(page_texts: list[str]) -> bool:
    return any(t.strip() for t in page_texts)


def require_text(page_texts: list[str]) -> list[str]:
    """Return page_texts, or raise PdfNoTextError if no page has a text layer."""
    if not has_text(page_texts):
        raise _fail(PdfNoTextError, "no extractable text on any page")
    return page_texts
