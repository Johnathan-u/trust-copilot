"""Per-question content hash, source cell and explicit answer-cell mapping.

The product contract stores, on each question, the original file hash, the
question's own content hash, the sheet (or the format's own locator), the
question cell, the answer cell and the mapping ruleset version. The answer
cell is an explicit target. A global column offset is not used, so an owner
column between the question and the answer stays untouched.
"""

import csv
import hashlib
import json
import os
import subprocess
import sys
import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import openpyxl
import pytest
from docx import Document
from sqlalchemy import text

from app.services.docx_questionnaire_parser import parse_docx_questionnaire
from app.services.pdf_questionnaire_parser import parse_pdf_questionnaire
from app.services.question_normalizer import normalize_question
from app.services.synthetic_pdf import Page, build_pdf, text_block
from app.services.xlsx_parser import WorkbookUnreadable
from app.services.xlsx_questionnaire_parser import parse_xlsx_questionnaire

API_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = API_ROOT / "tests" / "fixtures" / "questionnaires"
MIGRATION = API_ROOT / "alembic" / "versions" / "question_cell_mapping.py"
ROUNDTRIP_DB = "cellmap_roundtrip_test"

Q_ENCRYPT = "Does the company encrypt data at rest?"
Q_ACCESS = "Is access reviewed at least quarterly?"
Q_OWNER_LOOKALIKE = "Does the owner review access every quarter?"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content_hash(text: str) -> str:
    return _sha256(normalize_question(text).encode("utf-8"))


def _column_index(cell: str) -> int:
    letters = "".join(ch for ch in cell if ch.isalpha())
    number = 0
    for ch in letters:
        number = number * 26 + (ord(ch.upper()) - 64)
    return number


def _write_grid(path: Path, sheets: dict[str, list[list]]) -> None:
    wb = openpyxl.Workbook()
    first = True
    for name, rows in sheets.items():
        ws = wb.active if first else wb.create_sheet(name)
        first = False
        ws.title = name
        for row in rows:
            ws.append(row)
    wb.save(path)


def _owner_answer_grid() -> list[list]:
    return [
        ["ID", "Question", "Owner", "Answer"],
        ["1", Q_ENCRYPT, "Alice", None],
        ["2", Q_ACCESS, "Bob", None],
        ["3", None, Q_OWNER_LOOKALIKE, None],
    ]


def _layout_workbook(path: Path) -> None:
    _write_grid(
        path,
        {
            "Security": _owner_answer_grid(),
            "Privacy": [
                ["ID", "Question", "Owner", "Answer"],
                ["9", Q_ENCRYPT, "Cara", "existing"],
            ],
            "Notes": [
                ["leave-a", "leave-b", "leave-c", "leave-d"],
            ],
        },
    )


def _csv_file(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(_owner_answer_grid())


def _loc(question: dict) -> dict:
    raw = question["source_location"]
    return json.loads(raw) if isinstance(raw, str) else raw


def _by_text(questions: list[dict], needle: str, sheet: str | None = "") -> dict:
    wanted = normalize_question(needle)
    matches = [q for q in questions if q["text"] == wanted]
    if sheet != "":
        matches = [q for q in matches if q.get("sheet") == sheet]
    assert len(matches) == 1, [q["text"] for q in questions]
    return matches[0]


def test_identical_file_keeps_hashes_and_text_change_updates_them(tmp_path: Path) -> None:
    original = tmp_path / "original.xlsx"
    copy = tmp_path / "copy.xlsx"
    changed = tmp_path / "changed.xlsx"
    _layout_workbook(original)
    copy.write_bytes(original.read_bytes())
    _layout_workbook(changed)
    wb = openpyxl.load_workbook(changed)
    wb["Security"]["B2"] = "Does the company encrypt data in transit?"
    wb.save(changed)

    first = parse_xlsx_questionnaire(original)
    second = parse_xlsx_questionnaire(copy)
    edited = parse_xlsx_questionnaire(changed)
    encrypt = _by_text(first, Q_ENCRYPT, "Security")
    encrypt_copy = _by_text(second, Q_ENCRYPT, "Security")
    access = _by_text(first, Q_ACCESS, "Security")
    access_edited = _by_text(edited, Q_ACCESS, "Security")
    moved = _by_text(edited, "Does the company encrypt data in transit?", "Security")

    assert encrypt["content_hash"] == _content_hash(Q_ENCRYPT)
    assert encrypt["content_hash"] == encrypt_copy["content_hash"]
    assert encrypt["original_file_hash"] == _sha256(original.read_bytes())
    assert encrypt["original_file_hash"] == encrypt_copy["original_file_hash"]
    assert encrypt["content_hash"] != access["content_hash"]
    assert access["content_hash"] == access_edited["content_hash"]
    assert moved["content_hash"] == _content_hash("Does the company encrypt data in transit?")
    assert moved["content_hash"] != encrypt["content_hash"]
    assert moved["original_file_hash"] == _sha256(changed.read_bytes())
    assert moved["original_file_hash"] != encrypt["original_file_hash"]


def test_explicit_answer_column_targets_d_and_leaves_owner_column(tmp_path: Path) -> None:
    path = tmp_path / "layout.xlsx"
    _layout_workbook(path)
    questions = parse_xlsx_questionnaire(path)
    security = [q for q in questions if q["sheet"] == "Security"]
    privacy = [q for q in questions if q["sheet"] == "Privacy"]
    assert [q["text"] for q in security] == [
        normalize_question(Q_ENCRYPT),
        normalize_question(Q_ACCESS),
    ]
    assert normalize_question(Q_OWNER_LOOKALIKE) not in {q["text"] for q in questions}

    encrypt = security[0]
    access = security[1]
    private = privacy[0]
    for question, cell, row in (
        (encrypt, "B2", 2),
        (access, "B3", 3),
        (private, "B2", 2),
    ):
        assert question["question_cell"] == cell
        assert question["answer_cell"].startswith("D")
        assert _column_index(question["answer_cell"]) == 4
        assert _loc(question)["row"] == row
        assert _loc(question)["col"] == 2
        assert question["mapping_version"] == 1
        assert question["sheet"] in {"Security", "Privacy"}

    assert encrypt["answer_cell"] == "D2"
    assert access["answer_cell"] == "D3"
    assert private["answer_cell"] == "D2"
    assert private["sheet"] == "Privacy"
    assert "Notes" not in {q["sheet"] for q in questions}

    wb = openpyxl.load_workbook(path)
    for question in (encrypt, access, private):
        wb[question["sheet"]][question["answer_cell"]] = "Approved"
    saved = tmp_path / "written.xlsx"
    wb.save(saved)
    out = openpyxl.load_workbook(saved)
    assert out["Security"]["C2"].value == "Alice"
    assert out["Security"]["C3"].value == "Bob"
    assert out["Security"]["D2"].value == "Approved"
    assert out["Security"]["D3"].value == "Approved"
    assert out["Privacy"]["C2"].value == "Cara"
    assert out["Privacy"]["D2"].value == "Approved"
    assert out["Notes"]["C1"].value == "leave-c"
    assert out["Notes"]["D1"].value == "leave-d"


def test_answer_header_without_question_header_still_names_the_answer_column() -> None:
    questions = parse_xlsx_questionnaire(FIXTURES / "simple_soc2.xlsx")
    first = questions[0]
    assert _loc(first)["sheet"] == "CC1"
    assert _loc(first)["row"] == 2
    assert _loc(first)["col"] == 1
    assert first["sheet"] == "CC1"
    assert first["question_cell"] == "A2"
    assert first["answer_cell"] == "B2"
    assert first["mapping_version"] == 1
    assert first["content_hash"] == _content_hash(first["text"])
    assert first["original_file_hash"] == _sha256((FIXTURES / "simple_soc2.xlsx").read_bytes())


def test_missing_answer_header_does_not_use_the_next_column(tmp_path: Path) -> None:
    path = tmp_path / "no-header.xlsx"
    _write_grid(
        path,
        {"Sheet1": [["ID", Q_ENCRYPT, "Alice"], ["ID", Q_ACCESS, "Bob"]]},
    )
    questions = parse_xlsx_questionnaire(path)
    assert len(questions) == 2
    assert questions[0]["question_cell"] == "B1"
    assert questions[0]["answer_cell"] is None
    assert questions[0]["mapping_version"] == 1
    assert _column_index(questions[0]["question_cell"]) == 2


def test_csv_uses_the_same_explicit_cells_without_a_sheet(tmp_path: Path) -> None:
    path = tmp_path / "layout.csv"
    _csv_file(path)
    from app.services.csv_questionnaire_parser import parse_csv_questionnaire

    first = parse_csv_questionnaire(path)
    second = parse_csv_questionnaire(path)
    encrypt = _by_text(first, Q_ENCRYPT)
    assert encrypt["sheet"] is None
    assert encrypt["question_cell"] == "B2"
    assert encrypt["answer_cell"] == "D2"
    assert _loc(encrypt)["type"] == "csv"
    assert _loc(encrypt)["row"] == 2
    assert _loc(encrypt)["col"] == 2
    assert "sheet" not in _loc(encrypt) or _loc(encrypt).get("sheet") in {None, ""}
    assert encrypt["mapping_version"] == 1
    assert encrypt["content_hash"] == _content_hash(Q_ENCRYPT)
    assert encrypt["content_hash"] == _by_text(second, Q_ENCRYPT)["content_hash"]
    assert encrypt["original_file_hash"] == _sha256(path.read_bytes())
    assert normalize_question(Q_OWNER_LOOKALIKE) not in {q["text"] for q in first}

    grid = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    for question in first:
        row = int("".join(ch for ch in question["answer_cell"] if ch.isdigit())) - 1
        col = _column_index(question["answer_cell"]) - 1
        grid[row][col] = "Approved"
    assert grid[1][2] == "Alice"
    assert grid[2][2] == "Bob"
    assert grid[1][3] == "Approved"


def test_empty_workbook_has_no_questions_and_unreadable_fails(tmp_path: Path) -> None:
    empty_xlsx = tmp_path / "empty.xlsx"
    _write_grid(empty_xlsx, {"Sheet1": []})
    assert parse_xlsx_questionnaire(empty_xlsx) == []
    garbage = tmp_path / "garbage.xlsx"
    garbage.write_bytes(b"this is not a workbook")
    with pytest.raises(WorkbookUnreadable, match="corrupt or unreadable"):
        parse_xlsx_questionnaire(garbage)
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text("", encoding="utf-8")
    from app.services.csv_questionnaire_parser import parse_csv_questionnaire

    assert parse_csv_questionnaire(empty_csv) == []


def test_docx_paragraphs_have_no_answer_cell_and_tables_target_the_answer_column(
    tmp_path: Path,
) -> None:
    paragraphs = parse_docx_questionnaire(FIXTURES / "simple_soc2.docx")
    assert paragraphs
    first = paragraphs[0]
    assert first["sheet"] is None
    assert first["answer_cell"] is None
    assert first["question_cell"].startswith("paragraph:")
    assert first["mapping_version"] == 1
    assert first["content_hash"] == _content_hash(first["text"])
    assert first["original_file_hash"] == _sha256((FIXTURES / "simple_soc2.docx").read_bytes())
    assert _loc(first)["type"] == "paragraph"

    path = tmp_path / "table.docx"
    doc = Document()
    table = doc.add_table(rows=2, cols=4)
    for idx, label in enumerate(["ID", "Question", "Owner", "Answer"]):
        table.rows[0].cells[idx].text = label
    table.rows[1].cells[0].text = "1"
    table.rows[1].cells[1].text = Q_ENCRYPT
    table.rows[1].cells[2].text = "Alice"
    table.rows[1].cells[3].text = ""
    doc.save(path)
    questions = parse_docx_questionnaire(path)
    question = _by_text(questions, Q_ENCRYPT)
    assert question["sheet"] is None
    assert question["question_cell"] == "T1R2C2"
    assert question["answer_cell"] == "T1R2C4"
    assert question["answer_cell"] != "T1R2C3"
    assert _loc(question)["type"] == "table"
    assert _loc(question)["col"] == 2
    assert question["mapping_version"] == 1


def test_pdf_provenance_keeps_the_page_and_has_no_workbook_answer_cell(tmp_path: Path) -> None:
    path = tmp_path / "questions.pdf"
    path.write_bytes(
        build_pdf([Page(texts=text_block(72, 90, ["1.0 CONTROL ENVIRONMENT", Q_ENCRYPT]))])
    )
    raw = parse_pdf_questionnaire(path)
    assert raw
    assert "answer_cell" not in raw[0]
    assert _loc(raw[0])["type"] == "pdf"
    assert _loc(raw[0])["page"] == 1

    from app.services.cell_mapping import annotate_question_provenance

    annotated = annotate_question_provenance(raw, path.read_bytes(), kind="pdf")
    question = annotated[0]
    assert question["sheet"] is None
    assert question["question_cell"] == "page:1"
    assert question["answer_cell"] is None
    assert question["mapping_version"] == 1
    assert question["content_hash"] == _content_hash(question["text"])
    assert question["original_file_hash"] == _sha256(path.read_bytes())
    assert _loc(question)["type"] == "pdf"


def test_ruleset_version_is_newer_than_the_legacy_default() -> None:
    from app.services.cell_mapping import CELL_MAPPING_VERSION

    assert CELL_MAPPING_VERSION == 1


def _database_url(name: str) -> str:
    base = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/trustcopilot_test"
    )
    return base.rsplit("/", 1)[0] + "/" + name


def _admin_engine():
    from sqlalchemy import create_engine

    engine = create_engine(_database_url("postgres"), isolation_level="AUTOCOMMIT")
    return engine


def _recreate_roundtrip_db() -> None:
    engine = _admin_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": ROUNDTRIP_DB},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{ROUNDTRIP_DB}"'))
        conn.execute(text(f'CREATE DATABASE "{ROUNDTRIP_DB}"'))
    engine.dispose()


def _alembic(url: str, *args: str) -> str:
    env = {**os.environ, "DATABASE_URL": url, "TRUST_COPILOT_TESTING": "1"}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr[-2000:] + proc.stdout[-2000:]
    return proc.stdout


@pytest.fixture
def roundtrip_db():
    _recreate_roundtrip_db()
    url = _database_url(ROUNDTRIP_DB)
    _alembic(url, "upgrade", "head")
    yield url
    from sqlalchemy import create_engine

    create_engine(url).dispose()


def test_migration_backfills_legacy_rows_and_round_trips(roundtrip_db: str) -> None:
    assert MIGRATION.is_file()
    source = MIGRATION.read_text(encoding="utf-8")
    assert "import app" not in source
    assert "app." not in source
    spec_name = "question_cell_mapping_revision"
    import importlib.util

    spec = importlib.util.spec_from_file_location(spec_name, MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "question_cell_mapping"
    parent = module.down_revision
    url = roundtrip_db
    _alembic(url, "downgrade", parent)

    from sqlalchemy import create_engine

    engine = create_engine(url)
    slug = "cellmap-" + uuid.uuid4().hex[:8]
    location = json.dumps({"sheet": "Security", "row": 4, "col": 2})
    broken = "not-json"
    with engine.begin() as conn:
        for table in ("workspaces", "questionnaires", "questions"):
            conn.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('"
                    + table
                    + "', 'id'), (SELECT COALESCE(MAX(id), 1) FROM "
                    + table
                    + "))"
                )
            )
        workspace_id = conn.execute(
            text(
                "INSERT INTO workspaces (name, slug, mfa_required, ai_automate_everything) "
                "VALUES ('Cell map', :slug, false, false) RETURNING id"
            ),
            {"slug": slug},
        ).scalar_one()
        questionnaire_id = conn.execute(
            text(
                "INSERT INTO questionnaires (workspace_id, filename, status) "
                "VALUES (:ws, 'legacy.xlsx', 'parsed') RETURNING id"
            ),
            {"ws": workspace_id},
        ).scalar_one()
        question_id = conn.execute(
            text(
                "INSERT INTO questions (questionnaire_id, text, source_location) "
                "VALUES (:qid, :text, :loc) RETURNING id"
            ),
            {
                "qid": questionnaire_id,
                "text": Q_ENCRYPT,
                "loc": location,
            },
        ).scalar_one()
        broken_id = conn.execute(
            text(
                "INSERT INTO questions (questionnaire_id, text, source_location) "
                "VALUES (:qid, :text, :loc) RETURNING id"
            ),
            {"qid": questionnaire_id, "text": Q_ACCESS, "loc": broken},
        ).scalar_one()
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'questions'"
                )
            )
        }
        assert "answer_cell" not in columns

    _alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT content_hash, original_file_hash, sheet, question_cell, "
                "answer_cell, mapping_version, text, source_location "
                "FROM questions WHERE id = :id"
            ),
            {"id": question_id},
        ).one()
        assert row.content_hash == _sha256(Q_ENCRYPT.encode("utf-8"))
        assert row.original_file_hash is None
        assert row.sheet == "Security"
        assert row.question_cell == "B4"
        assert row.answer_cell is None
        assert row.mapping_version == 0
        assert row.text == Q_ENCRYPT
        assert row.source_location == location
        broken_row = conn.execute(
            text(
                "SELECT content_hash, sheet, question_cell, answer_cell, mapping_version "
                "FROM questions WHERE id = :id"
            ),
            {"id": broken_id},
        ).one()
        assert broken_row.content_hash == _sha256(Q_ACCESS.encode("utf-8"))
        assert broken_row.sheet is None
        assert broken_row.question_cell is None
        assert broken_row.answer_cell is None
        assert broken_row.mapping_version == 0

        conn.execute(
            text(
                "UPDATE questions SET answer_cell = 'D4', original_file_hash = :file_hash, "
                "mapping_version = 1, content_hash = :content_hash WHERE id = :id"
            ),
            {
                "id": question_id,
                "file_hash": "ab" * 32,
                "content_hash": "cd" * 32,
            },
        )

    _alembic(url, "downgrade", parent)
    with engine.begin() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'questions'"
                )
            )
        }
        assert "content_hash" not in columns
        assert "answer_cell" not in columns
        assert "mapping_version" not in columns
        kept = conn.execute(
            text("SELECT text, source_location FROM questions WHERE id = :id"),
            {"id": question_id},
        ).one()
        assert kept.text == Q_ENCRYPT
        assert kept.source_location == location
        parked = conn.execute(
            text(
                "SELECT answer_cell, original_file_hash, mapping_version, content_hash "
                "FROM question_cell_mapping_hold WHERE question_id = :id"
            ),
            {"id": question_id},
        ).one()
        assert parked.answer_cell == "D4"
        assert parked.original_file_hash == "ab" * 32
        assert parked.mapping_version == 1
        assert parked.content_hash == "cd" * 32

    _alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        restored = conn.execute(
            text(
                "SELECT answer_cell, original_file_hash, mapping_version, content_hash, "
                "sheet, question_cell FROM questions WHERE id = :id"
            ),
            {"id": question_id},
        ).one()
        assert restored.answer_cell == "D4"
        assert restored.original_file_hash == "ab" * 32
        assert restored.mapping_version == 1
        assert restored.content_hash == "cd" * 32
        assert restored.sheet == "Security"
        assert restored.question_cell == "B4"
        hold_left = conn.execute(
            text("SELECT count(*) FROM question_cell_mapping_hold WHERE question_id = :id"),
            {"id": question_id},
        ).scalar_one()
        assert hold_left == 0
    engine.dispose()


def test_parsed_questions_keep_mapping_on_the_questionnaire(client) -> None:
    from app.core.database import SessionLocal
    from app.models import Job
    from app.worker import run_parse_questionnaire

    login = client.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    assert login.status_code == 200
    workbook = BytesIO()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Security"
    for row in _owner_answer_grid():
        ws.append(row)
    wb.save(workbook)
    payload = workbook.getvalue()
    stored: dict[tuple[str, str], bytes] = {}

    def fake_upload(bucket: str, key: str, body, **kwargs) -> str:
        stored[(bucket, key)] = body.read() if hasattr(body, "read") else body
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
            files={
                "file": (
                    "layout.xlsx",
                    payload,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    session = SessionLocal()
    try:
        job = session.query(Job).filter(Job.id == body["job_id"]).first()
        with patch("app.services.storage.StorageClient.download", side_effect=fake_download):
            run_parse_questionnaire(job, session, json.loads(job.payload))
        session.commit()
    finally:
        session.close()

    fetched = client.get(f"/api/questionnaires/{body['id']}?workspace_id=1")
    assert fetched.status_code == 200, fetched.text
    questions = fetched.json()["questions"]
    encrypt = _by_text(questions, Q_ENCRYPT)
    assert encrypt["sheet"] == "Security"
    assert encrypt["question_cell"] == "B2"
    assert encrypt["answer_cell"] == "D2"
    assert encrypt["mapping_version"] == 1
    assert encrypt["content_hash"] == _content_hash(Q_ENCRYPT)
    assert encrypt["original_file_hash"] == _sha256(payload)
    denied = client.get(f"/api/questionnaires/{body['id']}?workspace_id=999999")
    assert denied.status_code == 403
