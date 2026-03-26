"""Case study service (P0-83) — CRUD and template."""

import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.case_study import CaseStudy

TEMPLATE = {
    "sections": [
        {"name": "Company Background", "field": "company_name", "prompt": "Company name, industry, size, and relevant context."},
        {"name": "The Challenge", "field": "challenge", "prompt": "How many questionnaires? How long did they take? What was the impact on deals?"},
        {"name": "The Solution", "field": "solution", "prompt": "How Trust Copilot was deployed, what was uploaded, how answers were generated."},
        {"name": "The Results", "field": "results", "prompt": "Time saved, questionnaires completed, deals unblocked, accuracy rate."},
        {"name": "Customer Quote", "field": "quote", "prompt": "A direct quote from the customer about their experience."},
    ],
    "suggested_metrics": [
        "questionnaires_completed",
        "hours_saved",
        "avg_completion_time_minutes",
        "accuracy_rate_pct",
        "deals_unblocked",
        "deal_value_unblocked",
    ],
}


def get_template() -> dict:
    return TEMPLATE


def create(db: Session, workspace_id: int, title: str, **fields) -> dict:
    cs = CaseStudy(workspace_id=workspace_id, title=title)
    for key in ("company_name", "industry", "company_size", "challenge", "solution", "results", "quote", "quote_attribution"):
        if key in fields and fields[key] is not None:
            setattr(cs, key, fields[key])
    if "metrics" in fields and fields["metrics"]:
        cs.metrics_json = json.dumps(fields["metrics"])
    db.add(cs)
    db.flush()
    return _serialize(cs)


def list_all(db: Session, workspace_id: int) -> list[dict]:
    rows = db.query(CaseStudy).filter(CaseStudy.workspace_id == workspace_id).order_by(CaseStudy.created_at.desc()).all()
    return [_serialize(r) for r in rows]


def get(db: Session, case_id: int) -> dict | None:
    row = db.query(CaseStudy).filter(CaseStudy.id == case_id).first()
    return _serialize(row) if row else None


def update(db: Session, case_id: int, **updates) -> dict | None:
    row = db.query(CaseStudy).filter(CaseStudy.id == case_id).first()
    if not row:
        return None
    for key in ("title", "company_name", "industry", "company_size", "challenge", "solution", "results", "quote", "quote_attribution", "status"):
        if key in updates and updates[key] is not None:
            setattr(row, key, updates[key])
    if "metrics" in updates and updates["metrics"] is not None:
        row.metrics_json = json.dumps(updates["metrics"])
    if updates.get("status") == "published" and not row.published_at:
        row.published_at = datetime.now(timezone.utc)
    db.flush()
    return _serialize(row)


def delete(db: Session, case_id: int) -> bool:
    row = db.query(CaseStudy).filter(CaseStudy.id == case_id).first()
    if not row:
        return False
    db.delete(row)
    db.flush()
    return True


def _serialize(row: CaseStudy) -> dict:
    metrics = None
    if row.metrics_json:
        try:
            metrics = json.loads(row.metrics_json)
        except Exception:
            pass
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "title": row.title,
        "company_name": row.company_name,
        "industry": row.industry,
        "company_size": row.company_size,
        "challenge": row.challenge,
        "solution": row.solution,
        "results": row.results,
        "quote": row.quote,
        "quote_attribution": row.quote_attribution,
        "metrics": metrics,
        "status": row.status,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
