"""Intake rejects macro, encrypted and legacy workbooks before anything is stored.

The rejection text is ``UnsupportedWorkbookStructure``, the same sentence
``reject_unsupported_workbook`` raises for export. A rejected upload creates no
questionnaire, question, job or stored object. A normal xlsx is accepted, its
questions are stored, and named ranges, merges, validations and styles survive
export. Fixtures are synthetic. No customer workbook is read.
"""

from __future__ import annotations

import hashlib
import io
import json
import struct
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from openpyxl import Workbook

from app.core.database import SessionLocal
from app.core.job_errors import BAD_INPUT, classify, is_retryable_code
from app.models import Job, Question, Questionnaire
from app.services.xlsx_parser import WorkbookUnreadable
from app.services.xlsx_questionnaire_parser import parse_xlsx_questionnaire
from app.services.xlsx_writer import (
    UnsupportedWorkbookStructure,
    create_export_from_questionnaire,
    reject_unsupported_workbook,
    unsupported_workbook_features,
)
from tests.release.test_export_fidelity import (
    _assert_same_view,
    _assert_supported_content,
    build_supported_workbook,
    package_view,
)

_OLE_END = 0xFFFFFFFE
_OLE_FREE = 0xFFFFFFFF
_OLE_FAT = 0xFFFFFFFD
_SECTOR = 512


def _plain_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Security"
    ws["A1"] = "Question"
    ws["A2"] = "Do you encrypt data at rest?"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _macro_package() -> bytes:
    """OOXML workbook with a VBA part and the macro-enabled content type."""
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(_plain_xlsx())) as zf:
        for name in zf.namelist():
            files[name] = zf.read(name)
    files["xl/vbaProject.bin"] = b"synthetic-vba-project"
    content = files["[Content_Types].xml"].decode("utf-8")
    # Workbook part type used by a macro-enabled workbook. openpyxl still opens it.
    workbook_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
    content = content.replace(
        workbook_type,
        "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
        1,
    )
    override = (
        '<Override PartName="/xl/vbaProject.bin" '
        'ContentType="application/vnd.ms-office.vbaProject"/>'
    )
    content = content.replace("</Types>", override + "</Types>", 1)
    files["[Content_Types].xml"] = content.encode("utf-8")
    assert b"macroEnabled" in files["[Content_Types].xml"]
    assert b"vbaProject" in files["[Content_Types].xml"]
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, blob in files.items():
            zf.writestr(name, blob)
    payload = out.getvalue()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        assert "xl/vbaProject.bin" in zf.namelist()
        assert b"macroEnabled" in zf.read("[Content_Types].xml")
    return payload


def _dir_entry(name: str, kind: int, start: int, size: int, child: int = _OLE_FREE) -> bytes:
    encoded = name.encode("utf-16le")
    entry = bytearray(_SECTOR // 4)
    entry[: len(encoded)] = encoded
    struct.pack_into("<H", entry, 64, len(encoded) + 2)
    entry[66] = kind
    struct.pack_into("<I", entry, 68, _OLE_FREE)
    struct.pack_into("<I", entry, 72, _OLE_FREE)
    struct.pack_into("<I", entry, 76, child)
    struct.pack_into("<I", entry, 116, start)
    struct.pack_into("<Q", entry, 120, size)
    return bytes(entry)


def _ole_file(streams: list[tuple[str, bytes]]) -> bytes:
    """Minimal OLE compound file. Each stream payload fits in one sector."""
    data_sectors: list[bytes] = []
    placed: list[tuple[str, int, int]] = []
    for name, payload in streams:
        if len(payload) > _SECTOR:
            raise ValueError("synthetic stream must fit in one sector")
        start = 2 + len(data_sectors)
        data_sectors.append(payload + b"\x00" * (_SECTOR - len(payload)))
        placed.append((name, start, len(payload)))
    directory = bytearray(_SECTOR)
    directory[:128] = _dir_entry("Root Entry", 5, _OLE_END, 0, child=1 if placed else _OLE_FREE)
    for index, (name, start, size) in enumerate(placed):
        directory[(index + 1) * 128 : (index + 2) * 128] = _dir_entry(name, 2, start, size)
    fat = bytearray(_SECTOR)
    struct.pack_into("<I", fat, 0, _OLE_FAT)
    struct.pack_into("<I", fat, 4, _OLE_END)
    for index in range(len(data_sectors)):
        struct.pack_into("<I", fat, (2 + index) * 4, _OLE_END)
    for index in range(2 + len(data_sectors), _SECTOR // 4):
        struct.pack_into("<I", fat, index * 4, _OLE_FREE)
    header = bytearray(_SECTOR)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<H", header, 0x18, 0x003E)
    struct.pack_into("<H", header, 0x1A, 0x0003)
    struct.pack_into("<H", header, 0x1C, 0xFFFE)
    struct.pack_into("<H", header, 0x1E, 9)
    struct.pack_into("<H", header, 0x20, 6)
    struct.pack_into("<I", header, 0x2C, 1)
    struct.pack_into("<I", header, 0x30, 1)
    struct.pack_into("<I", header, 0x38, 4096)
    struct.pack_into("<I", header, 0x3C, _OLE_END)
    struct.pack_into("<I", header, 0x44, _OLE_END)
    struct.pack_into("<I", header, 0x4C, 0)
    for index in range(1, 109):
        struct.pack_into("<I", header, 0x4C + 4 * index, _OLE_FREE)
    return bytes(header) + bytes(fat) + bytes(directory) + b"".join(data_sectors)


def _encrypted_workbook() -> bytes:
    """ECMA-376 encrypted package: OLE streams, not a zip."""
    return _ole_file(
        [
            ("EncryptionInfo", b"\x04\x00\x04\x00synthetic-encryption-info"),
            ("EncryptedPackage", b"synthetic-encrypted-package"),
        ]
    )


def _legacy_xls() -> bytes:
    """BIFF Workbook stream. Not an OOXML zip and not readable by openpyxl."""
    bof = struct.pack("<HH", 0x0809, 16) + struct.pack(
        "<HHHHHH", 0x0600, 0x0005, 0x0DBB, 0x07CC, 0, 6
    )
    eof = struct.pack("<HH", 0x000A, 0)
    return _ole_file([("Workbook", bof + eof)])


def _inventory() -> tuple[int, int, int]:
    session = SessionLocal()
    try:
        return (
            session.query(Questionnaire).count(),
            session.query(Question).count(),
            session.query(Job).count(),
        )
    finally:
        session.close()


def _questions_for_digest(digest: str) -> int:
    session = SessionLocal()
    try:
        return session.query(Question).filter(Question.original_file_hash == digest).count()
    finally:
        session.close()


def _questionnaires_named(filename: str) -> int:
    session = SessionLocal()
    try:
        return session.query(Questionnaire).filter(Questionnaire.filename == filename).count()
    finally:
        session.close()


def _upload(client, filename: str, blob: bytes, *, workspace_id: str = "1"):
    stored: dict[tuple[str, str], bytes] = {}

    def fake_upload(bucket: str, key: str, body, **kwargs) -> str:
        stored[(bucket, key)] = body.read() if hasattr(body, "read") else bytes(body)
        return key

    with patch("app.services.storage.StorageClient.upload", side_effect=fake_upload):
        response = client.post(
            "/api/questionnaires/upload",
            data={"workspace_id": workspace_id},
            files={"file": (filename, blob, "application/octet-stream")},
        )
    return response, stored


def _login(client) -> None:
    response = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert response.status_code == 200


def _assert_same_rejection(blob: bytes, detail: str, feature: str) -> None:
    with pytest.raises(UnsupportedWorkbookStructure) as parsed:
        reject_unsupported_workbook(blob)
    with pytest.raises(UnsupportedWorkbookStructure) as exported:
        create_export_from_questionnaire(blob, [], {})
    assert parsed.value.features == (feature,)
    assert exported.value.features == (feature,)
    assert str(parsed.value) == detail
    assert str(exported.value) == detail
    assert feature in detail
    assert "<" not in detail
    assert "xl/" not in detail
    assert len(detail) <= 500
    assert classify(parsed.value) == BAD_INPUT
    assert is_retryable_code(BAD_INPUT) is False


@pytest.mark.parametrize(
    "filename,feature,build",
    [
        ("questionnaire.xlsm", "macros", _macro_package),
        ("questionnaire.xlsx", "macros", _macro_package),
        ("locked.xlsx", "encryption", _encrypted_workbook),
        ("legacy.xls", "legacy .xls", _legacy_xls),
    ],
    ids=["xlsm", "macro-xlsx", "encrypted", "legacy-xls"],
)
def test_rejected_upload_stores_nothing(client, filename: str, feature: str, build) -> None:
    _login(client)
    filename = f"{uuid.uuid4().hex}-{filename}"
    blob = build()
    digest = hashlib.sha256(blob).hexdigest()
    before = _inventory()
    response, stored = _upload(client, filename, blob)
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    _assert_same_rejection(blob, detail, feature)
    assert stored == {}
    assert _inventory() == before
    assert _questionnaires_named(filename) == 0
    assert _questions_for_digest(digest) == 0


@pytest.mark.parametrize(
    "filename,feature,build",
    [
        ("parse-macro.xlsm", "macros", _macro_package),
        ("parse-locked.xlsx", "encryption", _encrypted_workbook),
        ("parse-legacy.xls", "legacy .xls", _legacy_xls),
    ],
    ids=["macros", "encrypted", "legacy-xls"],
)
def test_parse_rejects_before_questions(tmp_path: Path, filename: str, feature: str, build) -> None:
    blob = build()
    path = tmp_path / filename
    path.write_bytes(blob)
    with pytest.raises(UnsupportedWorkbookStructure) as caught:
        parse_xlsx_questionnaire(path)
    assert caught.value.features == (feature,)
    with pytest.raises(UnsupportedWorkbookStructure) as exported:
        reject_unsupported_workbook(blob)
    assert str(caught.value) == str(exported.value)


def test_worker_does_not_store_questions_for_a_macro_workbook(monkeypatch, tmp_path: Path) -> None:
    from app import worker

    blob = _macro_package()
    path = tmp_path / "worker-macro.xlsx"
    path.write_bytes(blob)
    questionnaire = SimpleNamespace(
        id=11,
        workspace_id=1,
        filename="worker-macro.xlsx",
        storage_key="raw/1/worker-macro.xlsx",
        status="uploaded",
        parse_metadata=None,
        deleted_at=None,
    )
    job = SimpleNamespace(id=12, workspace_id=1, attempt=1, result=None)
    added: list = []

    class _Query:
        def filter(self, *_args, **_kwargs):
            return self

        def populate_existing(self):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return questionnaire

        def count(self) -> int:
            return 0

    class _Session:
        def query(self, _model):
            return _Query()

        def add(self, obj) -> None:
            added.append(obj)

        def rollback(self) -> None:
            return None

    class _Store:
        bucket_raw = "raw"

        def download(self, _bucket: str, _key: str) -> bytes:
            return blob

    class _Effects:
        def __init__(self, _session, _job) -> None:
            return None

        def is_applied(self, _effect: str) -> bool:
            return False

    monkeypatch.setattr(worker, "StorageClient", lambda: _Store())
    monkeypatch.setattr(worker, "JobEffects", _Effects)
    with pytest.raises(UnsupportedWorkbookStructure) as caught:
        worker.run_parse_questionnaire(
            job,
            _Session(),
            {"questionnaire_id": 11, "storage_key": "raw/1/worker-macro.xlsx"},
        )
    assert caught.value.features == ("macros",)
    assert added == []
    assert questionnaire.status == "uploaded"
    assert worker.apply_questionnaire_parse_failure(questionnaire, caught.value) is True
    assert questionnaire.status == "failed"
    assert json.loads(questionnaire.parse_metadata) == {"count": 0, "error": str(caught.value)}


def test_unrelated_compound_file_is_not_rejected() -> None:
    blob = _ole_file([("WordDocument", b"synthetic-word")])
    assert unsupported_workbook_features(blob) == []


def test_corrupt_xlsx_stays_unreadable(tmp_path: Path) -> None:
    payload = b"this is not a workbook"
    path = tmp_path / "broken.xlsx"
    path.write_bytes(payload)
    assert unsupported_workbook_features(payload) == []
    with pytest.raises(WorkbookUnreadable, match="corrupt or unreadable"):
        parse_xlsx_questionnaire(path)


def test_other_workspace_cannot_upload(client) -> None:
    _login(client)
    blob = _plain_xlsx()
    before = _inventory()
    response, stored = _upload(client, "other-workspace.xlsx", blob, workspace_id="999999")
    assert response.status_code == 403
    assert stored == {}
    assert _inventory() == before
    assert _questionnaires_named("other-workspace.xlsx") == 0


def test_supported_xlsx_is_stored_and_export_keeps_structure(client, tmp_path: Path) -> None:
    from app.worker import run_parse_questionnaire

    _login(client)
    payload = build_supported_workbook(tmp_path / "supported")
    assert unsupported_workbook_features(payload) == []
    stored: dict[tuple[str, str], bytes] = {}

    def fake_upload(bucket: str, key: str, body, **kwargs) -> str:
        stored[(bucket, key)] = body.read() if hasattr(body, "read") else bytes(body)
        return key

    def fake_download(bucket: str, key: str) -> bytes:
        return stored[(bucket, key)]

    with (
        patch("app.services.storage.StorageClient.upload", side_effect=fake_upload),
        patch("app.services.storage.StorageClient.download", side_effect=fake_download),
    ):
        uploaded = client.post(
            "/api/questionnaires/upload",
            data={"workspace_id": "1"},
            files={"file": ("supported.xlsx", payload, "application/octet-stream")},
        )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert stored
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == body["job_id"]).one()
        with patch("app.services.storage.StorageClient.download", side_effect=fake_download):
            run_parse_questionnaire(job, session, json.loads(job.payload))
        session.commit()
        questions = session.query(Question).filter(Question.questionnaire_id == body["id"]).all()
        assert questions
        assert any("encrypt" in (question.text or "").lower() for question in questions)
    finally:
        session.close()
    exported = create_export_from_questionnaire(
        payload,
        [{"id": 1, "source_location": json.dumps({"sheet": "Security", "row": 2, "col": 1})}],
        {1: "Approved"},
    )
    before = package_view(payload)
    after = package_view(exported)
    _assert_supported_content(before, very_hidden=True)
    _assert_same_view(before, after)
