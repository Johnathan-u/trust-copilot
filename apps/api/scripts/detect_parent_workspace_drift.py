#!/usr/bin/env python3
"""Count legacy cross-workspace references for the parent-move guard (TC-02-BUG-001a).

Read-only. Prints JSON counts for the relationships guarded by tc06001_same_workspace_refs.
Does not update, backfill or delete rows. Do not point it at a production database from a
workstation; it is a report for a database the operator already chose to inspect.

Usage (from apps/api/):
  python scripts/detect_parent_workspace_drift.py
  python scripts/detect_parent_workspace_drift.py --print-sql
Exit code is 0 when every count is zero, 1 when any row is reported.
"""

import argparse
import json
import os
import sys
from pathlib import Path

_api_root = Path(__file__).resolve().parent.parent
if str(_api_root) not in sys.path:
    sys.path.insert(0, str(_api_root))

from dotenv import load_dotenv  # noqa: E402

_in_docker = Path("/.dockerenv").exists() or os.environ.get("TRUST_COPILOT_IN_DOCKER") == "1"
if not _in_docker:
    load_dotenv(_api_root / ".env", override=True)
    load_dotenv(_api_root.parent.parent / ".env")

from app.services.cross_workspace_audit import CHECKS, run_audit  # noqa: E402

PARENT_RELATIONSHIPS = (
    "evidence_items.document_id",
    "export_records.questionnaire_id",
    "evidence_gaps.questionnaire_id",
    "evidence_gaps.question_id",
    "evidence_gaps.answer_id",
)


def parent_checks():
    wanted = set(PARENT_RELATIONSHIPS)
    found = tuple(check for check in CHECKS if check.name in wanted)
    missing = wanted.difference(check.name for check in found)
    if missing:
        raise RuntimeError("missing relationship checks")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only parent-workspace drift report")
    parser.add_argument("--print-sql", action="store_true")
    args = parser.parse_args()
    checks = parent_checks()
    if args.print_sql:
        for check in checks:
            print(f"-- {check.name}\nSELECT COUNT(*) FROM ({check.sql}) AS hits;\n")
        return 0

    from sqlalchemy import create_engine

    from app.core.config import get_settings

    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as conn:
            report = run_audit(conn, read_only=True)
            conn.rollback()
    finally:
        engine.dispose()
    selected = [row for row in report["checks"] if row["check"] in PARENT_RELATIONSHIPS]
    payload = {"checks": selected, "total": sum(row["count"] for row in selected)}
    print(json.dumps(payload, indent=2))
    return 1 if payload["total"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
