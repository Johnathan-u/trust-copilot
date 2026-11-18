"""TC-16-006: audited feature flags that cannot gate security.

Gap 1: a flag change writes ``feature_flag.updated`` with the actor and the
old and new values, and in production ``FEATURE_*`` does not override a row.

Gap 2: no flag gates permissions, CSRF, sessions, authentication, MFA, audit,
rate limits or tenant isolation. The admin API returns 400 for those names.
``SECURITY_MODULES`` is the denylist: a flag lookup in one of them fails this
file. Flags named on the public home and pricing pages default on.

The build job runs ``pytest -rs`` from ``apps/api``, which collects this file.
There is no separate workflow gate.

The backlog command is ``python -m pytest tests/release/test_feature_flags.py -q``
from ``apps/api``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit_event import AuditEvent
from app.models.feature_flag import FeatureFlag
from app.services.feature_flags import (
    KNOWN_FLAGS,
    SecurityFlagError,
    get_all_flags,
    is_enabled,
    is_security_sensitive_flag,
    seed_defaults,
    set_flag,
)

FLAG_UPDATED_ACTION = "feature_flag.updated"
AUDIT_FLAG = "release.tc16006.row"
DENIED_FLAG = "release.tc16006.denied"
ENV_FLAG = "connectors.aws"
ENV_VAR = "FEATURE_CONNECTORS_AWS"


def _login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def _login_admin(client: TestClient) -> int:
    from app.core.database import SessionLocal
    from app.models import User, WorkspaceMember

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@trust.local").one()
        mem = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == 1)
            .one()
        )
        if mem.role != "admin":
            mem.role = "admin"
            db.commit()
        user_id = user.id
    finally:
        db.close()
    _login(client, "demo@trust.local", "j")
    return user_id


def _delete_flag(flag_name: str, workspace_id: int = 1) -> None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        db.query(FeatureFlag).filter(
            FeatureFlag.workspace_id == workspace_id,
            FeatureFlag.flag_name == flag_name,
        ).delete()
        db.commit()
    finally:
        db.close()


def _latest_audit_id() -> int:
    from sqlalchemy import func

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return int(db.query(func.max(AuditEvent.id)).scalar() or 0)
    finally:
        db.close()


def _events(flag_name: str, after_id: int) -> list[dict]:
    """Audit rows for ``flag_name`` with id greater than ``after_id``.

    Fields are copied out before the session closes. Earlier tests leave rows
    behind; the high-water mark keeps each test to its own writes.
    """
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        rows = (
            db.query(AuditEvent)
            .filter(AuditEvent.action == FLAG_UPDATED_ACTION, AuditEvent.id > after_id)
            .order_by(AuditEvent.id.asc())
            .all()
        )
        matched: list[dict] = []
        for row in rows:
            details = json.loads(row.details) if row.details else {}
            if details.get("flag_name") != flag_name:
                continue
            matched.append(
                {
                    "user_id": row.user_id,
                    "email": row.email,
                    "workspace_id": row.workspace_id,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "details": details,
                }
            )
        return matched
    finally:
        db.close()


def _one(flags: list[dict], flag_name: str) -> dict:
    return next(item for item in flags if item["flag_name"] == flag_name)


def test_flag_change_writes_audit_with_actor_old_and_new(client: TestClient) -> None:
    _delete_flag(AUDIT_FLAG)
    actor_id = _login_admin(client)

    mark = _latest_audit_id()
    created = client.patch("/api/feature-flags", json={"flag_name": AUDIT_FLAG, "enabled": False})
    assert created.status_code == 200, created.text
    updated = client.patch("/api/feature-flags", json={"flag_name": AUDIT_FLAG, "enabled": True})
    assert updated.status_code == 200, updated.text
    assert updated.json()["enabled"] is True

    events = _events(AUDIT_FLAG, mark)
    assert len(events) == 2
    first, second = events
    assert first["user_id"] == actor_id
    assert first["email"] == "demo@trust.local"
    assert first["workspace_id"] == 1
    assert first["resource_type"] == "feature_flag"
    assert first["resource_id"] == AUDIT_FLAG
    assert first["details"]["old_enabled"] is None
    assert first["details"]["new_enabled"] is False
    assert first["details"]["changed"] is True

    assert second["user_id"] == actor_id
    assert second["email"] == "demo@trust.local"
    assert second["workspace_id"] == 1
    assert second["resource_type"] == "feature_flag"
    assert second["resource_id"] == AUDIT_FLAG
    assert second["details"]["flag_name"] == AUDIT_FLAG
    assert second["details"]["old_enabled"] is False
    assert second["details"]["new_enabled"] is True
    assert second["details"]["changed"] is True


def test_noop_flag_set_still_writes_one_audit(client: TestClient) -> None:
    """A repeat of the stored value is still one audit, and the row is not rewritten."""
    _delete_flag(AUDIT_FLAG)
    actor_id = _login_admin(client)
    mark = _latest_audit_id()
    first = client.patch("/api/feature-flags", json={"flag_name": AUDIT_FLAG, "enabled": True})
    assert first.status_code == 200, first.text
    again = client.patch("/api/feature-flags", json={"flag_name": AUDIT_FLAG, "enabled": True})
    assert again.status_code == 200, again.text
    assert again.json()["enabled"] is True

    events = _events(AUDIT_FLAG, mark)
    assert len(events) == 2
    assert events[1]["user_id"] == actor_id
    assert events[1]["details"]["old_enabled"] is True
    assert events[1]["details"]["new_enabled"] is True
    assert events[1]["details"]["changed"] is False

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        rows = (
            db.query(FeatureFlag)
            .filter(FeatureFlag.workspace_id == 1, FeatureFlag.flag_name == AUDIT_FLAG)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].enabled is True
    finally:
        db.close()


def test_non_admin_cannot_change_a_flag_and_writes_no_audit(client: TestClient) -> None:
    _delete_flag(DENIED_FLAG)
    _login(client, "reviewer@trust.local", "r")
    mark = _latest_audit_id()
    response = client.patch("/api/feature-flags", json={"flag_name": DENIED_FLAG, "enabled": True})
    assert response.status_code == 403
    assert _events(DENIED_FLAG, mark) == []

    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        row = (
            db.query(FeatureFlag)
            .filter(FeatureFlag.workspace_id == 1, FeatureFlag.flag_name == DENIED_FLAG)
            .first()
        )
        assert row is None
    finally:
        db.close()


def test_rejected_flag_name_writes_no_audit(client: TestClient) -> None:
    _login_admin(client)
    mark = _latest_audit_id()
    response = client.patch("/api/feature-flags", json={"flag_name": " ", "enabled": True})
    assert response.status_code == 400
    assert _events("", mark) == []


def test_set_flag_commits_the_row_and_the_audit_together(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    """One commit covers the row and the audit. A second commit is the members.py pattern."""
    _delete_flag(AUDIT_FLAG)
    db_session.expire_all()
    calls = {"n": 0}
    real_commit = db_session.commit

    def _commit() -> None:
        calls["n"] += 1
        real_commit()

    monkeypatch.setattr(db_session, "commit", _commit)
    mark = _latest_audit_id()
    set_flag(db_session, 1, AUDIT_FLAG, True, actor_user_id=7, actor_email="actor@trust.test")
    assert calls["n"] == 1
    events = _events(AUDIT_FLAG, mark)
    assert len(events) == 1
    assert events[0]["user_id"] == 7
    assert events[0]["email"] == "actor@trust.test"
    assert events[0]["details"]["old_enabled"] is None
    assert events[0]["details"]["new_enabled"] is True
    assert is_enabled(db_session, 1, AUDIT_FLAG) is True


@pytest.mark.parametrize("app_env", ["production", " Production ", "PRODUCTION"])
def test_production_env_does_not_override_an_existing_row(
    client: TestClient, db_session: Session, monkeypatch, app_env: str
) -> None:
    _delete_flag(ENV_FLAG)
    db_session.expire_all()
    set_flag(db_session, 1, ENV_FLAG, False)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv(ENV_VAR, "1")
    get_settings.cache_clear()
    assert is_enabled(db_session, 1, ENV_FLAG) is False
    resolved = _one(get_all_flags(db_session, 1), ENV_FLAG)
    assert resolved["enabled"] is False
    assert resolved["source"] == "workspace"


def test_production_env_is_the_default_when_no_row_exists(
    client: TestClient, db_session: Session, monkeypatch
) -> None:
    _delete_flag(ENV_FLAG)
    _delete_flag("connectors.slack")
    db_session.expire_all()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(ENV_VAR, "1")
    monkeypatch.setenv("FEATURE_CONNECTORS_SLACK", "0")
    get_settings.cache_clear()

    assert is_enabled(db_session, 1, ENV_FLAG) is True
    aws = _one(get_all_flags(db_session, 1), ENV_FLAG)
    assert aws["enabled"] is True
    assert aws["source"] == "env"

    # connectors.slack defaults to enabled. The env var replaces that default.
    assert is_enabled(db_session, 1, "connectors.slack") is False
    slack = _one(get_all_flags(db_session, 1), "connectors.slack")
    assert slack["enabled"] is False
    assert slack["source"] == "env"


@pytest.mark.parametrize("app_env", ["development", "test", "staging"])
def test_outside_production_env_overrides_the_stored_row(
    client: TestClient, db_session: Session, monkeypatch, app_env: str
) -> None:
    _delete_flag(ENV_FLAG)
    db_session.expire_all()
    set_flag(db_session, 1, ENV_FLAG, False)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv(ENV_VAR, "1")
    get_settings.cache_clear()
    assert is_enabled(db_session, 1, ENV_FLAG) is True
    resolved = _one(get_all_flags(db_session, 1), ENV_FLAG)
    assert resolved["enabled"] is True
    assert resolved["source"] == "env"


# --- Gap 2: flags do not gate security, and advertised flags default on --------

REPO_ROOT = Path(__file__).resolve().parents[4]

# Maintained denylist. A flag lookup in any of these files fails the build.
# main.py is included because CSRFMiddleware and GlobalRateLimitMiddleware live there.
# The feature-flag router mount in that file is not a lookup; the scanner ignores it.
SECURITY_MODULES = (
    "apps/api/app/core/csrf.py",
    "apps/api/app/core/session.py",
    "apps/api/app/core/auth_deps.py",
    "apps/api/app/core/audit.py",
    "apps/api/app/core/roles.py",
    "apps/api/app/core/mfa.py",
    "apps/api/app/core/password.py",
    "apps/api/app/core/keys.py",
    "apps/api/app/core/rate_limit.py",
    "apps/api/app/core/compliance_rate_limit.py",
    "apps/api/app/core/workspace.py",
    "apps/api/app/core/workspace_refs.py",
    "apps/api/app/services/workspace_integrity.py",
    "apps/api/app/services/cross_workspace_audit.py",
    "apps/api/app/services/oauth_service.py",
    "apps/api/app/services/sso_service.py",
    "apps/api/app/api/routes/auth.py",
    "apps/api/app/api/routes/audit.py",
    "apps/api/app/main.py",
    "apps/web/middleware.ts",
    "apps/web/contexts/AuthContext.tsx",
    "apps/web/components/layout/MfaRequiredBanner.tsx",
)

_LOOKUP_RES = (
    ("is_enabled(", re.compile(r"\bis_enabled\s*\(")),
    ("get_all_flags(", re.compile(r"\bget_all_flags\s*\(")),
    ("set_flag(", re.compile(r"\bset_flag\s*\(")),
    ("KNOWN_FLAGS", re.compile(r"\bKNOWN_FLAGS\b")),
    ("ff_service", re.compile(r"\bff_service\b")),
    ("app.services.feature_flags", re.compile(r"app\.services\.feature_flags")),
    ("services import feature_flags", re.compile(r"services\s+import\s+feature_flags")),
    ("/feature-flags", re.compile(r"/feature-flags")),
    ("FEATURE_", re.compile(r"\bFEATURE_[A-Z0-9_]+\b")),
)

# Public home and pricing pages advertise this sentence. There is no separate
# pricing JSON. These two flags are that sentence. They must default on.
ADVERTISED_PHRASE = "Gmail and Slack evidence ingestion"
ADVERTISED_PAGES = (
    "apps/web/app/page.tsx",
    "apps/web/app/pricing/page.tsx",
)
ROLE_AUDIT_PHRASE = "Role-based access and audit logging"
PRICING_PAGE = "apps/web/app/pricing/page.tsx"
ADVERTISED_FLAGS = frozenset({"connectors.gmail", "connectors.slack"})
# Every other registered flag. A new KNOWN_FLAGS key fails until it is added
# here or to ADVERTISED_FLAGS. Default-off is allowed only in this set.
NOT_ADVERTISED_FLAGS = frozenset(
    {
        "connectors.aws",
        "connectors.github",
        "connectors.gcp",
        "connectors.azure",
        "monitoring.continuous",
        "monitoring.alerts",
        "trust_center.auto_publish",
        "trust_center.nda_gating",
        "trust_center.analytics",
        "answers.memory",
        "answers.confidence_routing",
        "answers.llm_rerank",
        "credits.enforce",
        "exports.branded_cover",
        "beta.deal_rooms",
        "beta.promise_engine",
        "beta.remediation",
    }
)

SECURITY_FLAG_NAMES = (
    "csrf",
    "csrf.enforce",
    "CSRF.Enforce",
    " csrf ",
    "session.cookie",
    "audit.write",
    "permissions.admin",
    "mfa.required",
    "rate_limit.login",
    "rate-limit.login",
    "tenant.isolation",
    "auth_bypass",
)

_INJECTED_LOOKUPS = (
    "if not is_enabled(db, 1, 'csrf.enforce'):\n    return\n",
    "from app.services.feature_flags import is_enabled\n",
    "enabled = ff_service.is_enabled(db, workspace_id, 'audit')\n",
    "flags = get_all_flags(db, workspace_id)\n",
    "set_flag(db, 1, 'csrf', False)\n",
    "return KNOWN_FLAGS['connectors.slack']\n",
    "if os.getenv('FEATURE_CONNECTORS_SLACK') == '0':\n    return\n",
    "client.get('/api/feature-flags')\n",
    'quote = "connectors.gmail"\n',
)


def flag_lookups(rel: str, text: str, flag_names: set[str]) -> list[str]:
    """Return ``path:line`` hits for a feature-flag lookup in ``text``."""
    quoted = [(name, re.compile(rf"""(['"]){re.escape(name)}\1""")) for name in sorted(flag_names)]
    findings: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        reasons: list[str] = []
        for label, pattern in _LOOKUP_RES:
            if pattern.search(line):
                reasons.append(label)
        for name, pattern in quoted:
            if pattern.search(line):
                reasons.append(f"flag {name}")
        if reasons:
            snippet = line.strip()
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            findings.append(f"{rel}:{lineno}: {', '.join(reasons)}: {snippet}")
    return findings


def _update_count(after_id: int) -> int:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return (
            db.query(AuditEvent)
            .filter(AuditEvent.action == FLAG_UPDATED_ACTION, AuditEvent.id > after_id)
            .count()
        )
    finally:
        db.close()


def _flag_row(flag_name: str, workspace_id: int = 1) -> FeatureFlag | None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return (
            db.query(FeatureFlag)
            .filter(FeatureFlag.workspace_id == workspace_id, FeatureFlag.flag_name == flag_name)
            .first()
        )
    finally:
        db.close()


def test_known_flags_are_not_security_controls() -> None:
    bad = sorted(name for name in KNOWN_FLAGS if is_security_sensitive_flag(name))
    assert bad == []


def test_advertised_flags_default_on() -> None:
    """Home and pricing advertise Gmail and Slack. Those flags default on.

    Role-based access and audit logging are advertised and are not flags.
    There is no pricing JSON; the two pages are the manifest. Other registered
    flags are classified in NOT_ADVERTISED_FLAGS, including ones that default
    off, so a new flag fails until it is classified.
    """
    assert ADVERTISED_FLAGS.isdisjoint(NOT_ADVERTISED_FLAGS)
    assert ADVERTISED_FLAGS | NOT_ADVERTISED_FLAGS == set(KNOWN_FLAGS)
    off = sorted(name for name in ADVERTISED_FLAGS if KNOWN_FLAGS[name][0] is not True)
    assert off == []
    for rel in ADVERTISED_PAGES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert ADVERTISED_PHRASE in text, rel
    pricing = (REPO_ROOT / PRICING_PAGE).read_text(encoding="utf-8")
    assert ROLE_AUDIT_PHRASE in pricing
    assert is_security_sensitive_flag("audit")
    assert is_security_sensitive_flag("permissions.admin")


def test_security_modules_do_not_look_up_flags() -> None:
    missing: list[str] = []
    findings: list[str] = []
    names = set(KNOWN_FLAGS)
    for rel in SECURITY_MODULES:
        path = REPO_ROOT / rel
        if not path.is_file():
            missing.append(rel)
            continue
        findings.extend(flag_lookups(rel, path.read_text(encoding="utf-8"), names))
    assert missing == []
    assert findings == []


def test_flag_lookup_scanner_rejects_an_injected_lookup() -> None:
    names = set(KNOWN_FLAGS)
    for snippet in _INJECTED_LOOKUPS:
        found = flag_lookups("apps/api/app/core/csrf.py", snippet, names)
        assert found, snippet


def test_flag_lookup_scanner_ignores_the_admin_router_mount() -> None:
    text = (
        "from app.api.routes import feature_flags as feature_flags_router\n"
        'app.include_router(feature_flags_router.router, prefix="/api")\n'
        "card.is_enabled = True\n"
    )
    assert flag_lookups("apps/api/app/main.py", text, set(KNOWN_FLAGS)) == []


@pytest.mark.parametrize("flag_name", SECURITY_FLAG_NAMES)
def test_admin_cannot_toggle_a_security_flag(client: TestClient, flag_name: str) -> None:
    normalized = flag_name.strip().lower()
    _delete_flag(normalized)
    _login_admin(client)
    mark = _latest_audit_id()
    response = client.patch("/api/feature-flags", json={"flag_name": flag_name, "enabled": False})
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "Security controls are not feature flags"
    assert _update_count(mark) == 0
    assert _flag_row(normalized) is None
    if " " not in flag_name:
        got = client.get(f"/api/feature-flags/{flag_name}")
        assert got.status_code == 400, got.text
        assert got.json()["detail"] == "Security controls are not feature flags"


def test_set_flag_and_is_enabled_refuse_a_security_flag(db_session: Session) -> None:
    _delete_flag("csrf.enforce")
    db_session.expire_all()
    with pytest.raises(SecurityFlagError, match="Security controls are not feature flags"):
        set_flag(db_session, 1, "csrf.enforce", False, actor_user_id=7, actor_email="a@trust.test")
    with pytest.raises(SecurityFlagError, match="Security controls are not feature flags"):
        is_enabled(db_session, 1, "session")
    assert _flag_row("csrf.enforce") is None
    assert _flag_row("session") is None


def test_seed_defaults_skips_a_security_name(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _delete_flag("csrf.enforce")
    db_session.expire_all()
    monkeypatch.setitem(KNOWN_FLAGS, "csrf.enforce", (True, "must not be seeded"))
    seed_defaults(db_session, 1)
    db_session.expire_all()
    assert _flag_row("csrf.enforce") is None
