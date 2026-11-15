"""Numbered, all-caps and Unicode questions stay questions; headings stay headings.

A readable workbook with no questions is left for review. A workbook that cannot
be opened fails with a fixed message and is not stored as a successful parse.
Synthetic workbooks only. No database, network or model calls.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from app.services.xlsx_questionnaire_parser import parse_xlsx_questionnaire

# Fragments are the normalized question text. The section is the heading above
# that question, and the sheet is the workbook sheet it was read from.
EXPECTED = [
    (
        "1. do you enforce multi-factor authentication for all administrators",
        "1.0 CONTROL ENVIRONMENT",
        "Security",
    ),
    (
        "2. do you encrypt customer data at rest using aes-256",
        "1.0 CONTROL ENVIRONMENT",
        "Security",
    ),
    (
        "do you perform annual risk assessments for every production system",
        "2.0 RISK ASSESSMENT",
        "Security",
    ),
    (
        "3. describe the incident response process used after a confirmed breach",
        "2.0 RISK ASSESSMENT",
        "Security",
    ),
    (
        "do you retain audit logs for at least one year",
        "2.0 RISK ASSESSMENT",
        "Security",
    ),
    (
        "¿la organización aplica autenticación multifactor a todos los administradores",
        "2.0 RISK ASSESSMENT",
        "Security",
    ),
    (
        "贵公司是否对所有管理员强制执行多因素认证？",
        "2.0 RISK ASSESSMENT",
        "Security",
    ),
    (
        "هل تطبق المؤسسة تشفير البيانات أثناء النقل للعملاء؟",
        "2.0 RISK ASSESSMENT",
        "Security",
    ),
    (
        "εφαρμοζετε πολυπαραγοντικη ταυτοποιηση για ολους τους διαχειριστες\u037e",
        "2.0 RISK ASSESSMENT",
        "Security",
    ),
    (
        "does the company verify mailing addresses for new vendor accounts",
        "ADDRESS VERIFICATION",
        "Security",
    ),
    (
        "is physical access to the production data centre logged and reviewed",
        "1. ACCESS CONTROL",
        "Security",
    ),
    (
        "4) is a data processing agreement in place with each subprocessor",
        "PRIVACY CONTROLS",
        "Privacy",
    ),
    (
        "q12. does the company honor data subject access requests within thirty days",
        "PRIVACY CONTROLS",
        "Privacy",
    ),
]

# These cells are section titles. None of them may be stored as a question.
HEADINGS = [
    "1.0 control environment",
    "2.0 risk assessment",
    "address verification",
    "1. access control",
    "privacy controls",
]

UNREADABLE = (
    "Workbook is corrupt or unreadable. Re-export it as an .xlsx file and upload it again."
)
NO_QUESTIONS = (
    "No questions were detected in this workbook. "
    "Review the file or upload a corrected copy."
)

_GREEK = "ΕΦΑΡΜΟΖΕΤΕ ΠΟΛΥΠΑΡΑΓΟΝΤΙΚΗ ΤΑΥΤΟΠΟΙΗΣΗ ΓΙΑ ΟΛΟΥΣ ΤΟΥΣ ΔΙΑΧΕΙΡΙΣΤΕΣ\u037e"


def _sheets() -> dict[str, list[list[str]]]:
    return {
        "Security": [
            ["1.0 CONTROL ENVIRONMENT", ""],
            [
                "1. DO YOU ENFORCE MULTI-FACTOR AUTHENTICATION FOR ALL ADMINISTRATORS?",
                "Yes",
            ],
            ["2. Do you encrypt customer data at rest using AES-256?", "No"],
            ["2.0 RISK ASSESSMENT", ""],
            ["DO YOU PERFORM ANNUAL RISK ASSESSMENTS FOR EVERY PRODUCTION SYSTEM?", ""],
            ["3. Describe the incident response process used after a confirmed breach.", ""],
            ["DO YOU RETAIN AUDIT LOGS FOR AT LEAST ONE YEAR", ""],
            ["¿La organización aplica autenticación multifactor a todos los administradores?", ""],
            ["贵公司是否对所有管理员强制执行多因素认证？", ""],
            ["هل تطبق المؤسسة تشفير البيانات أثناء النقل للعملاء؟", ""],
            [_GREEK, ""],
            ["ADDRESS VERIFICATION", ""],
            ["Does the company verify mailing addresses for new vendor accounts?", "Yes"],
            ["1. ACCESS CONTROL", ""],
            ["Is physical access to the production data centre logged and reviewed?", "No"],
        ],
        "Privacy": [
            ["PRIVACY CONTROLS", ""],
            ["4) Is a data processing agreement in place with each subprocessor?", "Yes"],
            ["Q12. Does the company honor data subject access requests within thirty days?", ""],
        ],
    }


def _write(path, sheets: dict[str, list[list[str]]]) -> None:
    book = Workbook()
    first = True
    for name, rows in sheets.items():
        worksheet = book.active if first else book.create_sheet()
        first = False
        worksheet.title = name
        for row in rows:
            worksheet.append(row)
    book.save(path)


def _located(questions: list[dict]) -> list[tuple[str, str | None, str]]:
    located = []
    for question in questions:
        source = json.loads(question["source_location"])
        located.append((question["text"], question.get("section"), source["sheet"]))
    return located


def test_numbered_uppercase_and_unicode_questions_keep_their_sections(tmp_path) -> None:
    path = tmp_path / "fresh-corpus.xlsx"
    _write(path, _sheets())
    located = _located(parse_xlsx_questionnaire(path))
    assert located == EXPECTED
    texts = [text for text, _section, _sheet in located]
    for heading in HEADINGS:
        assert heading not in texts
    for text, _section, _sheet in located:
        assert not text.endswith(" yes") and not text.endswith(" no")


def test_each_sheet_starts_its_own_section(tmp_path) -> None:
    """A heading on a later sheet must not keep the previous sheet's section."""
    path = tmp_path / "two-sheets.xlsx"
    _write(path, _sheets())
    privacy = [
        question
        for question in parse_xlsx_questionnaire(path)
        if json.loads(question["source_location"])["sheet"] == "Privacy"
    ]
    assert privacy
    assert {question["section"] for question in privacy} == {"PRIVACY CONTROLS"}


@pytest.mark.parametrize(
    "payload",
    [b"this is not a workbook", b"", b"PK\x03\x04not-a-workbook"],
    ids=["text", "empty", "truncated-zip"],
)
def test_corrupt_workbook_fails_with_a_fixed_message(tmp_path, payload: bytes) -> None:
    path = tmp_path / "secret-workbook-name.xlsx"
    path.write_bytes(payload)
    with pytest.raises(Exception) as caught:
        parse_xlsx_questionnaire(path)
    message = str(caught.value)
    assert caught.value.__class__.__name__ == "WorkbookUnreadable"
    assert message == UNREADABLE
    assert "secret-workbook-name" not in message
    assert "openpyxl" not in message.lower()
    assert "Traceback" not in message
    from app.core.job_errors import classify, is_retryable_code

    assert classify(caught.value) == "bad_input"
    assert is_retryable_code("bad_input") is False


def test_zero_question_workbook_is_readable_and_needs_review(tmp_path, monkeypatch) -> None:
    path = tmp_path / "headings-only.xlsx"
    _write(
        path,
        {
            "Notes": [
                ["1. ACCESS CONTROL"],
                ["ADDRESS VERIFICATION"],
                ["2.0 RISK ASSESSMENT"],
                ["Notes for the reviewer"],
                ["See the attached policy"],
            ]
        },
    )
    assert parse_xlsx_questionnaire(path) == []

    from app import worker

    blob = path.read_bytes()
    questionnaire = SimpleNamespace(
        id=1,
        workspace_id=1,
        filename="headings-only.xlsx",
        storage_key="raw/1/headings.xlsx",
        status="uploaded",
        parse_metadata=None,
        deleted_at=None,
    )
    job = SimpleNamespace(id=2, workspace_id=1, attempt=1, result=None)
    session = _Session(questionnaire)

    class _Store:
        bucket_raw = "raw"

        def download(self, _bucket: str, _key: str) -> bytes:
            return blob

    class _Effects:
        def __init__(self, _session, _job) -> None:
            self.detail = None

        def is_applied(self, _effect: str) -> bool:
            return False

        def mark_applied(self, _effect: str, detail=None) -> None:
            self.detail = detail

    monkeypatch.setattr(worker, "StorageClient", lambda: _Store())
    monkeypatch.setattr(worker, "JobEffects", _Effects)
    monkeypatch.setattr(worker, "_auto_classify_questionnaire", lambda *_a, **_k: None)
    worker.run_parse_questionnaire(
        job,
        session,
        {"questionnaire_id": 1, "storage_key": "raw/1/headings.xlsx"},
    )
    assert questionnaire.status == "needs_review"
    meta = json.loads(questionnaire.parse_metadata)
    assert meta["count"] == 0
    assert meta["questions"] == []
    assert meta["review"] == NO_QUESTIONS
    assert json.loads(job.result)["outcome"] == "needs_review"


def test_corrupt_workbook_fails_before_it_is_marked_parsed(tmp_path, monkeypatch) -> None:
    from app import worker

    blob = b"this is not a workbook"
    questionnaire = SimpleNamespace(
        id=3,
        workspace_id=1,
        filename="secret-workbook-name.xlsx",
        storage_key="raw/1/secret.xlsx",
        status="uploaded",
        parse_metadata=None,
        deleted_at=None,
    )
    job = SimpleNamespace(id=4, workspace_id=1, attempt=1, result=None)
    session = _Session(questionnaire)

    class _Store:
        bucket_raw = "raw"

        def download(self, _bucket: str, _key: str) -> bytes:
            return blob

    class _Effects:
        def __init__(self, _session, _job) -> None:
            pass

        def is_applied(self, _effect: str) -> bool:
            return False

        def mark_applied(self, _effect: str, detail=None) -> None:
            self.detail = detail

    monkeypatch.setattr(worker, "StorageClient", lambda: _Store())
    monkeypatch.setattr(worker, "JobEffects", _Effects)
    with pytest.raises(Exception) as caught:
        worker.run_parse_questionnaire(
            job,
            session,
            {"questionnaire_id": 3, "storage_key": "raw/1/secret.xlsx"},
        )
    assert caught.value.__class__.__name__ == "WorkbookUnreadable"
    assert str(caught.value) == UNREADABLE
    assert "secret-workbook-name" not in str(caught.value)
    assert questionnaire.status == "uploaded"
    worker.apply_questionnaire_parse_failure(questionnaire, caught.value)
    assert questionnaire.status == "failed"
    assert json.loads(questionnaire.parse_metadata) == {"count": 0, "error": UNREADABLE}
    from app.services.pdf_text import NO_TEXT_MESSAGE, PdfNoTextError

    pdf = SimpleNamespace(status="uploaded", parse_metadata=None)
    assert worker.apply_questionnaire_parse_failure(pdf, PdfNoTextError()) is True
    assert pdf.status == "failed"
    assert json.loads(pdf.parse_metadata) == {"count": 0, "error": NO_TEXT_MESSAGE}
    assert worker.apply_questionnaire_parse_failure(pdf, RuntimeError("internal")) is False


class _Query:
    def __init__(self, value, count: int) -> None:
        self._value = value
        self._count = count

    def filter(self, *_args, **_kwargs):
        return self

    def populate_existing(self):
        return self

    def with_for_update(self):
        return self

    def first(self):
        return self._value

    def count(self) -> int:
        return self._count

    def all(self) -> list:
        return []


class _Session:
    def __init__(self, questionnaire) -> None:
        self.questionnaire = questionnaire
        self.added: list = []
        self.committed = False

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "Question":
            return _Query(None, 0)
        return _Query(self.questionnaire, 1)

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass
