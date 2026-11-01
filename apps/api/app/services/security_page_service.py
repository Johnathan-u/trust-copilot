"""Public security and data-handling page (P0-82, TC-17-003).

Every compliance, audit, encryption, backup and contact assertion on the page comes
from an owner decision stored in ``security_claims``. A claim that needs proof is
shown as verified only while its proof is an approved evidence item in the same
workspace; otherwise the page falls back to the conservative wording. Nothing on
the page is asserted by code.
"""

import json
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import AuditEvent, EvidenceItem, SecurityClaim
from app.services import security_faq_service as faq_svc

SCHEMA_VERSION = 2
STATUSES = ("not_claimed", "claimed")

# key -> (group, public name, conservative wording shown until verified, proof kind)
# proof kind: "evidence" = an approved evidence item is required; "email" = an
# owner-approved address is the claim itself (no document can prove an inbox).
CATALOGUE: dict[str, dict] = {
    "soc2_type2": {
        "group": "certification",
        "name": "SOC 2 Type II",
        "fallback": "No SOC 2 audit has been completed.",
        "proof": "evidence",
    },
    "gdpr": {
        "group": "certification",
        "name": "GDPR",
        "fallback": "No GDPR compliance assessment has been completed.",
        "proof": "evidence",
    },
    "iso27001": {
        "group": "certification",
        "name": "ISO 27001",
        "fallback": "No ISO 27001 certification has been obtained.",
        "proof": "evidence",
    },
    "encryption_at_rest": {
        "group": "infrastructure",
        "name": "AES-256 encryption at rest",
        "fallback": "Deployment-dependent, not yet verified: AES-256 encryption at rest",
        "proof": "evidence",
    },
    "encryption_in_transit": {
        "group": "infrastructure",
        "name": "TLS 1.2+ encryption in transit",
        "fallback": "Deployment-dependent, not yet verified: TLS 1.2+ encryption in transit",
        "proof": "evidence",
    },
    "backups": {
        "group": "infrastructure",
        "name": "Automated backups and recovery",
        "fallback": "Deployment-dependent, not yet verified: automated backups and recovery",
        "proof": "evidence",
    },
    "dpa": {
        "group": "contact",
        "name": "Data processing agreement",
        "fallback": "No data processing agreement is published.",
        "proof": "evidence",
    },
    "subprocessor_list": {
        "group": "contact",
        "name": "Subprocessor list",
        "fallback": "No subprocessor list is published.",
        "proof": "evidence",
    },
    "security_contact": {
        "group": "contact",
        "name": "Security contact",
        "fallback": "No security contact has been approved.",
        "proof": "email",
    },
}

# Application features that ship with the product itself (TC-01-005 wording).
APPLICATION_FEATURES = (
    "Workspace-level tenant isolation (application layer)",
    "TOTP multi-factor authentication",
    "Role-based access control (RBAC)",
    "Audit logging of key workspace actions",
)

_EMAIL = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


class ClaimError(Exception):
    """A rejected claim change. ``status`` is the HTTP status to report."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _proof_for(db: Session, workspace_id: int, evidence_item_id: int | None):
    """Return the evidence item only if it is approved and in this workspace."""
    if evidence_item_id is None:
        return None
    item = db.get(EvidenceItem, evidence_item_id)
    if item is None or item.workspace_id != workspace_id:
        return None
    if (item.approval_status or "").lower() != "approved":
        return None
    return item


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _rows(db: Session, workspace_id: int) -> dict[str, SecurityClaim]:
    rows = (
        db.query(SecurityClaim)
        .filter(
            SecurityClaim.workspace_id == workspace_id,
            SecurityClaim.claim_key.in_(tuple(CATALOGUE)),
        )
        .all()
    )
    return {row.claim_key: row for row in rows}


def _effective(db: Session, workspace_id: int, key: str, row: SecurityClaim | None) -> dict:
    spec = CATALOGUE[key]
    out = {
        "key": key,
        "group": spec["group"],
        "name": spec["name"],
        "status": row.status if row else "not_claimed",
        "verified": False,
        "reason": "not_claimed",
        "statement": None,
        "value": None,
        "proof": None,
        "revision": row.revision if row else 0,
        "decided_at": _iso(row.decided_at) if row else None,
    }
    if row is None or row.status != "claimed":
        return out
    if spec["proof"] == "email":
        if row.value and _EMAIL.match(row.value):
            out.update(verified=True, reason="verified", value=row.value)
        else:
            out["reason"] = "value_unavailable"
        return out
    proof = _proof_for(db, workspace_id, row.evidence_item_id)
    if proof is None:
        out["reason"] = "proof_unavailable"
        return out
    out.update(
        verified=True,
        reason="verified",
        statement=row.statement or spec["name"],
        proof={"evidence_item_id": proof.id, "title": proof.title},
    )
    return out


def list_claims(db: Session, workspace_id: int) -> list[dict]:
    """Every catalogue claim with its stored decision and current verification."""
    rows = _rows(db, workspace_id)
    out = []
    for key in CATALOGUE:
        row = rows.get(key)
        item = _effective(db, workspace_id, key, row)
        item.update(
            proof_required=CATALOGUE[key]["proof"] == "evidence",
            stored_statement=row.statement if row else None,
            stored_value=row.value if row else None,
            evidence_item_id=row.evidence_item_id if row else None,
            decided_by_user_id=row.decided_by_user_id if row else None,
        )
        out.append(item)
    return out


def _clean_text(value, limit: int, label: str):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ClaimError(422, f"{label} must be text")
    if any((ord(c) < 32 and c not in "\n\r\t") or 127 <= ord(c) <= 159 for c in value):
        raise ClaimError(422, f"{label} contains an unsupported character")
    value = value.strip()
    if not value:
        return None
    if len(value) > limit:
        raise ClaimError(422, f"{label} must be at most {limit} characters")
    return value


def set_claim(
    db: Session,
    workspace_id: int,
    key: str,
    *,
    status: str,
    statement: str | None,
    value: str | None,
    evidence_item_id: int | None,
    expected_revision: int,
    actor_id: int | None,
) -> dict:
    """Record an owner decision for one claim. Caller commits.

    Same payload against the revision it produced = an idempotent retry that
    returns the stored decision unchanged. Any other stale revision is a conflict.
    """
    if key not in CATALOGUE:
        raise ClaimError(404, "Unknown security claim")
    if actor_id is None:
        raise ClaimError(403, "A signed-in workspace administrator must decide security claims")
    if status not in STATUSES:
        raise ClaimError(422, "Status must be not_claimed or claimed")
    spec = CATALOGUE[key]
    statement = _clean_text(statement, 500, "Statement")
    value = _clean_text(value, 320, "Value")
    if status == "not_claimed":
        statement, value, evidence_item_id = None, None, None
    elif spec["proof"] == "email":
        evidence_item_id, statement = None, None
        if value is None or not _EMAIL.match(value):
            raise ClaimError(422, "Enter a valid security contact email address")
    else:
        value = None
        if evidence_item_id is None:
            raise ClaimError(422, "Choose approved evidence that proves this claim")
        if _proof_for(db, workspace_id, evidence_item_id) is None:
            # Same answer for missing, other-workspace and unapproved evidence.
            raise ClaimError(422, "That evidence is not available as approved proof")

    row = (
        db.query(SecurityClaim)
        .filter(SecurityClaim.workspace_id == workspace_id, SecurityClaim.claim_key == key)
        .with_for_update()
        .populate_existing()
        .first()
    )
    current = row.revision if row else 0
    same = row is not None and (
        row.status,
        row.statement,
        row.value,
        row.evidence_item_id,
    ) == (status, statement, value, evidence_item_id)
    if expected_revision != current:
        if same and expected_revision == current - 1:
            return _effective(db, workspace_id, key, row)
        raise ClaimError(409, "This claim changed since you loaded it. Reload and try again.")
    if same:
        return _effective(db, workspace_id, key, row)
    now = datetime.now(timezone.utc)
    if row is None:
        row = SecurityClaim(workspace_id=workspace_id, claim_key=key, revision=1)
        db.add(row)
    else:
        row.revision = current + 1
    row.status = status
    row.statement = statement
    row.value = value
    row.evidence_item_id = evidence_item_id
    row.decided_by_user_id = actor_id
    row.decided_at = now
    db.flush()
    db.add(
        AuditEvent(
            action=f"security_claim.{status}",
            user_id=actor_id,
            workspace_id=workspace_id,
            resource_type="security_claim",
            resource_id=key,
            details=json.dumps({"revision": row.revision, "evidence_item_id": evidence_item_id}),
        )
    )
    db.flush()
    return _effective(db, workspace_id, key, row)


def get_public_security_page(db: Session, workspace_id: int) -> dict:
    """Generate the public-facing security page content."""
    faqs = faq_svc.list_published_faqs(db, workspace_id)
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

    rows = _rows(db, workspace_id)
    claims = {key: _effective(db, workspace_id, key, rows.get(key)) for key in CATALOGUE}

    certifications = []
    highlights = list(APPLICATION_FEATURES)
    for key, claim in claims.items():
        spec = CATALOGUE[key]
        if spec["group"] == "certification":
            certifications.append(
                {
                    "name": spec["name"],
                    "status": "attested" if claim["verified"] else "not_attested",
                    "description": claim["statement"] if claim["verified"] else spec["fallback"],
                    "proof": claim["proof"],
                }
            )
        elif spec["group"] == "infrastructure":
            highlights.append(claim["statement"] if claim["verified"] else spec["fallback"])

    contact = claims["security_contact"]
    return {
        "schema_version": SCHEMA_VERSION,
        "title": "Security & Data Handling",
        "subtitle": "How we protect your data",
        "sections": [{"category": k, **v} for k, v in sections.items()],
        "notice": (
            "Only claims approved by the workspace owner and backed by approved evidence "
            "are shown as attested or verified. Everything else is shown as not yet verified."
        ),
        "certifications": certifications,
        "infrastructure_highlights": highlights,
        "contact": {
            "security_email": contact["value"] if contact["verified"] else None,
            "dpa_available": claims["dpa"]["verified"],
            "subprocessor_list_available": claims["subprocessor_list"]["verified"],
        },
        "claims": [
            {k: v for k, v in claim.items() if k != "revision"} for claim in claims.values()
        ],
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
