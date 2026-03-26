"""Incident, status, and vulnerability disclosure API (P2-100)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services import incident_page_service as ips

router = APIRouter(prefix="/status", tags=["status"])


class VulnerabilityReportBody(BaseModel):
    reporter_name: str
    reporter_email: str
    description: str
    severity: str = "unknown"
    affected_component: str | None = None


@router.get("")
async def system_status(db: Session = Depends(get_db)):
    """Public endpoint for system status."""
    return ips.get_system_status(db)


@router.get("/vulnerability-disclosure")
async def vulnerability_disclosure():
    """Public endpoint for vulnerability disclosure policy."""
    return ips.get_vulnerability_disclosure()


@router.post("/vulnerability-report")
async def report_vulnerability(body: VulnerabilityReportBody):
    """Public endpoint to report a vulnerability."""
    return ips.report_vulnerability(
        body.reporter_name, body.reporter_email, body.description,
        body.severity, body.affected_component,
    )
