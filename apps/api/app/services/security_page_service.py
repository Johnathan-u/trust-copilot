"""Public security and data-handling page service (P0-82)."""

from sqlalchemy.orm import Session

from app.services import security_faq_service as faq_svc


def get_public_security_page(db: Session, workspace_id: int) -> dict:
    """Generate the public-facing security page content."""
    faqs = faq_svc.list_faqs(db, workspace_id)
    categories = faq_svc.get_categories(db, workspace_id)  # noqa: F841

    sections = {}
    for faq in faqs:
        cat = faq["category"]
        if cat not in sections:
            sections[cat] = {"title": _category_title(cat), "items": []}
        sections[cat]["items"].append(
            {
                "question": faq["question"],
                "answer": faq["answer"],
                "frameworks": faq["framework_tags"].split(",") if faq["framework_tags"] else [],
            }
        )

    return {
        "title": "Security & Data Handling",
        "subtitle": "How we protect your data",
        "sections": [{"category": k, **v} for k, v in sections.items()],
        "notice": (
            "Default FAQ answers are templates that must be verified against the actual "
            "deployment before publishing. No certifications or attestations are claimed."
        ),
        "certifications": [
            # TC-01-005: no audit, certification, or compliance attestation has been
            # completed. Do not change these statuses without linked evidence.
            {
                "name": "SOC 2 Type II",
                "status": "not_attested",
                "description": "No SOC 2 audit has been completed.",
            },
            {
                "name": "GDPR",
                "status": "not_attested",
                "description": "No GDPR compliance assessment has been completed.",
            },
            {
                "name": "ISO 27001",
                "status": "not_attested",
                "description": "No ISO 27001 certification has been obtained.",
            },
        ],
        "infrastructure_highlights": [
            # TC-01-005: application features are listed as implemented, pending
            # acceptance; hosting controls depend on the deployment and are unverified.
            "Workspace-level tenant isolation (application layer)",
            "TOTP multi-factor authentication",
            "Role-based access control (RBAC)",
            "Audit logging of key workspace actions",
            "Deployment-dependent, not yet verified: AES-256 encryption at rest",
            "Deployment-dependent, not yet verified: TLS 1.2+ encryption in transit",
            "Deployment-dependent, not yet verified: automated backups and recovery",
        ],
        "contact": {
            "security_email": "security@trustcopilot.io",
            "dpa_available": False,
            "subprocessor_list_available": False,
        },
    }


def _category_title(cat: str) -> str:
    titles = {
        "data_storage": "Data Storage & Encryption",
        "access_control": "Access Control & Authentication",
        "data_retention": "Data Retention & Deletion",
        "audit_logging": "Audit Logging & Monitoring",
        "infrastructure": "Infrastructure & Architecture",
        "incident_response": "Incident Response & Vulnerability Management",
        "data_privacy": "Data Privacy & AI Usage",
        "tenant_isolation": "Tenant Isolation",
        "business_continuity": "Business Continuity & Backups",
        "third_party": "Third-Party Services & Subprocessors",
        "change_management": "Change Management & Development Practices",
    }
    return titles.get(cat, cat.replace("_", " ").title())
