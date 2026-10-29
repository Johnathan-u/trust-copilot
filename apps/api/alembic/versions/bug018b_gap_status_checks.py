"""CHECK constraints on evidence gap status and close_reason (TC-02-BUG-018b).

``evidence_gaps.status`` is written as open, accepted, dismissed or resolved.
``close_reason`` is written as NULL, question_removed or answer_sufficient.
The literals below are duplicated from the model on purpose. This module does
not import the application package. Tests lock the two copies together.

Upgrade pre-scans for rows that would fail either check. A hit raises with
the count and example ids and does not change any row. On a clean table each
check is added NOT VALID, then validated, so the checks are validated against
existing rows. ``env.py`` runs the whole migration in one transaction, so both
steps share that transaction and this does not shorten the lock.

Downgrade drops only those two constraints. It does not rewrite rows.

A third check, that close_reason is non-null only when status is resolved, is
not added. See ``SKIPPED_PRESENCE_CHECK``.

Revision ID: bug018b_gap_status_checks
Revises: tc21005_mapping_version
"""

import sqlalchemy as sa
from alembic import context, op

revision = "bug018b_gap_status_checks"
down_revision = "tc21005_mapping_version"
branch_labels = None
depends_on = None

_TABLE = "evidence_gaps"
# How many violating ids to print. The count in the error is the full count.
EXAMPLE_LIMIT = 5

STATUS_VALUES = ("open", "accepted", "dismissed", "resolved")
# evidence_sufficient is CONTROL_CHECK_CLOSE_REASON on control_check scan rows.
CLOSE_REASON_VALUES = ("question_removed", "answer_sufficient", "evidence_sufficient")

CK_EVIDENCE_GAPS_STATUS = "ck_evidence_gaps_status"
CK_EVIDENCE_GAPS_CLOSE_REASON = "ck_evidence_gaps_close_reason"

# update_evidence_gap_status and bulk_update_by_title set status to open,
# accepted or dismissed and leave close_reason unchanged, so a non-resolved
# row can still hold question_removed or answer_sufficient. The 018a backfill
# also leaves close_reason NULL on resolved rows whose reason has no parseable
# note, so "resolved iff close_reason is set" is not true either.
SKIPPED_PRESENCE_CHECK = (
    "close_reason IS NOT NULL only when status = 'resolved' was not added. "
    "update_evidence_gap_status and bulk_update_by_title change status without "
    "clearing close_reason, and bug018a_gap_closed_at_reason leaves close_reason "
    "NULL on resolved rows whose reason has no parseable note."
)


def _sql_in(column: str, values: tuple[str, ...]) -> str:
    parts: list[str] = []
    for value in values:
        if not value or any(ch in value for ch in "'\\"):
            raise RuntimeError(f"refusing unsafe check literal: {value!r}")
        parts.append("'" + value + "'")
    return f"{column} IN ({', '.join(parts)})"


STATUS_CHECK_SQL = _sql_in("status", STATUS_VALUES)
CLOSE_REASON_CHECK_SQL = "close_reason IS NULL OR " + _sql_in("close_reason", CLOSE_REASON_VALUES)


class EvidenceGapCheckViolation(RuntimeError):
    """Existing rows would fail a new check. No row was modified."""

    def __init__(self, reports: list[tuple[str, int, list[int]]]):
        self.reports = reports
        lines = [
            "evidence_gaps CHECK pre-scan failed. No rows were changed. "
            "Refusing to add constraints."
        ]
        for name, count, examples in reports:
            shown = ", ".join(str(gap_id) for gap_id in examples)
            lines.append(f"{name}: {count} violating row(s); example ids: {shown}")
        super().__init__("\n".join(lines))


def _violation_sql(predicate: str) -> str:
    return f"""
SELECT
    CAST(count(*) AS integer) AS n,
    COALESCE(
        (
            SELECT array_agg(sample.id ORDER BY sample.id)
            FROM (
                SELECT id
                FROM {_TABLE}
                WHERE NOT ({predicate})
                ORDER BY id
                LIMIT {EXAMPLE_LIMIT}
            ) AS sample
        ),
        CAST(ARRAY[] AS integer[])
    ) AS example_ids
FROM {_TABLE}
WHERE NOT ({predicate})
"""


def _example_ids(value: object) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        inner = value.strip("{}")
        if not inner:
            return []
        return [int(part) for part in inner.split(",")]
    return [int(item) for item in value]  # type: ignore[union-attr]


def violation_reports(connection) -> list[tuple[str, int, list[int]]]:
    """Rows that would fail a check. Empty when the table is clean. Reads only."""
    reports: list[tuple[str, int, list[int]]] = []
    for name, predicate in (
        (CK_EVIDENCE_GAPS_STATUS, STATUS_CHECK_SQL),
        (CK_EVIDENCE_GAPS_CLOSE_REASON, CLOSE_REASON_CHECK_SQL),
    ):
        row = connection.execute(sa.text(_violation_sql(predicate))).one()
        count = int(row[0])
        if count:
            reports.append((name, count, _example_ids(row[1])))
    return reports


def _add_check(name: str, expression: str) -> None:
    op.execute(
        sa.text(f"ALTER TABLE {_TABLE} ADD CONSTRAINT {name} " f"CHECK ({expression}) NOT VALID")
    )
    op.execute(sa.text(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {name}"))


def upgrade() -> None:
    # Offline --sql has no rows to scan. Online, refuse before any DDL.
    if not context.is_offline_mode():
        found = violation_reports(op.get_bind())
        if found:
            raise EvidenceGapCheckViolation(found)
    _add_check(CK_EVIDENCE_GAPS_STATUS, STATUS_CHECK_SQL)
    _add_check(CK_EVIDENCE_GAPS_CLOSE_REASON, CLOSE_REASON_CHECK_SQL)


def downgrade() -> None:
    op.drop_constraint(CK_EVIDENCE_GAPS_CLOSE_REASON, _TABLE, type_="check")
    op.drop_constraint(CK_EVIDENCE_GAPS_STATUS, _TABLE, type_="check")
