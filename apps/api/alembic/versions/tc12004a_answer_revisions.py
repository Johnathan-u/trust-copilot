"""Draft revisions for an approved answer (TC-12-004a).

SCHEMA CHANGE. Review this migration before it is applied.

``answers`` is not altered. Approved text, citations, and status stay on that
row. Explicit regenerate inserts ``answer_revisions``. Downgrade copies those
rows into ``tc12004a_revision_archive`` (no foreign keys) and drops the live
table. Upgrade again restores a revision whose answer and question still
exist, then drops the archive. A revision whose answer was deleted is not
restored.

The revision id fits alembic_version.version_num (varchar(32)). down_revision
is the single alembic head on master when this file is parented. This revision
does not import the application package.

Revision ID: tc12004a_answer_revisions
Revises: tc05001c_mfa_satisfied
"""

import sqlalchemy as sa

from alembic import op

revision = "tc12004a_answer_revisions"
down_revision = "tc05001c_mfa_satisfied"
branch_labels = None
depends_on = None

_LIVE = "answer_revisions"
_ARCHIVE = "tc12004a_revision_archive"

_COLUMNS = (
    "id",
    "answer_id",
    "question_id",
    "revision_number",
    "text",
    "citations",
    "confidence",
    "insufficient_reason",
    "gating_reason",
    "primary_categories_json",
    "evidence_fingerprint",
    "outcome_code",
    "status",
    "created_at",
    "updated_at",
)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _revision_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("answer_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("citations", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("insufficient_reason", sa.String(length=64), nullable=True),
        sa.Column("gating_reason", sa.String(length=64), nullable=True),
        sa.Column("primary_categories_json", sa.Text(), nullable=True),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("outcome_code", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    ]


def _copy(source: str, target: str, where: str = "") -> None:
    cols = ", ".join(_COLUMNS)
    op.execute(sa.text(f"INSERT INTO {target} ({cols}) SELECT {cols} FROM {source} {where}"))


def _setval() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        sa.text(
            """
            SELECT setval(
                pg_get_serial_sequence('answer_revisions', 'id'),
                GREATEST(COALESCE((SELECT MAX(id) FROM answer_revisions), 1), 1),
                (SELECT MAX(id) IS NOT NULL FROM answer_revisions)
            )
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        _LIVE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "answer_id",
            sa.Integer(),
            sa.ForeignKey("answers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Integer(),
            sa.ForeignKey("questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("citations", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("insufficient_reason", sa.String(length=64), nullable=True),
        sa.Column("gating_reason", sa.String(length=64), nullable=True),
        sa.Column("primary_categories_json", sa.Text(), nullable=True),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("outcome_code", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "answer_id", "revision_number", name="uq_answer_revisions_answer_number"
        ),
    )
    op.create_index("ix_answer_revisions_answer_id", _LIVE, ["answer_id"])
    op.create_index("ix_answer_revisions_question_id", _LIVE, ["question_id"])
    op.create_index("ix_answer_revisions_answer_status", _LIVE, ["answer_id", "status"])
    if _ARCHIVE in _tables():
        _copy(
            _ARCHIVE,
            _LIVE,
            "WHERE EXISTS (SELECT 1 FROM answers WHERE answers.id = "
            f"{_ARCHIVE}.answer_id) AND EXISTS (SELECT 1 FROM questions "
            f"WHERE questions.id = {_ARCHIVE}.question_id)",
        )
        op.drop_table(_ARCHIVE)
        _setval()


def downgrade() -> None:
    if _LIVE not in _tables():
        return
    if _ARCHIVE not in _tables():
        op.create_table(_ARCHIVE, *_revision_columns())
    _copy(_LIVE, _ARCHIVE)
    op.drop_index("ix_answer_revisions_answer_status", table_name=_LIVE)
    op.drop_index("ix_answer_revisions_question_id", table_name=_LIVE)
    op.drop_index("ix_answer_revisions_answer_id", table_name=_LIVE)
    op.drop_table(_LIVE)
