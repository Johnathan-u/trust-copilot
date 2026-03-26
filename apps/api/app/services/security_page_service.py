"""Public security and data-handling page service (P0-82)."""

from sqlalchemy.orm import Session

from app.services import security_faq_service as faq_svc


def get_public_security_page(db: Session, workspace_id: int) -> dict:
    """Generate the public-facing security page content."""
    faqs = faq_svc.list_faqs(db, workspace_id)
    categories = faq_svc.get_categories(db, workspace_id)

    sections = {}
    for faq in faqs:
        cat = faq["category"]
        if cat not in sections:
            sections[cat] = {"title": _category_title(cat), "items": []}
        sections[cat]["items"].append({
            "question": faq["question"],
            "answer": faq["answer"],
            "frameworks": faq["framework_tags"].split(",") if faq["framework_tags"] else [],
        })

    return {
        "title": "Security & Data Handling",
        "subtitle": "How we protect your data and maintain compliance",
        "sections": [{"category": k, **v} for k, v in sections.items()],
        "certifications": [
            {"name": "SOC 2 Type II", "status": "in_progress", "description": "Trust service criteria audit underway"},
            {"name": "GDPR", "status": "compliant", "description": "Data processing compliant with EU regulations"},
            {"name": "ISO 27001", "status": "planned", "description": "Information security management planned"},
        ],
        "infrastructure_highlights": [
            "AES-256 encryption at rest",
            "TLS 1.2+ encryption in transit",
            "Workspace-level tenant isolation",
            "TOTP multi-factor authentication",
            "Role-based access control (RBAC)",
            "Comprehensive audit logging",
            "Automated daily backups with 7-day recovery",
            "Containerized deployment on managed infrastructure",
        ],
        "contact": {
            "security_email": "security@trustcopilot.io",
            "dpa_available": True,
            "subprocessor_list_available": True,
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
