"""Connector setup wizard service (P1-15).

Generalized connector setup wizard providing a unified "Add a connector" flow
with permission explanation, validation, and setup steps.
"""

import logging

from sqlalchemy.orm import Session

from app.models.source_registry import SourceRegistry

logger = logging.getLogger(__name__)

CONNECTOR_CATALOG = {
    "aws": {
        "display_name": "Amazon Web Services",
        "auth_method": "iam_role",
        "permissions_required": [
            "iam:ListUsers", "iam:ListPolicies", "iam:GetAccountAuthorizationDetails",
            "s3:ListAllMyBuckets", "s3:GetBucketPolicy", "s3:GetBucketEncryption",
            "cloudtrail:DescribeTrails", "cloudtrail:GetTrailStatus",
        ],
        "data_collected": ["IAM users and policies", "S3 bucket configurations", "CloudTrail logging status"],
        "data_not_collected": ["File contents", "S3 object data", "Personal information"],
        "setup_steps": [
            "Create an IAM role with read-only permissions",
            "Configure trust policy for Trust Copilot",
            "Provide the role ARN",
            "Validate access",
        ],
    },
    "github": {
        "display_name": "GitHub",
        "auth_method": "github_app",
        "permissions_required": [
            "Repository metadata (read)", "Branch protection rules (read)",
            "Organization members (read)", "Repository collaborators (read)",
        ],
        "data_collected": ["Repository list and settings", "Branch protection rules", "Access and collaborator info"],
        "data_not_collected": ["Source code", "Commit contents", "Issue/PR body text"],
        "setup_steps": [
            "Install the Trust Copilot GitHub App",
            "Select repositories to grant access",
            "Authorize organization access",
            "Validate connection",
        ],
    },
    "google_workspace": {
        "display_name": "Google Workspace",
        "auth_method": "oauth_admin_consent",
        "permissions_required": [
            "Admin Directory API (read users)", "Admin Reports API (read login activity)",
            "Admin Roles API (read admin roles)",
        ],
        "data_collected": ["User directory", "MFA enrollment status", "Admin role assignments"],
        "data_not_collected": ["Email contents", "Drive files", "Calendar events"],
        "setup_steps": [
            "Sign in as a Google Workspace admin",
            "Review and consent to requested scopes",
            "Validate admin access",
            "Configure sync schedule",
        ],
    },
    "okta": {
        "display_name": "Okta",
        "auth_method": "api_token",
        "permissions_required": ["Users (read)", "Groups (read)", "Applications (read)"],
        "data_collected": ["User directory", "Group memberships", "Application assignments"],
        "data_not_collected": ["Passwords", "MFA secrets", "Session tokens"],
        "setup_steps": [
            "Generate an API token in Okta admin console",
            "Provide the Okta domain and token",
            "Validate access",
        ],
    },
    "azure": {
        "display_name": "Microsoft Azure",
        "auth_method": "service_principal",
        "permissions_required": ["Reader role on subscription", "Microsoft Graph Directory.Read.All"],
        "data_collected": ["Resource configurations", "AD users and groups", "Policy assignments"],
        "data_not_collected": ["Storage contents", "Key Vault secrets", "Application data"],
        "setup_steps": [
            "Create an Azure AD app registration",
            "Assign Reader role on target subscription",
            "Provide tenant ID, client ID, and client secret",
            "Validate access",
        ],
    },
    "gitlab": {
        "display_name": "GitLab",
        "auth_method": "personal_access_token",
        "permissions_required": ["read_api", "read_repository"],
        "data_collected": ["Project list and settings", "Branch protection rules", "Group membership"],
        "data_not_collected": ["Source code", "CI/CD secrets", "Issue contents"],
        "setup_steps": [
            "Generate a personal access token with read_api scope",
            "Provide the GitLab instance URL and token",
            "Validate access",
        ],
    },
    "slack": {
        "display_name": "Slack",
        "auth_method": "oauth",
        "permissions_required": ["channels:read", "chat:write"],
        "data_collected": ["Channel list", "Message metadata for configured channels"],
        "data_not_collected": ["DM contents", "File attachments", "User passwords"],
        "setup_steps": [
            "Install the Trust Copilot Slack app",
            "Select channels to monitor",
            "Authorize workspace access",
        ],
    },
    "gmail": {
        "display_name": "Gmail",
        "auth_method": "oauth",
        "permissions_required": ["gmail.readonly", "gmail.labels"],
        "data_collected": ["Email metadata from labeled threads", "Attachment metadata"],
        "data_not_collected": ["All inbox contents", "Draft emails", "Contact data"],
        "setup_steps": [
            "Sign in with Google account",
            "Consent to read-only access",
            "Configure label filters",
        ],
    },
}


def get_catalog() -> list[dict]:
    return [
        {"connector_type": k, **v}
        for k, v in CONNECTOR_CATALOG.items()
    ]


def get_connector_details(connector_type: str) -> dict | None:
    info = CONNECTOR_CATALOG.get(connector_type)
    if not info:
        return None
    return {"connector_type": connector_type, **info}


def start_setup(db: Session, workspace_id: int, connector_type: str) -> dict:
    info = CONNECTOR_CATALOG.get(connector_type)
    if not info:
        return {"error": f"Unknown connector type: {connector_type}"}

    existing = db.query(SourceRegistry).filter(
        SourceRegistry.workspace_id == workspace_id,
        SourceRegistry.source_type == connector_type,
    ).first()

    if existing and existing.enabled:
        return {"error": f"Connector '{connector_type}' is already enabled", "source_id": existing.id}

    if not existing:
        reg = SourceRegistry(
            workspace_id=workspace_id,
            source_type=connector_type,
            display_name=info["display_name"],
            auth_method=info["auth_method"],
            sync_cadence="daily",
            status="setup_pending",
            enabled=False,
        )
        db.add(reg)
        db.flush()
        source_id = reg.id
    else:
        existing.status = "setup_pending"
        db.flush()
        source_id = existing.id

    return {
        "source_id": source_id,
        "connector_type": connector_type,
        "status": "setup_pending",
        "setup_steps": info["setup_steps"],
        "permissions_required": info["permissions_required"],
        "data_collected": info["data_collected"],
        "data_not_collected": info["data_not_collected"],
    }


def validate_setup(db: Session, workspace_id: int, connector_type: str) -> dict:
    reg = db.query(SourceRegistry).filter(
        SourceRegistry.workspace_id == workspace_id,
        SourceRegistry.source_type == connector_type,
    ).first()
    if not reg:
        return {"error": "Connector not found. Please start setup first."}

    reg.status = "available"
    reg.enabled = True
    db.flush()
    return {
        "source_id": reg.id,
        "connector_type": connector_type,
        "status": "validated",
        "enabled": True,
    }


def disable_connector(db: Session, workspace_id: int, connector_type: str) -> dict:
    reg = db.query(SourceRegistry).filter(
        SourceRegistry.workspace_id == workspace_id,
        SourceRegistry.source_type == connector_type,
    ).first()
    if not reg:
        return {"error": "Connector not found"}
    reg.enabled = False
    reg.status = "disabled"
    db.flush()
    return {"source_id": reg.id, "connector_type": connector_type, "status": "disabled", "enabled": False}
