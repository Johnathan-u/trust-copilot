"""Read-only detector for stored cross-workspace references (TC-06-BUG-001).

Every check is a SELECT that returns the primary key of a referencing row whose target belongs to a
different workspace. Nothing is written, backfilled or deleted. By default only counts are
reported. Row ids are returned only when include_ids=True, capped by id_limit, and never with any
other column (no names, titles, filenames or text).

Questions and answers have no workspace_id; their workspace is questionnaires.workspace_id.
JSON id arrays are expanded only when the column is a well-formed JSON array (Postgres 16 IS JSON),
and only integer elements are compared, so malformed legacy values cannot abort the report.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection

_Q_OF_QUESTION = (
    "JOIN questions q ON q.id = {col} JOIN questionnaires qn ON qn.id = q.questionnaire_id"
)
_Q_OF_ANSWER = (
    "JOIN answers a ON a.id = {col} JOIN questions q ON q.id = a.question_id "
    "JOIN questionnaires qn ON qn.id = q.questionnaire_id"
)


@dataclass(frozen=True)
class Check:
    name: str
    sql: str
    report_only: bool = False


def _direct(table: str, alias: str, col: str, target: str) -> Check:
    return Check(
        f"{table}.{col}",
        f"SELECT {alias}.id FROM {table} {alias} JOIN {target} t ON t.id = {alias}.{col} "
        f"WHERE t.workspace_id <> {alias}.workspace_id",
    )


def _via_question(table: str, alias: str, col: str) -> Check:
    join = _Q_OF_QUESTION.format(col=f"{alias}.{col}")
    return Check(
        f"{table}.{col}",
        f"SELECT {alias}.id FROM {table} {alias} {join} WHERE qn.workspace_id <> {alias}.workspace_id",
    )


def _via_answer(table: str, alias: str, col: str) -> Check:
    join = _Q_OF_ANSWER.format(col=f"{alias}.{col}")
    return Check(
        f"{table}.{col}",
        f"SELECT {alias}.id FROM {table} {alias} {join} WHERE qn.workspace_id <> {alias}.workspace_id",
    )


def _json_ids(table: str, alias: str, col: str, target: str, report_only: bool = False) -> Check:
    return Check(
        f"{table}.{col}",
        "WITH arrays AS MATERIALIZED ("
        f"SELECT {alias}.id AS row_id, {alias}.workspace_id AS ws, {alias}.{col} AS raw "
        f"FROM {table} {alias} WHERE {alias}.{col} IS JSON ARRAY"
        "), ids AS MATERIALIZED ("
        "SELECT row_id, ws, elem FROM arrays, LATERAL jsonb_array_elements_text(raw::jsonb) AS elem"
        "), ints AS MATERIALIZED ("
        "SELECT row_id, ws, elem::bigint AS ref FROM ids WHERE elem ~ '^[0-9]{1,18}$'"
        ") "
        f"SELECT DISTINCT ints.row_id FROM ints JOIN {target} t ON t.id = ints.ref "
        "WHERE t.workspace_id <> ints.ws",
        report_only,
    )


CHECKS: tuple[Check, ...] = (
    _direct("evidence_items", "e", "document_id", "documents"),
    _direct("export_records", "x", "questionnaire_id", "questionnaires"),
    _direct("evidence_gaps", "g", "questionnaire_id", "questionnaires"),
    _via_question("evidence_gaps", "g", "question_id"),
    _via_answer("evidence_gaps", "g", "answer_id"),
    _direct("vendor_requests", "v", "questionnaire_id", "questionnaires"),
    _via_answer("answer_delivery_outcomes", "o", "answer_id"),
    _direct("answer_delivery_outcomes", "o", "questionnaire_id", "questionnaires"),
    _direct("answer_delivery_outcomes", "o", "deal_id", "deals"),
    _direct("answer_delivery_outcomes", "o", "golden_answer_id", "golden_answers"),
    _direct("operator_queue_items", "oq", "questionnaire_id", "questionnaires"),
    _direct("question_mapping_preferences", "p", "questionnaire_id", "questionnaires"),
    _via_question("question_mapping_preferences", "p", "question_id"),
    _direct("question_mapping_preferences", "p", "preferred_control_id", "workspace_controls"),
    _via_answer("answer_reuse_provenance", "r", "answer_id"),
    _direct("answer_reuse_provenance", "r", "questionnaire_id", "questionnaires"),
    _direct("answer_reuse_provenance", "r", "deal_id", "deals"),
    _json_ids("answer_reuse_provenance", "r", "evidence_ids_json", "evidence_items"),
    _direct("proof_graph_edges", "pe", "from_node_id", "proof_graph_nodes"),
    _direct("proof_graph_edges", "pe", "to_node_id", "proof_graph_nodes"),
    _direct("buyer_satisfaction_signals", "s", "portal_id", "buyer_portals"),
    _direct("buyer_satisfaction_signals", "s", "questionnaire_id", "questionnaires"),
    _direct("buyer_escalations", "be", "portal_id", "buyer_portals"),
    _via_answer("buyer_escalations", "be", "answer_id"),
    _json_ids("deals", "dl", "linked_questionnaire_ids", "questionnaires", report_only=True),
)


def run_audit(
    conn: Connection,
    *,
    include_ids: bool = False,
    id_limit: int = 100,
    read_only: bool = True,
) -> dict:
    """Run every check and return {"checks": [...], "total": n}.

    read_only=True issues SET TRANSACTION READ ONLY first, so it must be the first statement of the
    connection's transaction. Tests that seed rows on the same connection pass read_only=False.
    """
    if read_only:
        conn.execute(text("SET TRANSACTION READ ONLY"))
    results = []
    total = 0
    for check in CHECKS:
        count = conn.execute(text(f"SELECT COUNT(*) FROM ({check.sql}) AS hits")).scalar_one()
        entry: dict = {"check": check.name, "count": int(count)}
        if check.report_only:
            entry["report_only"] = True
        if include_ids:
            rows = conn.execute(
                text(f"SELECT id FROM ({check.sql}) AS hits(id) ORDER BY id LIMIT :lim"),
                {"lim": max(0, int(id_limit))},
            )
            entry["ids"] = [int(r[0]) for r in rows]
        total += int(count)
        results.append(entry)
    return {"checks": results, "total": total}
