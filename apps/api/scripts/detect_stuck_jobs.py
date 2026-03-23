#!/usr/bin/env python3
"""Detect and optionally recover jobs stuck in RUNNING (e.g. worker crash). Run periodically or on-demand.

Definition of stuck: status=running and started_at older than STUCK_THRESHOLD_MINUTES.
Recovery: set status=failed, error='Stuck (recovered by detect_stuck_jobs)' so they are not retried indefinitely.

Usage (from apps/api/):
  python scripts/detect_stuck_jobs.py           # report only
  python scripts/detect_stuck_jobs.py --recover # mark stuck jobs as failed
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure app is importable
_api_root = Path(__file__).resolve().parent.parent
if str(_api_root) not in sys.path:
    sys.path.insert(0, str(_api_root))

from dotenv import load_dotenv
_in_docker = Path("/.dockerenv").exists() or os.environ.get("TRUST_COPILOT_IN_DOCKER") == "1"
if not _in_docker:
    load_dotenv(_api_root / ".env", override=True)
    load_dotenv(_api_root.parent.parent / ".env")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.models import Job, JobStatus

STUCK_THRESHOLD_MINUTES = 30


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect jobs stuck in RUNNING")
    parser.add_argument("--recover", action="store_true", help="Mark stuck jobs as failed")
    parser.add_argument("--minutes", type=int, default=STUCK_THRESHOLD_MINUTES, help="Consider running jobs older than this as stuck")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.database_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Use UTC naive for DB comparison (jobs.started_at is typically stored without tz)
        threshold = datetime.utcnow() - timedelta(minutes=args.minutes)
        stuck = (
            session.query(Job)
            .filter(Job.status == JobStatus.RUNNING.value, Job.started_at.isnot(None), Job.started_at < threshold)
            .order_by(Job.started_at)
            .all()
        )
        if not stuck:
            print("No stuck jobs found.")
            return
        print(f"Found {len(stuck)} stuck job(s) (RUNNING and started_at < {args.minutes} min ago):")
        for j in stuck:
            print(f"  id={j.id} kind={j.kind} workspace_id={j.workspace_id} started_at={j.started_at}")
        if args.recover:
            for j in stuck:
                j.status = JobStatus.FAILED.value
                j.error = "Stuck (recovered by detect_stuck_jobs)"
                j.completed_at = datetime.utcnow()
                session.merge(j)
            session.commit()
            print(f"Marked {len(stuck)} job(s) as failed.")
        else:
            print("Run with --recover to mark these jobs as failed.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
