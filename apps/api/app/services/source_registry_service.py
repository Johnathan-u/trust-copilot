"""Source registry service — manage evidence source types per workspace."""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.source_registry import SourceRegistry

logger = logging.getLogger(__name__)

KNOWN_SOURCES: list[dict] = [
    {
        "source_type": "manual",
        "display_name": "Manual Upload",
        "auth_method": "none",
        "sync_cadence": "manual",
        "object_types": "documents,policies,certifications,reports",
        "failure_modes": "upload_failed,parse_error,unsupported_format",
    },
    {
        "source_type": "slack",
        "display_name": "Slack",
        "auth_method": "bot_token",
        "sync_cadence": "realtime",
        "object_types": "messages,threads,files",
        "failure_modes": "token_revoked,channel_not_found,rate_limited,api_error",
    },
    {
        "source_type": "gmail",
        "display_name": "Gmail",
        "auth_method": "oauth2",
        "sync_cadence": "periodic_15m",
        "object_types": "emails,attachments",
        "failure_modes": "token_expired,refresh_failed,quota_exceeded,label_not_found",
    },
    {
        "source_type": "aws",
        "display_name": "Amazon Web Services",
        "auth_method": "iam_role_assumption",
        "sync_cadence": "daily",
        "object_types": "iam_users,iam_policies,iam_roles,s3_buckets,cloudtrail_config,security_hub_findings",
        "failure_modes": "credentials_invalid,role_not_assumable,insufficient_permissions,api_throttled,region_unavailable",
    },
    {
        "source_type": "github",
        "display_name": "GitHub",
        "auth_method": "oauth2_app",
        "sync_cadence": "daily",
        "object_types": "repos,branch_protections,collaborators,teams,security_alerts,dependabot",
        "failure_modes": "token_expired,app_not_installed,rate_limited,repo_not_found,insufficient_scope",
    },
    {
        "source_type": "gcp",
        "display_name": "Google Cloud Platform",
        "auth_method": "service_account",
        "sync_cadence": "daily",
        "object_types": "iam_policies,audit_logs,org_policies,kms_keys,scc_findings",
        "failure_modes": "credentials_invalid,project_not_found,api_disabled,quota_exceeded",
    },
    {
        "source_type": "azure",
        "display_name": "Microsoft Azure",
        "auth_method": "service_principal",
        "sync_cadence": "daily",
        "object_types": "aad_users,aad_roles,defender_findings,resource_policies,key_vault",
        "failure_modes": "credentials_expired,tenant_not_found,insufficient_permissions,api_throttled",
    },
    {
        "source_type": "okta",
        "display_name": "Okta",
        "auth_method": "api_token",
        "sync_cadence": "daily",
        "object_types": "users,groups,mfa_enrollment,sso_configs,auth_policies",
        "failure_modes": "token_invalid,rate_limited,org_not_found",
    },
    {
        "source_type": "google_workspace",
        "display_name": "Google Workspace",
        "auth_method": "oauth2_admin",
        "sync_cadence": "daily",
        "object_types": "users,groups,mfa_status,admin_roles,org_units",
        "failure_modes": "token_expired,admin_consent_missing,api_disabled,domain_not_verified",
    },
    {
        "source_type": "jira",
        "display_name": "Jira",
        "auth_method": "oauth2",
        "sync_cadence": "periodic_1h",
        "object_types": "security_tickets,vulnerability_tracking,incident_records,risk_items",
        "failure_modes": "token_expired,project_not_found,permission_denied,rate_limited",
    },
    {
        "source_type": "gitlab",
        "display_name": "GitLab",
        "auth_method": "personal_token",
        "sync_cadence": "daily",
        "object_types": "projects,branch_protections,members,merge_rules,security_scans",
        "failure_modes": "token_invalid,project_not_found,rate_limited,insufficient_scope",
    },
]


def seed_sources(db: Session, workspace_id: int) -> int:
    """Seed known source types for a workspace. Skip existing."""
    existing = {
        r.source_type
        for r in db.query(SourceRegistry.source_type).filter(SourceRegistry.workspace_id == workspace_id).all()
    }
    created = 0
    for src in KNOWN_SOURCES:
        if src["source_type"] in existing:
            continue
        db.add(SourceRegistry(workspace_id=workspace_id, **src))
        created += 1
    db.flush()
    return created


def list_sources(db: Session, workspace_id: int, enabled_only: bool = False) -> list[dict]:
    q = db.query(SourceRegistry).filter(SourceRegistry.workspace_id == workspace_id)
    if enabled_only:
        q = q.filter(SourceRegistry.enabled.is_(True))
    return [_serialize(s) for s in q.order_by(SourceRegistry.source_type).all()]


def get_source(db: Session, workspace_id: int, source_type: str) -> dict | None:
    row = db.query(SourceRegistry).filter(
        SourceRegistry.workspace_id == workspace_id,
        SourceRegistry.source_type == source_type,
    ).first()
    return _serialize(row) if row else None


def update_source(db: Session, workspace_id: int, source_type: str, **updates) -> dict | None:
    row = db.query(SourceRegistry).filter(
        SourceRegistry.workspace_id == workspace_id,
        SourceRegistry.source_type == source_type,
    ).first()
    if not row:
        return None
    for key in ("enabled", "sync_cadence", "status", "config_json", "last_sync_at", "last_sync_status", "last_error"):
        if key in updates:
            setattr(row, key, updates[key])
    db.flush()
    return _serialize(row)


def record_sync(db: Session, workspace_id: int, source_type: str, success: bool, error: str | None = None) -> None:
    """Record sync result for a source."""
    row = db.query(SourceRegistry).filter(
        SourceRegistry.workspace_id == workspace_id,
        SourceRegistry.source_type == source_type,
    ).first()
    if row:
        row.last_sync_at = datetime.now(timezone.utc)
        row.last_sync_status = "success" if success else "failed"
        row.last_error = error if not success else None
        db.flush()


def get_health_summary(db: Session, workspace_id: int) -> dict:
    """Get connector health summary."""
    sources = db.query(SourceRegistry).filter(SourceRegistry.workspace_id == workspace_id).all()
    total = len(sources)
    enabled = sum(1 for s in sources if s.enabled)
    healthy = sum(1 for s in sources if s.enabled and s.last_sync_status == "success")
    failed = sum(1 for s in sources if s.enabled and s.last_sync_status == "failed")
    never_synced = sum(1 for s in sources if s.enabled and s.last_sync_at is None)
    return {
        "total_sources": total,
        "enabled": enabled,
        "healthy": healthy,
        "failed": failed,
        "never_synced": never_synced,
    }


def _serialize(row: SourceRegistry) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "source_type": row.source_type,
        "display_name": row.display_name,
        "auth_method": row.auth_method,
        "sync_cadence": row.sync_cadence,
        "object_types": row.object_types,
        "failure_modes": row.failure_modes,
        "status": row.status,
        "enabled": row.enabled,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_sync_status": row.last_sync_status,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
