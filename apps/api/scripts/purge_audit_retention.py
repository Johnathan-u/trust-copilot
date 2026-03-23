"""Purge audit events older than AUDIT_RETENTION_DAYS. Run via cron or scheduler (e.g. daily)."""
from pathlib import Path
import os
import sys
from datetime import datetime, timedelta, timezone

# Load env like worker/main; ensure app is importable when run from repo root
_api_root = Path(__file__).resolve().parent.parent
_repo_root = _api_root.parent.parent
if str(_api_root) not in sys.path:
    sys.path.insert(0, str(_api_root))
if not os.environ.get("TRUST_COPILOT_IN_DOCKER"):
    try:
        from dotenv import load_dotenv
        load_dotenv(_api_root / ".env", override=True)
        load_dotenv(_repo_root / ".env")
    except ImportError:
        pass

from app.core.config import get_settings
from app.models import AuditEvent
from app.core.database import SessionLocal


def main() -> None:
    settings = get_settings()
    if settings.audit_retention_days <= 0:
        print("AUDIT_RETENTION_DAYS is 0; skipping purge.")
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.audit_retention_days)
    # Use naive datetime for DB if DB stores naive UTC
    cutoff_naive = cutoff.replace(tzinfo=None)
    db = SessionLocal()
    try:
        deleted = db.query(AuditEvent).filter(AuditEvent.occurred_at < cutoff_naive).delete()
        db.commit()
        print(f"Purged {deleted} audit events older than {settings.audit_retention_days} days.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
