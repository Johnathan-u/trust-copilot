"""Fixed evidence-format failures (TC-08-002).

Each error's ``str()`` is one stable reason plus one next action. It never
includes the path, the file bytes, or the parser's own exception text. The
internal cause stays on ``detail`` and is not shown to the user. ``code`` is
the stable reason code.
"""

from __future__ import annotations


class EvidenceFormatError(ValueError):
    """An evidence file that cannot be indexed. ``str(err)`` is safe to store."""

    code = "evidence_unreadable"
    summary = "This file could not be read as evidence."
    next_action = "Upload a text-based PDF, DOCX, XLSX, or TXT file."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(f"{self.summary} {self.next_action}")


class WorkbookCorruptError(EvidenceFormatError):
    """An .xlsx that could not be opened, or whose every sheet failed to read."""

    code = "workbook_corrupt"
    summary = "Workbook is corrupt or unreadable."
    next_action = "Re-export it as an .xlsx file and upload it again."


class LegacyOfficeError(EvidenceFormatError):
    """A legacy .doc or .xls file. Raised before any office library is called."""

    code = "legacy_office"
    summary = "Legacy .doc and .xls files are not supported."
    next_action = "Save the file as .docx or .xlsx and upload that copy."


class DocxUnreadableError(EvidenceFormatError):
    """A .docx package that python-docx could not open."""

    code = "docx_unreadable"
    summary = "This Word file could not be read."
    next_action = "Re-save it as a .docx file and upload it again."


class EmptyEvidenceError(EvidenceFormatError):
    """A parse that produced no text. The document must not be indexed."""

    code = "empty_evidence"
    summary = "This file has no extractable text."
    next_action = "Upload a file that contains text."
