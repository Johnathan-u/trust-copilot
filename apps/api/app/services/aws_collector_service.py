"""AWS connector services (P1-17, P1-18, P1-19, P1-20, P1-21).

Collection returns the versioned observation contract. This module does not
call AWS. A non-empty local key shape is not a successful provider observation.
"""

import logging

from sqlalchemy.orm import Session

from app.services.provider_adapter.adapters import (
    AWS,
    AWS_IAM,
    AWS_LOGGING,
    AWS_S3,
    legacy_collection,
    merge_observations,
)
from app.services.provider_adapter.contract import (
    CONTRACT_NAME,
    SCHEMA_VERSION,
    ObservationState,
    ProvenanceKind,
    utc_now,
)
from app.services.provider_adapter.surfaces import action_contract

logger = logging.getLogger(__name__)


def authenticate_aws(
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    region: str = "us-east-1",
    role_arn: str | None = None,
    *,
    workspace_id: int | None = None,
) -> dict:
    """Report whether key material is present. Does not contact AWS."""
    present = bool(access_key_id and secret_access_key)
    if not present:
        state = ObservationState.MISSING_PERMISSION
        error_code = "missing_credentials"
        message = "Missing credentials"
    else:
        state = ObservationState.UNKNOWN
        error_code = "not_verified"
        message = "Credential shape is present and was not verified with AWS"
    contract = action_contract(
        provider="aws",
        resource_id=f"aws:auth:{region}",
        state=state,
        provenance_kind=ProvenanceKind.ABSENT,
        workspace_id=workspace_id,
        external_account_id=region,
        error_code=error_code,
        safe_message=message,
        note="Authentication does not store collected evidence",
    )
    if not present:
        return {
            "authenticated": False,
            "error": "Missing credentials",
            "observation_contract": contract,
        }
    return {
        "authenticated": True,
        "region": region,
        "role_arn": role_arn,
        "method": "assume_role" if role_arn else "access_key",
        "validated_at": utc_now().isoformat(),
        "observation_contract": contract,
    }


def collect_iam_posture(
    region: str = "us-east-1",
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Collect AWS IAM security posture (P1-18)."""
    return legacy_collection(
        AWS,
        source="aws.iam",
        scope_fields={"region": region},
        workspace_id=workspace_id,
        external_account_id=region,
        signals=AWS_IAM,
        recorded=recorded,
    )


def collect_s3_posture(
    region: str = "us-east-1",
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Collect AWS S3 security posture (P1-19)."""
    return legacy_collection(
        AWS,
        source="aws.s3",
        scope_fields={"region": region},
        workspace_id=workspace_id,
        external_account_id=region,
        signals=AWS_S3,
        recorded=recorded,
    )


def collect_logging_posture(
    region: str = "us-east-1",
    *,
    workspace_id: int | None = None,
    recorded=None,
) -> dict:
    """Collect AWS CloudTrail and logging posture (P1-20)."""
    return legacy_collection(
        AWS,
        source="aws.cloudtrail",
        scope_fields={"region": region},
        workspace_id=workspace_id,
        external_account_id=region,
        signals=AWS_LOGGING,
        recorded=recorded,
    )


def run_aws_sync(
    db: Session,
    workspace_id: int,
    region: str = "us-east-1",
    *,
    recorded=None,
) -> dict:
    """Run full AWS collection sync (P1-21). Does not persist static findings."""
    del db
    iam = collect_iam_posture(region, workspace_id=workspace_id, recorded=recorded)
    s3 = collect_s3_posture(region, workspace_id=workspace_id, recorded=recorded)
    logging_data = collect_logging_posture(region, workspace_id=workspace_id, recorded=recorded)
    findings = iam["findings"] + s3["findings"] + logging_data["findings"]
    return {
        "workspace_id": workspace_id,
        "region": region,
        "synced_at": utc_now().isoformat(),
        "sources_checked": ["aws.iam", "aws.s3", "aws.cloudtrail"],
        "total_findings": len(findings),
        "findings": findings,
        "observation_contract": {
            "schema_version": SCHEMA_VERSION,
            "contract": CONTRACT_NAME,
            "adapter": AWS.descriptor().to_dict(),
            "observations": merge_observations([iam, s3, logging_data]),
        },
    }
