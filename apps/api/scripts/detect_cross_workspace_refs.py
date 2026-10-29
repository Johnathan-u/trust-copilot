#!/usr/bin/env python3
"""Report stored cross-workspace references (TC-06-BUG-001). Read-only.

Runs every check in app.services.cross_workspace_audit inside a READ ONLY transaction and prints
JSON. Counts only by default; --ids adds referencing row ids (capped by --id-limit) and nothing
else. There is no write, backfill or delete mode. Cleanup is a Coordinator decision.

Usage (from apps/api/):
  python scripts/detect_cross_workspace_refs.py               # counts only
  python scripts/detect_cross_workspace_refs.py --ids         # counts + row ids
  python scripts/detect_cross_workspace_refs.py --print-sql   # print the queries, no DB access
Exit code is 0 when no cross-workspace references exist, 1 when any are found.
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only cross-workspace reference report")
    parser.add_argument("--ids", action="store_true", help="Include referencing row ids")
    parser.add_argument("--id-limit", type=int, default=100, help="Max ids per check")
    parser.add_argument("--print-sql", action="store_true", help="Print queries and exit")
    args = parser.parse_args()

    if args.print_sql:
        for check in CHECKS:
            note = "  -- report only" if check.report_only else ""
            print(f"-- {check.name}{note}\nSELECT COUNT(*) FROM ({check.sql}) AS hits;\n")
        return 0

    from sqlalchemy import create_engine

    from app.core.config import get_settings

    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as conn:
            report = run_audit(conn, include_ids=args.ids, id_limit=args.id_limit)
            conn.rollback()
    finally:
        engine.dispose()
    print(json.dumps(report, indent=2))
    return 1 if report["total"] else 0


if __name__ == "__main__":
    sys.exit(main())
