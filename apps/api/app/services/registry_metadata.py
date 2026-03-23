"""Shared registry metadata primitives for list modules."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable

FRAMEWORK_LABELS = [
    "SOC 2",
    "HIPAA",
    "ISO 27001",
    "NIST CSF 2.0",
    "NIST SP 800-53",
    "NIST SP 800-171",
    "NIST",
    "SIG",
    "CAIQ",
    "PCI DSS",
    "GDPR",
    "Unknown",
    "Multi-Framework",
    "General Vendor Security Questionnaire",
    "General Cloud Security Questionnaire",
    "Other",
]

SUBJECT_AREA_LABELS = [
    "Access Control",
    "Application Security",
    "Asset Inventory",
    "Audit & Assurance",
    "Availability & Resilience",
    "Backup & Restore",
    "Breach Notification",
    "Business Continuity & Disaster Recovery",
    "Change Management",
    "Cloud Security",
    "Confidentiality & Data Protection",
    "Configuration Management",
    "Container Security",
    "Contingency Planning",
    "Cryptography",
    "DNS Security",
    "Data Classification",
    "Data Loss Prevention",
    "Data Retention & Disposal",
    "Data Security & Privacy",
    "Detection & Response",
    "E-Discovery & Forensics",
    "Email Security",
    "Encryption",
    "Endpoint Security",
    "Governance & Risk Compliance",
    "HR / Security Training",
    "Identity & Authentication",
    "Incident Response",
    "Infrastructure Security",
    "Integrity Monitoring",
    "Interoperability & Portability",
    "Legal & Regulatory",
    "Logging",
    "Logging & Monitoring",
    "Media Protection",
    "Personnel Security",
    "Physical Security",
    "Privacy & Data Governance",
    "Privileged Access",
    "Processing Integrity",
    "Resilience",
    "Risk Assessment",
    "Risk Management",
    "Secure SDLC",
    "Supply Chain Risk",
    "Supplier Relationships",
    "System & Communications Protection",
    "AI Governance",
    "Vendor Management",
    "Vendor Risk",
    "Virtualization Security",
    "Web Filtering",
    "Workforce Security & Training",
    "Other",
]

SUBJECT_AREA_LABEL_TO_KEY: dict[str, str] = {
    "Access Control": "access_control",
    "Application Security": "application_security",
    "Asset Inventory": "asset_inventory",
    "Audit & Assurance": "audit_assurance",
    "Availability & Resilience": "availability_resilience",
    "Backup & Restore": "backup_restore",
    "Breach Notification": "breach_notification",
    "Business Continuity & Disaster Recovery": "business_continuity_disaster_recovery",
    "Change Management": "change_management",
    "Cloud Security": "cloud_security",
    "Confidentiality & Data Protection": "confidentiality_data_protection",
    "Configuration Management": "configuration_management",
    "Container Security": "container_security",
    "Contingency Planning": "contingency_planning",
    "Cryptography": "cryptography",
    "DNS Security": "dns_security",
    "Data Classification": "data_classification",
    "Data Loss Prevention": "dlp",
    "Data Retention & Disposal": "data_retention_disposal",
    "Data Security & Privacy": "data_security_privacy",
    "Detection & Response": "detection_response",
    "E-Discovery & Forensics": "e_discovery_forensics",
    "Email Security": "email_security",
    "Encryption": "cryptography",
    "Endpoint Security": "endpoint_security",
    "Governance & Risk Compliance": "governance_risk_compliance",
    "HR / Security Training": "workforce_security_training",
    "Identity & Authentication": "identity_authentication",
    "Incident Response": "incident_response",
    "Infrastructure Security": "system_communications_protection",
    "Integrity Monitoring": "integrity_monitoring",
    "Interoperability & Portability": "interoperability_portability",
    "Legal & Regulatory": "legal_regulatory",
    "Logging": "logging_monitoring",
    "Logging & Monitoring": "logging_monitoring",
    "Media Protection": "media_protection",
    "Personnel Security": "personnel_security",
    "Physical Security": "physical_security",
    "Privacy & Data Governance": "privacy_data_governance",
    "Privileged Access": "privileged_access",
    "Processing Integrity": "processing_integrity",
    "Resilience": "resilience",
    "Risk Assessment": "risk_assessment",
    "Risk Management": "governance_risk_compliance",
    "Secure SDLC": "secure_sdlc",
    "Supply Chain Risk": "supply_chain_risk",
    "Supplier Relationships": "supplier_relationships",
    "System & Communications Protection": "system_communications_protection",
    "AI Governance": "ai_governance",
    "Vendor Management": "vendor_risk",
    "Vendor Risk": "vendor_risk",
    "Virtualization Security": "virtualization_security",
    "Web Filtering": "web_filtering",
    "Workforce Security & Training": "workforce_security_training",
    "Other": "other",
}

MODULE_PREFIX = {
    "document": "DOC",
    "trust_request": "TR",
    "questionnaire": "QNR",
}


def build_display_id(kind: str, record_id: int) -> str:
    prefix = MODULE_PREFIX[kind]
    return f"{prefix}-{record_id:06d}"


def parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except Exception:
        return []
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def normalize_labels(values: Iterable[str], *, allowed: list[str], fallback: str = "Other") -> list[str]:
    """Dedupe case-insensitively, trim whitespace, map to allowed or fallback."""
    allowed_by_lower: dict[str, str] = {a.strip().lower(): a.strip() for a in allowed if a and str(a).strip()}
    deduped: list[str] = []
    seen_lower: set[str] = set()
    for value in values:
        label = value.strip() if value else ""
        if not label:
            continue
        canonical = allowed_by_lower.get(label.lower(), fallback)
        if canonical.lower() not in seen_lower:
            deduped.append(canonical)
            seen_lower.add(canonical.lower())
    if not deduped:
        return [fallback]
    return deduped


def to_json(values: list[str]) -> str:
    return json.dumps(values)


def parse_questionnaire_mapping_subject_areas(qnr) -> list[str] | None:
    """Validated subject-area labels for AI mapping / retrieval boost (aligned with evidence subject tags)."""
    raw = getattr(qnr, "mapping_preferred_subject_areas_json", None)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return None
        allowed = set(SUBJECT_AREA_LABELS)
        out: list[str] = []
        for x in data:
            s = str(x).strip()
            if s in allowed and s not in out:
                out.append(s)
        return out or None
    except Exception:
        return None


def ensure_created_at(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)
