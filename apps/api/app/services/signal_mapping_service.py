"""Map connector signals to controls (P1-32)."""

import logging
from sqlalchemy.orm import Session

from app.models.workspace_control import WorkspaceControl
from app.models.framework_control import FrameworkControl

logger = logging.getLogger(__name__)

SIGNAL_CONTROL_MAP: dict[str, list[str]] = {
    "aws.iam.mfa_enabled": ["AC-2", "IA-2", "AC-7"],
    "aws.iam.password_policy": ["IA-5", "AC-2"],
    "aws.iam.root_access_key": ["AC-6", "AC-2"],
    "aws.s3.public_access": ["AC-3", "SC-7"],
    "aws.s3.encryption": ["SC-28", "SC-13"],
    "aws.s3.versioning": ["CP-9", "SI-12"],
    "aws.cloudtrail.enabled": ["AU-2", "AU-3", "AU-12"],
    "aws.cloudtrail.multi_region": ["AU-2", "AU-6"],
    "github.branch_protection": ["CM-3", "SA-10"],
    "github.code_review_required": ["CM-3", "SA-11"],
    "github.vulnerability_alerts": ["SI-5", "RA-5"],
    "github.secret_scanning": ["SC-12", "SC-28"],
    "github.2fa_required": ["AC-2", "IA-2"],
    "google.mfa_enrollment": ["AC-2", "IA-2"],
    "google.admin_roles": ["AC-6", "AC-2"],
    "google.sso_configured": ["IA-8", "IA-2"],
    "google.password_policy": ["IA-5"],
    "slack.token_active": ["AC-2", "IA-4"],
    "gmail.token_active": ["AC-2", "IA-4"],
    "okta.mfa_policy": ["AC-2", "IA-2"],
    "okta.session_policy": ["AC-12", "SC-10"],
    "azure.mfa_enabled": ["AC-2", "IA-2"],
    "azure.conditional_access": ["AC-3", "AC-6"],
    "gcp.iam_audit": ["AU-2", "AU-3"],
    "manual.policy_uploaded": ["PL-1", "PL-2"],
    "manual.evidence_uploaded": ["CA-7", "CA-2"],
}


def get_signal_map() -> dict[str, list[str]]:
    return SIGNAL_CONTROL_MAP


def get_controls_for_signal(signal: str) -> list[str]:
    return SIGNAL_CONTROL_MAP.get(signal, [])


def get_signals_for_control(control_key: str) -> list[str]:
    return [
        signal
        for signal, controls in SIGNAL_CONTROL_MAP.items()
        if control_key in controls
    ]


def evaluate_signal(
    db: Session,
    workspace_id: int,
    signal: str,
    value: bool,
    metadata: dict | None = None,
) -> dict:
    """Evaluate a signal against mapped controls and update status."""
    control_keys = get_controls_for_signal(signal)
    if not control_keys:
        return {"signal": signal, "mapped_controls": 0, "status": "unmapped"}

    affected = []
    for key in control_keys:
        controls = (
            db.query(WorkspaceControl)
            .join(FrameworkControl, WorkspaceControl.framework_control_id == FrameworkControl.id)
            .filter(
                WorkspaceControl.workspace_id == workspace_id,
                FrameworkControl.control_key == key,
            )
            .all()
        )
        for ctrl in controls:
            affected.append({
                "control_key": key,
                "workspace_control_id": ctrl.id,
                "signal_passed": value,
            })

    return {
        "signal": signal,
        "value": value,
        "mapped_controls": len(control_keys),
        "affected_controls": affected,
    }


def get_coverage_matrix(db: Session, workspace_id: int) -> dict:
    """Show which controls have signal mappings and which don't."""
    controls = (
        db.query(WorkspaceControl, FrameworkControl.control_key)
        .outerjoin(FrameworkControl, WorkspaceControl.framework_control_id == FrameworkControl.id)
        .filter(WorkspaceControl.workspace_id == workspace_id)
        .all()
    )

    all_mapped_keys: set[str] = set()
    for signals in SIGNAL_CONTROL_MAP.values():
        all_mapped_keys.update(signals)

    covered = []
    uncovered = []
    for ctrl, ctrl_key in controls:
        if ctrl_key and ctrl_key in all_mapped_keys:
            signals = get_signals_for_control(ctrl_key)
            covered.append({"control_key": ctrl_key, "signals": signals})
        else:
            uncovered.append({"control_key": ctrl_key or ctrl.custom_name or f"wc-{ctrl.id}"})

    return {
        "total_controls": len(controls),
        "covered": len(covered),
        "uncovered": len(uncovered),
        "covered_controls": covered,
        "uncovered_controls": uncovered,
    }
