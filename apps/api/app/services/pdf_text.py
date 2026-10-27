"""PDF text extraction behind one interface (TC-01-003a, replaces PyMuPDF).

Backend: pypdf (BSD-3-Clause). Text-bearing PDFs only. There is no OCR, so a PDF
without a text layer (for example a scan) reports no text and the callers fail
explicitly. Callers depend on this module, not on the PDF library, so the backend
can be swapped again without touching the parsers.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BACKEND = "pypdf"


class PdfTextError(ValueError):
    """Base class for PDF text extraction failures (always explicit, never silent)."""


class PdfUnreadableError(PdfTextError):
    """The file is not a PDF, or is too damaged to read."""


class PdfEncryptedError(PdfTextError):
    """The PDF needs a password to open. Only empty-user-password PDFs are opened."""


class PdfNoTextError(PdfTextError):
    """The PDF has no extractable text layer (e.g. image-only scan). OCR is not supported."""


class PdfSupportUnavailableError(RuntimeError):
    """The PDF backend library is not installed."""


def _reader(path: str | Path):
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as e:  # pragma: no cover - dependency is declared in pyproject
        raise PdfSupportUnavailableError(
            "PDF support requires the 'pypdf' package; install the API dependencies"
        ) from e
    try:
        reader = PdfReader(str(path))
    except PdfReadError as e:
        raise PdfUnreadableError(f"Unreadable PDF: {e}") from e
    except Exception as e:  # noqa: BLE001 - pypdf raises assorted errors on damaged input
        raise PdfUnreadableError(f"Unreadable PDF: {type(e).__name__}: {e}") from e
    if reader.is_encrypted:
        try:
            ok = reader.decrypt("")
        except Exception as e:  # noqa: BLE001 - e.g. AES without cryptography, bad handler
            raise PdfEncryptedError(f"Encrypted PDF could not be opened: {e}") from e
        if not ok:
            raise PdfEncryptedError("Encrypted PDF requires a password; not supported")
    return reader


def extract_page_texts(path: str | Path) -> list[str]:
    """Return the text of every page, in page order (index 0 is page 1).

    Pages without text are returned as "" so page numbers stay aligned. Text follows
    the content-stream order, as PyMuPDF ``page.get_text()`` did. Raises
    PdfUnreadableError, PdfEncryptedError or PdfSupportUnavailableError, never returns
    a partial result silently.
    """
    reader = _reader(path)
    try:
        pages = reader.pages
        count = len(pages)
    except Exception as e:  # noqa: BLE001
        raise PdfUnreadableError(f"Unreadable PDF page tree: {type(e).__name__}: {e}") from e
    if count == 0:
        raise PdfUnreadableError("PDF has no readable pages")
    texts = []
    for i in range(count):
        try:
            texts.append(pages[i].extract_text() or "")
        except Exception as e:  # noqa: BLE001
            raise PdfUnreadableError(
                f"Unreadable PDF content on page {i + 1}: {type(e).__name__}: {e}"
            ) from e
    return texts


def has_text(page_texts: list[str]) -> bool:
    return any(t.strip() for t in page_texts)
