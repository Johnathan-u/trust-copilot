"""Per-question content hash, file hash, cells and mapping version.

Adds nullable provenance columns on questions and a non-null mapping_version
that defaults to 0. Existing rows are backfilled from the text and
source_location already stored: the content hash is the SHA-256 of that text,
the sheet and question cell are read from a JSON locator when it parses, and
the answer cell and file hash stay null. Version 0 means the row was saved
before an explicit answer cell was chosen. Nothing here invents an answer
column.

Downgrade copies the new values into question_cell_mapping_hold before
dropping the columns. Upgrade restores held values for questions that still
exist, then backfills only rows that still have no content hash. Held rows
whose question is gone stay in the hold table.

This revision does not import the application package.

Revision ID: question_cell_mapping
Revises: tc17003_security_claims
"""

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "question_cell_mapping"
down_revision = "tc17003_security_claims"
branch_labels = None
depends_on = None

HOLD = "question_cell_mapping_hold"
CHECK = "ck_questions_mapping_version_nonneg"


def upgrade() -> None:
    op.add_column("questions", sa.Column("content_hash", sa.String(64), nullable=True))
    op.add_column("questions", sa.Column("original_file_hash", sa.String(64), nullable=True))
    op.add_column("questions", sa.Column("sheet", sa.String(255), nullable=True))
    op.add_column("questions", sa.Column("question_cell", sa.String(64), nullable=True))
    op.add_column("questions", sa.Column("answer_cell", sa.String(64), nullable=True))
    op.add_column(
        "questions",
        sa.Column("mapping_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(CHECK, "questions", "mapping_version >= 0")
    bind = op.get_bind()
    _restore_hold(bind)
    _backfill(bind)


def downgrade() -> None:
    bind = op.get_bind()
    _park(bind)
    op.drop_constraint(CHECK, "questions", type_="check")
    op.drop_column("questions", "mapping_version")
    op.drop_column("questions", "answer_cell")
    op.drop_column("questions", "question_cell")
    op.drop_column("questions", "sheet")
    op.drop_column("questions", "original_file_hash")
    op.drop_column("questions", "content_hash")


def _table_exists(bind, name: str) -> bool:
    return (
        bind.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :name"),
            {"name": name},
        ).scalar()
        is not None
    )


def _park(bind) -> None:
    if not _table_exists(bind, HOLD):
        op.create_table(
            HOLD,
            sa.Column("question_id", sa.Integer(), primary_key=True),
            sa.Column("content_hash", sa.String(64), nullable=True),
            sa.Column("original_file_hash", sa.String(64), nullable=True),
            sa.Column("sheet", sa.String(255), nullable=True),
            sa.Column("question_cell", sa.String(64), nullable=True),
            sa.Column("answer_cell", sa.String(64), nullable=True),
            sa.Column("mapping_version", sa.Integer(), nullable=True),
        )
    else:
        bind.execute(sa.text(f"DELETE FROM {HOLD}"))
    bind.execute(
        sa.text(
            f"INSERT INTO {HOLD} ("
            "question_id, content_hash, original_file_hash, sheet, "
            "question_cell, answer_cell, mapping_version"
            ") SELECT id, content_hash, original_file_hash, sheet, "
            "question_cell, answer_cell, mapping_version FROM questions"
        )
    )


def _restore_hold(bind) -> None:
    if not _table_exists(bind, HOLD):
        return
    rows = bind.execute(
        sa.text(
            "SELECT question_id, content_hash, original_file_hash, sheet, "
            "question_cell, answer_cell, mapping_version FROM " + HOLD
        )
    ).fetchall()
    for row in rows:
        updated = bind.execute(
            sa.text(
                "UPDATE questions SET content_hash = :content_hash, "
                "original_file_hash = :original_file_hash, sheet = :sheet, "
                "question_cell = :question_cell, answer_cell = :answer_cell, "
                "mapping_version = :mapping_version WHERE id = :question_id"
            ),
            {
                "question_id": row.question_id,
                "content_hash": row.content_hash,
                "original_file_hash": row.original_file_hash,
                "sheet": row.sheet,
                "question_cell": row.question_cell,
                "answer_cell": row.answer_cell,
                "mapping_version": row.mapping_version if row.mapping_version is not None else 0,
            },
        ).rowcount
        if updated:
            bind.execute(
                sa.text(f"DELETE FROM {HOLD} WHERE question_id = :question_id"),
                {"question_id": row.question_id},
            )


def _backfill(bind) -> None:
    rows = bind.execute(
        sa.text("SELECT id, text, source_location FROM questions WHERE content_hash IS NULL")
    ).fetchall()
    for row in rows:
        sheet, question_cell = _locator(row.source_location)
        digest = None
        if row.text:
            digest = hashlib.sha256(row.text.encode("utf-8")).hexdigest()
        bind.execute(
            sa.text(
                "UPDATE questions SET content_hash = :content_hash, "
                "sheet = COALESCE(sheet, :sheet), "
                "question_cell = COALESCE(question_cell, :question_cell) "
                "WHERE id = :id AND content_hash IS NULL"
            ),
            {
                "id": row.id,
                "content_hash": digest,
                "sheet": sheet,
                "question_cell": question_cell,
            },
        )


def _letters(index: int) -> str:
    letters: list[str] = []
    number = index
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def _locator(raw: str | None) -> tuple[str | None, str | None]:
    if not raw or not isinstance(raw, str):
        return None, None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(loaded, dict):
        return None, None
    sheet = loaded.get("sheet")
    sheet_name = str(sheet)[:255] if sheet else None
    kind = loaded.get("type")
    try:
        if kind == "paragraph" and loaded.get("index"):
            return sheet_name, f"paragraph:{int(loaded['index'])}"
        if kind == "pdf" and loaded.get("page"):
            return sheet_name, f"page:{int(loaded['page'])}"
        if kind == "table" and loaded.get("row") and loaded.get("col"):
            table = int(loaded.get("table") or 1)
            return sheet_name, f"T{table}R{int(loaded['row'])}C{int(loaded['col'])}"
        if loaded.get("row") and loaded.get("col"):
            return sheet_name, f"{_letters(int(loaded['col']))}{int(loaded['row'])}"
    except (TypeError, ValueError):
        return sheet_name, None
    return sheet_name, None
