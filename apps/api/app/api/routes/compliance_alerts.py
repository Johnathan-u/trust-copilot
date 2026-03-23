"""Compliance Alerts — active alert computation from existing coverage data."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.auth_deps import require_can_admin
from app.core.database import get_db

router = APIRouter(prefix="/compliance-alerts")

COVERAGE_THRESHOLD = 80
INSUFFICIENT_THRESHOLD = 15
WEAK_CONFIDENCE_THRESHOLD = 50


@router.get("/active")
def get_active_alerts(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_can_admin),
):
    from app.services.compliance_coverage import get_compliance_coverage

    workspace_id = request.state.workspace_id
    data = get_compliance_coverage(db, workspace_id)
    kpi = data["kpi"]
    alerts: list[dict] = []

    if kpi["total_questions"] == 0:
        return {"alerts": alerts}

    if kpi["coverage_pct"] < COVERAGE_THRESHOLD:
        alerts.append({
            "severity": "high",
            "title": "Low coverage",
            "description": f"Coverage is at {kpi['coverage_pct']}%, below the {COVERAGE_THRESHOLD}% target.",
            "metric": kpi["coverage_pct"],
            "type": "coverage_drop",
        })

    if kpi["insufficient_pct"] > INSUFFICIENT_THRESHOLD:
        alerts.append({
            "severity": "high",
            "title": "High insufficient-answer rate",
            "description": f"{kpi['total_insufficient']} questions ({kpi['insufficient_pct']}%) lack sufficient evidence.",
            "metric": kpi["insufficient_pct"],
            "type": "high_insufficient",
        })

    if kpi["blind_spot_count"] > 0:
        top_blind = data["blind_spots"][:3]
        names = ", ".join(b["subject"] for b in top_blind)
        alerts.append({
            "severity": "medium" if kpi["blind_spot_count"] <= 2 else "high",
            "title": f"{kpi['blind_spot_count']} blind spot{'s' if kpi['blind_spot_count'] != 1 else ''} detected",
            "description": f"Subject areas with insufficient evidence: {names}.",
            "metric": kpi["blind_spot_count"],
            "type": "blind_spot",
        })

    weak = data.get("weak_areas", [])
    if weak:
        worst = weak[0]
        alerts.append({
            "severity": "medium",
            "title": "Weak evidence in key area",
            "description": f"{worst['subject']} has avg confidence of {worst['avg_confidence']}% across {worst['count']} answers.",
            "metric": worst["avg_confidence"],
            "type": "weak_evidence",
        })

    fw_gaps = [f for f in data.get("framework_coverage", []) if f["coverage_pct"] < 70]
    for fg in fw_gaps[:2]:
        alerts.append({
            "severity": "medium",
            "title": f"Low {fg['framework']} coverage",
            "description": f"Only {fg['drafted']}/{fg['total']} questions answered ({fg['coverage_pct']}%).",
            "metric": fg["coverage_pct"],
            "type": "framework_gap",
        })

    return {"alerts": alerts}
