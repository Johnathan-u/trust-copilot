"""
Smoke: questionnaire mappings list returns quickly without per-row suggested evidence.

Run from apps/api with DATABASE_URL and a valid session cookie, or from Docker:

  docker compose exec -T api python -m scripts.verify_mappings_list_performance --questionnaire-id 1

Uses GET /mappings?include_suggested_evidence=false (default) and reports response time + row count.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from dotenv import load_dotenv

load_dotenv(API_ROOT / ".env")

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Question, Questionnaire


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--questionnaire-id", type=int, required=True)
    p.add_argument("--workspace-id", type=int, default=1)
    args = p.parse_args()

    db: Session = SessionLocal()
    try:
        qnr = (
            db.query(Questionnaire)
            .filter(
                Questionnaire.id == args.questionnaire_id,
                Questionnaire.workspace_id == args.workspace_id,
                Questionnaire.deleted_at.is_(None),
            )
            .first()
        )
        if not qnr:
            print(f"No questionnaire id={args.questionnaire_id} in workspace {args.workspace_id}")
            sys.exit(1)
        nq = (
            db.query(Question)
            .filter(Question.questionnaire_id == args.questionnaire_id)
            .count()
        )
        print(f"Questionnaire {args.questionnaire_id}: ~{nq} questions (approx)")
    finally:
        db.close()

    # In-process timing of the same handler logic (no HTTP): import route and call
    from app.api.routes.questionnaires import list_questionnaire_mappings

    session = {"workspace_id": args.workspace_id, "user_id": 1}
    db2: Session = SessionLocal()
    try:
        t0 = time.perf_counter()
        out = list_questionnaire_mappings(
            qnr_id=args.questionnaire_id,
            include_suggested_evidence=False,
            session=session,
            db=db2,
        )
        elapsed = time.perf_counter() - t0
        n = len(out.get("mappings", []))
        print(f"list_questionnaire_mappings(include_suggested_evidence=False): {elapsed:.3f}s, {n} mapping rows")
        if elapsed > 30:
            print("WARNING: still slow; check DB size, match_keywords, or supporting_evidence batch.")
    finally:
        db2.close()


if __name__ == "__main__":
    main()
