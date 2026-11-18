"""Per-workspace feature flag service.

Resolution for is_enabled(workspace_id, flag_name):

Production (``app.core.session.is_production_env``, which reads ``APP_ENV`` on
the settings object and the process environment):

  1. Database row for (workspace_id, flag_name), when one exists.
  2. ``FEATURE_<UPPER_SNAKE>`` when the variable is set and no row exists.
  3. Built-in default from KNOWN_FLAGS.
  4. False.

Outside production (development, test, staging) the env var still overrides a
stored row:

  1. ``FEATURE_<UPPER_SNAKE>`` when set.
  2. Database row.
  3. KNOWN_FLAGS default.
  4. False.

The KNOWN_FLAGS dict is the canonical list of flag names the application understands.
Each entry maps flag_name -> (default_enabled, description).

``set_flag`` writes one ``feature_flag.updated`` audit event in the same
transaction as the row change. A repeat of the stored value still writes that
event and does not rewrite the row. ``seed_defaults`` inserts missing defaults
and does not write this event.

A name that would gate a security control is refused. ``is_enabled`` and
``set_flag`` raise ``SecurityFlagError`` instead of returning or storing false.
Permissions, CSRF, sessions, authentication, MFA, audit, rate limits and tenant
isolation are not flags.
"""

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import audit_log, persist_audit
from app.core.session import is_production_env
from app.models.feature_flag import FeatureFlag

logger = logging.getLogger(__name__)

# Durable record of a flag write. The feature_flags table has no actor column.
FLAG_UPDATED_ACTION = "feature_flag.updated"


class SecurityFlagError(ValueError):
    """A feature flag must not name a security control.

    ``is_enabled`` raises this instead of returning false, so a caller cannot
    treat "off" as permission to skip the control.
    """


# Path segments that name a security control. Compared after strip, lower-case
# and hyphen-to-underscore. A segment matches when it equals a token or starts
# with ``<token>_`` (``csrf_enforce``, ``auth_bypass``). ``release.tc16006.row``
# does not match. ``audit.write`` and ``session.cookie`` do.
SECURITY_FLAG_TOKENS = frozenset(
    {
        "permission",
        "permissions",
        "authz",
        "authorization",
        "csrf",
        "session",
        "sessions",
        "auth",
        "authentication",
        "login",
        "mfa",
        "audit",
        "auditing",
        "rate_limit",
        "ratelimit",
        "tenant",
        "tenancy",
        "isolation",
    }
)


def is_security_sensitive_flag(flag_name: str) -> bool:
    """True when this name would gate a security control if a caller read it."""
    name = flag_name.strip().lower().replace("-", "_")
    if not name:
        return False
    for part in name.split("."):
        if not part:
            continue
        if part in SECURITY_FLAG_TOKENS:
            return True
        for token in SECURITY_FLAG_TOKENS:
            if part.startswith(token + "_"):
                return True
    return False


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
    """Read FEATURE_<UPPER_SNAKE_NAME>.

    Absent returns None. ``1``, ``true`` and ``yes`` (any letter case) return
    True. Any other set value, including ``0`` and an empty string, returns False.
    """
    env_key = "FEATURE_" + flag_name.upper().replace(".", "_")
    val = os.getenv(env_key)
    if val is None:
        return None
    return val.lower() in ("1", "true", "yes")


def _resolve_enabled(row: Optional[FeatureFlag], flag_name: str) -> tuple[bool, str]:
    """Return ``(enabled, source)`` for one flag.

    In production a stored row wins over ``FEATURE_*``. The variable is a
    default only when that workspace has no row. Outside production the
    variable overrides the row.
    """
    env = _env_override(flag_name)
    if is_production_env():
        if row is not None:
            return bool(row.enabled), "workspace"
        if env is not None:
            return env, "env"
    elif env is not None:
        return env, "env"
    elif row is not None:
        return bool(row.enabled), "workspace"
    default, _description = KNOWN_FLAGS.get(flag_name, (False, ""))
    return bool(default), "default"


def is_enabled(db: Session, workspace_id: int, flag_name: str) -> bool:
    """Check whether a feature flag is enabled for a workspace.

    A security-control name raises ``SecurityFlagError`` before any read.
    It does not resolve to false.
    """
    if is_security_sensitive_flag(flag_name):
        raise SecurityFlagError("Security controls are not feature flags")
    row = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.workspace_id == workspace_id, FeatureFlag.flag_name == flag_name)
        .first()
    )
    enabled, _source = _resolve_enabled(row, flag_name)
    return enabled


def get_all_flags(db: Session, workspace_id: int) -> list[dict]:
    """Return all known flags with their resolved state for a workspace."""
    db_rows = db.query(FeatureFlag).filter(FeatureFlag.workspace_id == workspace_id).all()
    db_map = {r.flag_name: r for r in db_rows}

    result = []
    for flag_name, (_default, description) in sorted(KNOWN_FLAGS.items()):
        row = db_map.get(flag_name)
        enabled, source = _resolve_enabled(row, flag_name)
        result.append(
            {
                "flag_name": flag_name,
                "enabled": enabled,
                "source": source,
                "description": row.description if row and row.description else description,
            }
        )

    for row in db_rows:
        if row.flag_name not in KNOWN_FLAGS:
            enabled, source = _resolve_enabled(row, row.flag_name)
            result.append(
                {
                    "flag_name": row.flag_name,
                    "enabled": enabled,
                    "source": source,
                    "description": row.description or "",
                }
            )

    return result


def set_flag(
    db: Session,
    workspace_id: int,
    flag_name: str,
    enabled: bool,
    *,
    actor_user_id: int | None = None,
    actor_email: str | None = None,
) -> dict:
    """Set a feature flag for a workspace. Creates the row if it doesn't exist.

    Every call writes one audit event, including a no-op. A no-op is a row that
    already stores ``enabled``: the event records ``old_enabled == new_enabled``
    and ``changed: false``, and the row is left as it is. Creating a row records
    ``old_enabled: null``. A rejected request, including a security-control
    name, writes no event. ``SecurityFlagError`` is raised before any read
    or write.

    ``persist_audit`` commits ``db``. The flag change is still pending on that
    session, so the row and the event commit together. This function does not
    commit on its own.
    """
    if is_security_sensitive_flag(flag_name):
        raise SecurityFlagError("Security controls are not feature flags")
    requested = bool(enabled)
    row = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.workspace_id == workspace_id, FeatureFlag.flag_name == flag_name)
        .first()
    )
    if row is None:
        old_enabled: bool | None = None
        default_desc = KNOWN_FLAGS.get(flag_name, (False, ""))[1]
        row = FeatureFlag(
            workspace_id=workspace_id,
            flag_name=flag_name,
            enabled=requested,
            description=default_desc or None,
        )
        db.add(row)
        changed = True
    else:
        old_enabled = bool(row.enabled)
        changed = old_enabled != requested
        if changed:
            row.enabled = requested
    details = {
        "flag_name": flag_name,
        "old_enabled": old_enabled,
        "new_enabled": requested,
        "changed": changed,
    }
    audit_log(
        FLAG_UPDATED_ACTION,
        user_id=actor_user_id,
        email=actor_email,
        workspace_id=workspace_id,
        resource_type="feature_flag",
        resource_id=flag_name,
        details=details,
    )
    persist_audit(
        db,
        FLAG_UPDATED_ACTION,
        user_id=actor_user_id,
        email=actor_email,
        workspace_id=workspace_id,
        resource_type="feature_flag",
        resource_id=flag_name,
        details=details,
    )
    db.refresh(row)
    return {
        "flag_name": row.flag_name,
        "enabled": bool(row.enabled),
        "source": "workspace",
        "description": row.description or "",
    }


def seed_defaults(db: Session, workspace_id: int) -> int:
    """Seed all known flags for a workspace (skip existing rows). Returns count created.

    Does not write ``feature_flag.updated``. Seeding inserts missing defaults
    and leaves an existing row's value alone. A security-control name is
    skipped and is not inserted.
    """
    existing = {
        r.flag_name
        for r in db.query(FeatureFlag.flag_name)
        .filter(FeatureFlag.workspace_id == workspace_id)
        .all()
    }
    created = 0
    for flag_name, (default, description) in KNOWN_FLAGS.items():
        if is_security_sensitive_flag(flag_name):
            continue
        if flag_name not in existing:
            db.add(
                FeatureFlag(
                    workspace_id=workspace_id,
                    flag_name=flag_name,
                    enabled=default,
                    description=description,
                )
            )
            created += 1
    if created:
        db.commit()
    return created
