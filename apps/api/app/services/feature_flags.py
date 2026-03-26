"""Per-workspace feature flag service.

Resolution order for is_enabled(workspace_id, flag_name):
  1. Database row for (workspace_id, flag_name) — if present, use its `enabled` value.
  2. Global default from KNOWN_FLAGS registry.
  3. False.

The KNOWN_FLAGS dict is the canonical list of flag names the application understands.
Each entry maps flag_name -> (default_enabled, description).
"""

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.models.feature_flag import FeatureFlag

logger = logging.getLogger(__name__)


KNOWN_FLAGS: dict[str, tuple[bool, str]] = {
    "connectors.slack": (True, "Enable Slack integration"),
    "connectors.gmail": (True, "Enable Gmail integration"),
    "connectors.aws": (False, "Enable AWS evidence connector"),
    "connectors.github": (False, "Enable GitHub evidence connector"),
    "connectors.gcp": (False, "Enable GCP evidence connector"),
    "connectors.azure": (False, "Enable Azure evidence connector"),
    "monitoring.continuous": (False, "Enable continuous control monitoring"),
    "monitoring.alerts": (True, "Enable compliance alerting"),
    "trust_center.auto_publish": (False, "Auto-publish approved answers to Trust Center"),
    "trust_center.nda_gating": (False, "Enable NDA-gated Trust Center access"),
    "trust_center.analytics": (False, "Enable Trust Center viewer analytics"),
    "answers.memory": (False, "Enable cross-questionnaire answer reuse"),
    "answers.confidence_routing": (False, "Route low-confidence answers to human review"),
    "answers.llm_rerank": (True, "LLM re-rank for question-to-control mapping"),
    "credits.enforce": (False, "Enforce credit limits on answer generation"),
    "exports.branded_cover": (False, "Include branded cover page in exports"),
    "beta.deal_rooms": (False, "Enable deal room feature (beta)"),
    "beta.promise_engine": (False, "Enable promise tracking engine (beta)"),
    "beta.remediation": (False, "Enable remediation playbooks (beta)"),
}


def _env_override(flag_name: str) -> Optional[bool]:
    """Check for an env-var override: FEATURE_<UPPER_SNAKE_NAME>=1|0."""
    env_key = "FEATURE_" + flag_name.upper().replace(".", "_")
    val = os.getenv(env_key)
    if val is None:
        return None
    return val.lower() in ("1", "true", "yes")


def is_enabled(db: Session, workspace_id: int, flag_name: str) -> bool:
    """Check whether a feature flag is enabled for a workspace.

    Resolution: env-var override > DB row > KNOWN_FLAGS default > False.
    """
    env = _env_override(flag_name)
    if env is not None:
        return env

    row = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.workspace_id == workspace_id, FeatureFlag.flag_name == flag_name)
        .first()
    )
    if row is not None:
        return row.enabled

    default, _ = KNOWN_FLAGS.get(flag_name, (False, ""))
    return default


def get_all_flags(db: Session, workspace_id: int) -> list[dict]:
    """Return all known flags with their resolved state for a workspace."""
    db_rows = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.workspace_id == workspace_id)
        .all()
    )
    db_map = {r.flag_name: r for r in db_rows}

    result = []
    for flag_name, (default, description) in sorted(KNOWN_FLAGS.items()):
        env = _env_override(flag_name)
        row = db_map.get(flag_name)

        if env is not None:
            enabled = env
            source = "env"
        elif row is not None:
            enabled = row.enabled
            source = "workspace"
        else:
            enabled = default
            source = "default"

        result.append({
            "flag_name": flag_name,
            "enabled": enabled,
            "source": source,
            "description": row.description if row and row.description else description,
        })

    for row in db_rows:
        if row.flag_name not in KNOWN_FLAGS:
            env = _env_override(row.flag_name)
            result.append({
                "flag_name": row.flag_name,
                "enabled": env if env is not None else row.enabled,
                "source": "env" if env is not None else "workspace",
                "description": row.description or "",
            })

    return result


def set_flag(db: Session, workspace_id: int, flag_name: str, enabled: bool) -> dict:
    """Set a feature flag for a workspace. Creates the row if it doesn't exist."""
    row = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.workspace_id == workspace_id, FeatureFlag.flag_name == flag_name)
        .first()
    )
    if row:
        row.enabled = enabled
    else:
        default_desc = KNOWN_FLAGS.get(flag_name, (False, ""))[1]
        row = FeatureFlag(
            workspace_id=workspace_id,
            flag_name=flag_name,
            enabled=enabled,
            description=default_desc or None,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "flag_name": row.flag_name,
        "enabled": row.enabled,
        "source": "workspace",
        "description": row.description or "",
    }


def seed_defaults(db: Session, workspace_id: int) -> int:
    """Seed all known flags for a workspace (skip existing rows). Returns count created."""
    existing = {
        r.flag_name
        for r in db.query(FeatureFlag.flag_name).filter(FeatureFlag.workspace_id == workspace_id).all()
    }
    created = 0
    for flag_name, (default, description) in KNOWN_FLAGS.items():
        if flag_name not in existing:
            db.add(FeatureFlag(
                workspace_id=workspace_id,
                flag_name=flag_name,
                enabled=default,
                description=description,
            ))
            created += 1
    if created:
        db.commit()
    return created
