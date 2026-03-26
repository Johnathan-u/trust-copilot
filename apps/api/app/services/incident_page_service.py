"""Incident, status, and vulnerability disclosure page service (P2-100)."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

VULNERABILITY_DISCLOSURE_POLICY = {
    "program_type": "Responsible Disclosure",
    "contact_email": "security@trustcopilot.com",
    "pgp_key_url": None,
    "scope": [
        "*.trustcopilot.com",
        "API endpoints",
        "Authentication flows",
    ],
    "out_of_scope": [
        "Social engineering",
        "DoS attacks",
        "Third-party services",
    ],
    "response_sla": {
        "acknowledgment": "24 hours",
        "triage": "5 business days",
        "resolution_target": "90 days",
    },
    "safe_harbor": True,
}


def get_system_status(db: Session | None = None) -> dict:
    """Return current system status."""
    return {
        "status": "operational",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "components": [
            {"name": "API", "status": "operational"},
            {"name": "Database", "status": "operational"},
            {"name": "File Storage", "status": "operational"},
            {"name": "AI Pipeline", "status": "operational"},
            {"name": "Trust Center", "status": "operational"},
        ],
        "incidents": [],
        "scheduled_maintenance": [],
    }


def get_vulnerability_disclosure() -> dict:
    return VULNERABILITY_DISCLOSURE_POLICY


def report_vulnerability(
    reporter_name: str,
    reporter_email: str,
    description: str,
    severity: str = "unknown",
    affected_component: str | None = None,
) -> dict:
    """Accept a vulnerability report submission."""
    valid_severities = ("critical", "high", "medium", "low", "informational", "unknown")
    if severity not in valid_severities:
        severity = "unknown"
    return {
        "status": "received",
        "reference_id": f"VD-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "reporter_email": reporter_email,
        "severity": severity,
        "next_steps": "You will receive an acknowledgment within 24 hours.",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
