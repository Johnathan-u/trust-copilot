"""TC-03-001 release gate: typed configuration contract and production fail-closed startup.

All credentials used here are generated at runtime (``secrets``); known-default inputs are read from
the contract denylist, docker-compose.yml and .env.example at test time, so no credential literal
lives in this file. Assertion messages identify inputs by variable name only, never by value.
"""

from __future__ import annotations

import ast
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from app.core import config_contract as cc

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]

PROD_REQUIRED = (
    "SESSION_SECRET",
    "DATABASE_URL",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_ENDPOINT",
    "APP_BASE_URL",
    "FRONTEND_URL",
    "OPENAI_API_KEY",
)


def _dsn(
    user: str,
    password: str | None,
    host: str = "postgres:5432/trustcopilot",
    scheme: str = "postgresql",
) -> str:
    """Build a connection URL from parts (keeps URL-with-credential literals out of the source)."""
    auth = user if password is None else user + ":" + password
    return scheme + "://" + auth + "@" + host


def _tok(n: int = 24) -> str:
    # Random tokens can, rarely, contain a placeholder marker (e.g. "todo" in any letter case); the
    # contract refuses those by design, so draw again instead of making the suite flaky.
    while True:
        t = secrets.token_urlsafe(n)
        if not cc.is_known_default_or_placeholder(t):
            return t


def good_production_env() -> dict[str, str]:
    db_user = "tc_" + secrets.token_hex(4)
    return {
        "APP_ENV": "production",
        "SESSION_SECRET": _tok(48),
        "DATABASE_URL": _dsn(db_user, _tok(24), "postgres:5432/trustcopilot", "postgresql"),
        "POSTGRES_USER": db_user,
        "POSTGRES_PASSWORD": _tok(24),
        "S3_ENDPOINT": "http://minio:9000",
        "S3_ACCESS_KEY": "ak" + secrets.token_hex(10),
        "S3_SECRET_KEY": _tok(30),
        "MINIO_ROOT_USER": "root" + secrets.token_hex(6),
        "MINIO_ROOT_PASSWORD": _tok(24),
        "APP_BASE_URL": "https://app.trust.test",
        "FRONTEND_URL": "https://app.trust.test",
        "TRUSTED_ORIGINS": "https://app.trust.test",
        "OPENAI_API_KEY": "sk-test-" + secrets.token_hex(16),
        "SMTP_HOST": "smtp.trust.test",
        "SMTP_FROM": "noreply@trust.test",
    }


def fatal(problems) -> list:
    return [p for p in problems if p.fatal]


def names(problems) -> set[str]:
    return {p.name for p in problems if p.fatal}


# ---------------------------------------------------------------- AC1: documented, typed contract


def _env_vars_read_by_code() -> set[str]:
    pat = re.compile(r"(?:getenv|environ\.get|environ\[)\(?\s*[\"']([A-Z][A-Z0-9_]{2,})[\"']")
    found: set[str] = set()
    for base in (API_ROOT / "app", API_ROOT / "alembic"):
        for f in base.rglob("*.py"):
            found.update(pat.findall(f.read_text(encoding="utf-8", errors="replace")))
    return found


def test_every_env_var_read_by_the_api_is_in_the_contract():
    missing = sorted(_env_vars_read_by_code() - set(cc.CONTRACT_BY_NAME))
    assert not missing, f"undocumented variables: {missing}"


def test_contract_entries_are_typed_and_classified():
    assert len(cc.CONTRACT_BY_NAME) == len(cc.CONTRACT), "duplicate contract entries"
    for v in cc.CONTRACT:
        assert v.type and v.description, v.name
        assert v.production in ("required", "forbidden", "optional", "conditional"), v.name
    for n in PROD_REQUIRED + ("APP_ENV",):
        assert cc.CONTRACT_BY_NAME[n].production == "required", n


def test_contract_doc_is_generated_from_code():
    doc = (REPO_ROOT / "docs/release/config-contract.md").read_text()
    m = re.search(
        r"<!-- BEGIN GENERATED CONFIG CONTRACT -->\n(.*?)<!-- END GENERATED CONFIG CONTRACT -->",
        doc,
        re.S,
    )
    assert m, "generated block missing"
    assert (
        m.group(1).strip() == cc.contract_markdown().strip()
    ), "regenerate with: python -m app.core.config_contract markdown"


def test_env_example_documents_production_requirements():
    text = (REPO_ROOT / ".env.example").read_text()
    for n in (
        "APP_ENV",
        "SESSION_SECRET",
        "DATABASE_URL",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "SMTP_HOST",
        "OPENAI_API_KEY",
    ):
        assert re.search(rf"^#?\s*{n}=", text, re.M), n
    assert "config-contract.md" in text


# ---------------------------------------------------------------- success path


def test_valid_generated_production_env_passes():
    env = good_production_env()
    assert cc.validate_environment(env) == []
    assert cc.enforce_startup_contract("api", env) == []


def test_non_production_tolerates_missing_settings():
    assert cc.enforce_startup_contract("api", {"APP_ENV": "development"}) == []
    assert cc.enforce_startup_contract("api", {}) == []


# ---------------------------------------------------------------- AC2: production fails closed


@pytest.mark.parametrize("name", PROD_REQUIRED)
@pytest.mark.parametrize("mode", ["unset", "empty"])
def test_required_variable_missing_fails_closed(name, mode):
    env = good_production_env()
    if mode == "unset":
        env.pop(name)
    else:
        env[name] = ""
    with pytest.raises(cc.ConfigContractError) as ei:
        cc.enforce_startup_contract("api", env)
    assert name in names(ei.value.problems)


DEFAULTS = sorted(cc.KNOWN_DEFAULT_CREDENTIALS)


@pytest.mark.parametrize("idx", range(len(DEFAULTS)))
@pytest.mark.parametrize(
    "name",
    [
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "POSTGRES_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "SESSION_SECRET",
    ],
)
def test_known_default_credentials_refused(name, idx):
    env = good_production_env()
    env[name] = DEFAULTS[idx]
    assert name in names(cc.validate_environment(env))


@pytest.mark.parametrize("idx", range(len(DEFAULTS)))
def test_minio_root_user_default_refused(idx):
    env = good_production_env()
    env["MINIO_ROOT_USER"] = DEFAULTS[idx]
    assert "MINIO_ROOT_USER" in names(cc.validate_environment(env))


@pytest.mark.parametrize("idx", range(len(DEFAULTS)))
def test_database_url_default_password_refused(idx):
    env = good_production_env()
    env["DATABASE_URL"] = _dsn(
        DEFAULTS[idx], DEFAULTS[idx], "postgres:5432/trustcopilot", "postgresql"
    )
    assert "DATABASE_URL" in names(cc.validate_environment(env))


@pytest.mark.parametrize(
    "variant", ["no_password", "short", "placeholder", "same_as_user", "not_postgres", "garbage"]
)
def test_database_url_shapes_refused(variant):
    env = good_production_env()
    user = "u" + secrets.token_hex(3)
    pw = {"short": secrets.token_hex(4), "placeholder": "placeholder-" + secrets.token_hex(8)}.get(
        variant, _tok(20)
    )
    env["DATABASE_URL"] = {
        "no_password": _dsn(user, None, "db:5432/x"),
        "same_as_user": _dsn(user * 4, user * 4, "db:5432/x", "postgresql"),
        "not_postgres": _dsn(user, pw, "db:3306/x", "mysql"),
        "garbage": "not a url",
    }.get(variant, _dsn(user, pw, "db:5432/x", "postgresql"))
    assert "DATABASE_URL" in names(cc.validate_environment(env))


@pytest.mark.parametrize("value_kind", ["short", "placeholder", "low_variety"])
@pytest.mark.parametrize(
    "name", ["SESSION_SECRET", "S3_SECRET_KEY", "POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD"]
)
def test_weak_secrets_refused(name, value_kind):
    env = good_production_env()
    env[name] = {
        "short": secrets.token_hex(5),
        "placeholder": "placeholder" + _tok(30),
        "low_variety": "ab" * 24,
    }[value_kind]
    assert name in names(cc.validate_environment(env))


def _dev_compose_defaults() -> dict[str, str]:
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    return dict(re.findall(r"\$\{([A-Z_]+):-([^}]*)\}", text))


def test_dev_compose_credential_defaults_are_refused_in_production():
    defaults = _dev_compose_defaults()
    for n in ("POSTGRES_USER", "POSTGRES_PASSWORD", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"):
        assert n in defaults, f"{n} missing from dev compose"
    for n in ("POSTGRES_PASSWORD", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"):
        env = good_production_env()
        env[n] = defaults[n]
        assert n in names(cc.validate_environment(env)), f"dev default for {n} accepted"
    # The dev DATABASE_URL credentials and the dev MinIO credentials used as S3 keys.
    env = good_production_env()
    env["DATABASE_URL"] = _dsn(
        defaults["POSTGRES_USER"],
        defaults["POSTGRES_PASSWORD"],
        "postgres:5432/trustcopilot",
        "postgresql",
    )
    env["S3_ACCESS_KEY"] = defaults["MINIO_ROOT_USER"]
    env["S3_SECRET_KEY"] = defaults["MINIO_ROOT_PASSWORD"]
    assert {"DATABASE_URL", "S3_ACCESS_KEY", "S3_SECRET_KEY"} <= names(cc.validate_environment(env))


def test_dev_compose_s3_keys_are_refused_in_production():
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    for n in ("S3_ACCESS_KEY", "S3_SECRET_KEY"):
        for raw in re.findall(rf"^\s*{n}:\s*(\S+)\s*$", text, re.M):
            m = re.fullmatch(r"\$\{([A-Z_]+)(?::-([^}]*))?\}", raw)
            value = _dev_compose_defaults().get(m.group(1), "") if m else raw.strip("\"'")
            env = good_production_env()
            env[n] = value
            assert n in names(cc.validate_environment(env)), f"dev compose {n} accepted"


def _env_example() -> dict[str, str]:
    out = {}
    for line in (REPO_ROOT / ".env.example").read_text().splitlines():
        m = re.match(r"^#?\s*([A-Z][A-Z0-9_]*)=(.*)$", line)
        if m:
            out.setdefault(m.group(1), m.group(2).split(" #")[0].strip())
    return out


@pytest.mark.parametrize(
    "name",
    [
        "SESSION_SECRET",
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "OPENAI_API_KEY",
        "OAUTH_GOOGLE_CLIENT_SECRET",
        "OIDC_CLIENT_SECRET",
    ],
)
def test_env_example_values_are_refused_in_production(name):
    ex = _env_example()
    assert name in ex, name
    env = good_production_env()
    env[name] = ex[name]
    if name.endswith("_CLIENT_SECRET"):
        env[name.replace("_SECRET", "_ID")] = "client-" + secrets.token_hex(6)
        env["OIDC_ISSUER_URL"] = "https://idp.trust.test"
    assert name in names(
        cc.validate_environment(env)
    ), f".env.example {name} accepted in production"


@pytest.mark.parametrize("url_name", ["APP_BASE_URL", "FRONTEND_URL"])
@pytest.mark.parametrize(
    "value", ["http://app.trust.test", "https://localhost:3000", "https://127.0.0.1"]
)
def test_public_urls_must_be_https_and_public(url_name, value):
    env = good_production_env()
    env[url_name] = value
    assert url_name in names(cc.validate_environment(env))


def test_trusted_origins_must_be_https():
    env = good_production_env()
    env["TRUSTED_ORIGINS"] = "https://app.trust.test,http://localhost:3000"
    assert "TRUSTED_ORIGINS" in names(cc.validate_environment(env))


@pytest.mark.parametrize("name", cc.FORBIDDEN_IN_PRODUCTION)
def test_dev_demo_seed_switches_refused_in_production(name):
    env = good_production_env()
    env[name] = "1" if cc.CONTRACT_BY_NAME[name].type == "bool" else _tok(12)
    with pytest.raises(cc.ConfigContractError) as ei:
        cc.enforce_startup_contract("api", env)
    assert name in names(ei.value.problems)


def test_forbidden_switches_cover_demo_and_seed():
    f = set(cc.FORBIDDEN_IN_PRODUCTION)
    assert {
        "NEXT_PUBLIC_DEMO_LOGIN_EMAIL",
        "NEXT_PUBLIC_DEMO_LOGIN_PASSWORD",
        "TC_ALLOW_PRODUCTION_SEED",
        "TC_SEED_ADMIN_PASSWORD",
        "TC_SEED_DEMO_PASSWORD",
        "TRUST_COPILOT_DEV_RETURN_RESET_URL",
    } <= f


@pytest.mark.parametrize("pair", ["OAUTH_GOOGLE", "OAUTH_GITHUB", "OAUTH_MICROSOFT", "IDME"])
def test_half_configured_identity_provider_refused(pair):
    env = good_production_env()
    env[f"{pair}_CLIENT_ID"] = "client-" + secrets.token_hex(6)
    assert f"{pair}_CLIENT_SECRET" in names(cc.validate_environment(env))


def test_stripe_requires_webhook_secret():
    env = good_production_env()
    env["STRIPE_SECRET_KEY"] = "sk_test_" + secrets.token_hex(12)
    assert "STRIPE_WEBHOOK_SECRET" in names(cc.validate_environment(env))


# ---------------------------------------------------------------- typing / env mode


@pytest.mark.parametrize("app_env", ["prod", "live", "qa", "dev"])
def test_unknown_app_env_refused_everywhere(app_env):
    with pytest.raises(cc.ConfigContractError):
        cc.enforce_startup_contract("api", {"APP_ENV": app_env})


@pytest.mark.parametrize(
    "name", ["MAX_UPLOAD_BYTES", "EXPORT_ANSWER_COL_OFFSET", "OIDC_DEFAULT_WORKSPACE_ID"]
)
def test_malformed_ints_fatal_even_in_development(name):
    with pytest.raises(cc.ConfigContractError):
        cc.enforce_startup_contract("api", {"APP_ENV": "development", name: "not-a-number"})


@pytest.mark.parametrize(
    "name,value",
    [
        ("RATE_LIMIT_RPM_PER_IP", "abc"),
        ("OPENAI_TEMPERATURE", "warm"),
        ("LOG_LEVEL", "LOUD"),
        ("MAX_UPLOAD_BYTES", "0"),
        ("SMTP_PORT", "x"),
    ],
)
def test_malformed_types_warn_in_dev_and_fail_in_production(name, value):
    dev = (
        cc.enforce_startup_contract("api", {"APP_ENV": "development", name: value})
        if name != "MAX_UPLOAD_BYTES"
        else None
    )
    if dev is not None:
        assert name in {p.name for p in dev}
    env = good_production_env()
    env[name] = value
    assert name in names(cc.validate_environment(env))


# ---------------------------------------------------------------- no values in errors


def test_errors_never_contain_values():
    env = good_production_env()
    leaked = {
        "SESSION_SECRET": "placeholder" + _tok(10),
        "S3_SECRET_KEY": secrets.token_hex(4),
        "POSTGRES_PASSWORD": "changeme" + secrets.token_hex(3),
        "TC_SEED_ADMIN_PASSWORD": _tok(12),
        "NEXT_PUBLIC_DEMO_LOGIN_PASSWORD": _tok(12),
    }
    db_pw = secrets.token_hex(4)
    env.update(leaked)
    env["DATABASE_URL"] = _dsn("someuser", db_pw, "db:5432/x")
    with pytest.raises(cc.ConfigContractError) as ei:
        cc.enforce_startup_contract("api", env)
    text = str(ei.value) + repr(ei.value.problems)
    for n, v in list(leaked.items()) + [("DATABASE_URL", db_pw)]:
        assert v not in text, f"value of {n} leaked into the error"


def test_cli_check_exit_codes_and_no_values():
    bad = good_production_env()
    weak = "changeme" + secrets.token_hex(2)
    bad["S3_SECRET_KEY"] = weak
    base = {
        k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "SYSTEMROOT", "PYTHONPATH")
    }
    r = subprocess.run(
        [sys.executable, "-m", "app.core.config_contract", "check"],
        cwd=API_ROOT,
        env={**base, **bad},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 2 and "S3_SECRET_KEY" in r.stderr
    assert weak not in r.stdout + r.stderr
    r = subprocess.run(
        [sys.executable, "-m", "app.core.config_contract", "check"],
        cwd=API_ROOT,
        env={**base, **good_production_env()},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- startup wiring


def _apply_env(monkeypatch, env: dict[str, str]):
    for v in cc.CONTRACT:
        monkeypatch.delenv(v.name, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from app.core.config import get_settings

    get_settings.cache_clear()


def test_api_lifespan_refuses_before_touching_db(monkeypatch):
    import asyncio
    import app.main as main_mod

    env = good_production_env()
    env["S3_SECRET_KEY"] = "minioadmin"
    _apply_env(monkeypatch, env)
    called = []
    monkeypatch.setattr(main_mod, "_verify_db_connectivity", lambda: called.append(1))

    async def run():
        async with main_mod.lifespan(main_mod.app):
            pass

    try:
        with pytest.raises(cc.ConfigContractError):
            asyncio.run(run())
    finally:
        from app.core.config import get_settings

        get_settings.cache_clear()
    assert not called, "database contacted before the config contract was enforced"


def test_worker_main_refuses_before_polling(monkeypatch):
    import app.worker as worker

    env = good_production_env()
    env.pop("DATABASE_URL")
    _apply_env(monkeypatch, env)
    monkeypatch.setattr(worker, "SessionFactory", lambda: pytest.fail("worker touched the DB"))
    try:
        with pytest.raises(cc.ConfigContractError):
            worker.main()
    finally:
        from app.core.config import get_settings

        get_settings.cache_clear()


def test_alembic_env_and_entrypoint_enforce_contract():
    alembic_env = (API_ROOT / "alembic/env.py").read_text()
    assert 'enforce_startup_contract("migrations")' in alembic_env
    assert alembic_env.index("enforce_startup_contract(") < alembic_env.index(
        "def run_migrations_online"
    )
    ep = (API_ROOT / "docker-entrypoint.sh").read_text()
    assert "set -e" in ep
    assert (
        0 <= ep.index("python -m app.core.config_contract check") < ep.index("alembic upgrade head")
    )


def test_prod_compose_runs_api_and_worker_in_production_mode():
    text = (REPO_ROOT / "docker-compose.prod.yml").read_text()
    for svc in ("api", "worker"):
        block = re.search(rf"^  {svc}:\n(.*?)(?=^  \w)", text, re.S | re.M).group(1)
        assert re.search(
            r"^\s+APP_ENV:\s*production\b", block, re.M
        ), f"{svc} lacks APP_ENV=production"
        assert ".env.production" in block


def test_web_production_image_disables_demo_login():
    df = (REPO_ROOT / "apps/web/Dockerfile").read_text()
    builder = df.split("FROM node:20 AS production")[0]
    for n in ("NEXT_PUBLIC_DEMO_LOGIN_EMAIL", "NEXT_PUBLIC_DEMO_LOGIN_PASSWORD"):
        assert re.search(rf'{n}=""', builder), n
    assert builder.index("NEXT_PUBLIC_DEMO_LOGIN_EMAIL") < builder.index("npm run build")


def test_dockerignore_excludes_env_and_credential_files():
    lines = set((REPO_ROOT / ".dockerignore").read_text().split())
    assert {"**/.env", "**/.env.*", "**/.seed-credentials.local"} <= lines


# ---------------------------------------------------------------- demo auto-seeding


def test_demo_seed_refused_in_production_without_override(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TC_ALLOW_PRODUCTION_SEED", "1")  # former override must no longer work
    with pytest.raises(SystemExit):
        cc.refuse_demo_seed_in_production()
    sys.path.insert(0, str(API_ROOT))
    try:
        from scripts import _seed_credentials

        with pytest.raises(SystemExit):
            _seed_credentials.refuse_production_seed()
    finally:
        sys.path.remove(str(API_ROOT))


def test_demo_seed_allowed_outside_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    cc.refuse_demo_seed_in_production()


@pytest.mark.parametrize("script", sorted(p.name for p in (API_ROOT / "scripts").glob("seed_*.py")))
def test_every_seed_script_guards_production(script):
    tree = ast.parse((API_ROOT / "scripts" / script).read_text())
    calls = {
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert calls & {
        "refuse_production_seed",
        "refuse_demo_seed_in_production",
    }, f"{script} lacks the production guard"


def test_api_startup_does_not_seed_accounts():
    src = (API_ROOT / "app/main.py").read_text()
    for forbidden in ("seed_demo", "seed_admin", "seed_qa", "TC_SEED_"):
        assert forbidden not in src


def test_app_env_is_case_and_space_insensitive_for_production():
    env = good_production_env()
    env["APP_ENV"] = " Production "
    env.pop("SESSION_SECRET")
    with pytest.raises(cc.ConfigContractError):
        cc.enforce_startup_contract("api", env)


# ---------------------------------------------------------------- email delivery is conditional (Coordinator ruling)


def _prod_without_smtp() -> dict:
    env = good_production_env()
    for n in ("SMTP_HOST", "SMTP_FROM", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_DELIVERY_ENABLED"):
        env.pop(n, None)
    return env


@pytest.mark.parametrize("flag", [None, "", "false", "0", "no", "off", "FALSE"])
def test_production_boots_with_email_disabled_and_no_smtp(flag):
    """Slack-only / no-notification production deploys must boot."""
    env = _prod_without_smtp()
    if flag is not None:
        env["EMAIL_DELIVERY_ENABLED"] = flag
    assert cc.email_delivery_enabled(env) is False
    assert fatal(cc.validate_environment(env)) == []
    cc.enforce_startup_contract("api", env)  # does not raise


@pytest.mark.parametrize("flag", ["true", "1", "yes", "on", "TRUE"])
@pytest.mark.parametrize("missing", [("SMTP_HOST",), ("SMTP_FROM",), ("SMTP_HOST", "SMTP_FROM")])
def test_production_email_enabled_without_smtp_fails_closed(flag, missing):
    env = good_production_env()
    env["EMAIL_DELIVERY_ENABLED"] = flag
    for n in missing:
        env.pop(n)
    with pytest.raises(cc.ConfigContractError) as ei:
        cc.enforce_startup_contract("api", env)
    for n in missing:
        assert n in str(ei.value)


@pytest.mark.parametrize("value", ["", "   "])
def test_production_email_enabled_with_empty_smtp_fails_closed(value):
    env = good_production_env()
    env["EMAIL_DELIVERY_ENABLED"] = "true"
    env["SMTP_HOST"] = value
    assert "SMTP_HOST" in names(cc.validate_environment(env))


def test_production_email_enabled_with_valid_smtp_passes():
    env = good_production_env()
    env["EMAIL_DELIVERY_ENABLED"] = "true"
    assert cc.email_delivery_enabled(env) is True
    assert fatal(cc.validate_environment(env)) == []
    cc.enforce_startup_contract("api", env)


def test_production_smtp_host_without_flag_implies_email_enabled_and_needs_from():
    """Unset flag keeps the pre-existing signal (SMTP_HOST set => email on), so SMTP_FROM is then required."""
    env = good_production_env()
    env.pop("EMAIL_DELIVERY_ENABLED", None)
    env.pop("SMTP_FROM")
    assert cc.email_delivery_enabled(env) is True
    assert "SMTP_FROM" in names(cc.validate_environment(env))


def test_invalid_email_flag_fails_closed_in_production():
    env = _prod_without_smtp()
    env["EMAIL_DELIVERY_ENABLED"] = "maybe"
    assert cc.email_delivery_enabled(env) is True  # unparseable counts as enabled
    found = names(cc.validate_environment(env))
    assert {"EMAIL_DELIVERY_ENABLED", "SMTP_HOST", "SMTP_FROM"} <= found


def test_invalid_email_flag_is_only_a_warning_in_development():
    problems = cc.enforce_startup_contract(
        "api", {"APP_ENV": "development", "EMAIL_DELIVERY_ENABLED": "maybe"}
    )
    assert "EMAIL_DELIVERY_ENABLED" in {p.name for p in problems}


def test_email_flag_documented_in_contract_and_docs():
    by = {v.name: v for v in cc.CONTRACT}
    assert by["EMAIL_DELIVERY_ENABLED"].type == "bool"
    assert (
        by["SMTP_HOST"].production == "conditional" and by["SMTP_FROM"].production == "conditional"
    )
    doc = (REPO_ROOT / "docs/release/config-contract.md").read_text()
    assert "EMAIL_DELIVERY_ENABLED" in doc
    assert re.search(
        r"^#?\s*EMAIL_DELIVERY_ENABLED=", (REPO_ROOT / ".env.example").read_text(), re.M
    )


def _fresh_provider(monkeypatch, env: dict):
    from app.services import email_service as es

    for n in (
        "APP_ENV",
        "SMTP_HOST",
        "SMTP_FROM",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "EMAIL_DELIVERY_ENABLED",
    ):
        monkeypatch.delenv(n, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    es.set_email_provider(None)
    try:
        return es, es.get_email_provider()
    finally:
        es.set_email_provider(None)


def test_production_email_disabled_never_prints_message(monkeypatch, capsys):
    es, provider = _fresh_provider(
        monkeypatch, {"APP_ENV": "production", "EMAIL_DELIVERY_ENABLED": "false"}
    )
    assert isinstance(provider, es.DisabledEmailProvider)
    marker = "https://app.trust.test/reset?token=" + secrets.token_urlsafe(24)
    to = "user-" + secrets.token_hex(4) + "@trust.test"
    assert provider.send(es.EmailMessage(to=to, subject="Reset", body_text=marker)) is False
    out = capsys.readouterr().out
    assert marker not in out and to not in out


def test_production_without_smtp_host_never_uses_console(monkeypatch):
    es, provider = _fresh_provider(monkeypatch, {"APP_ENV": "production"})
    assert not isinstance(provider, es.ConsoleEmailProvider)


def test_production_email_enabled_uses_smtp(monkeypatch):
    es, provider = _fresh_provider(
        monkeypatch,
        {
            "APP_ENV": "production",
            "EMAIL_DELIVERY_ENABLED": "true",
            "SMTP_HOST": "smtp.trust.test",
            "SMTP_FROM": "noreply@trust.test",
        },
    )
    assert isinstance(provider, es.SmtpEmailProvider)


def test_development_keeps_console_provider(monkeypatch):
    es, provider = _fresh_provider(monkeypatch, {"APP_ENV": "development"})
    assert isinstance(provider, es.ConsoleEmailProvider)


def test_production_smtp_failure_does_not_print_body(monkeypatch, capsys):
    from app.services import email_service as es

    monkeypatch.setenv("APP_ENV", "production")

    class Boom:
        def __init__(self, *a, **k):
            raise OSError("unreachable (synthetic)")

    monkeypatch.setattr(es.smtplib, "SMTP", Boom)
    p = es.SmtpEmailProvider("smtp.trust.test", 587, None, None, "noreply@trust.test")
    marker = "https://app.trust.test/reset?token=" + secrets.token_urlsafe(24)
    assert p.send(es.EmailMessage(to="x@trust.test", subject="Reset", body_text=marker)) is False
    assert marker not in capsys.readouterr().out


# ---------------------------------------------------------------- .env.example credentials vs production
# (Coordinator: production must refuse every credential .env.example ships, including the dev MinIO S3
# pair, and must use master's is_production_env() as the only production detector.) Values are read from
# .env.example at test time; nothing here contains a credential literal.

_PRODUCTION_SPELLINGS = [
    "production",
    " production ",
    "PRODUCTION",
    "production\n",
    "\tProduction ",
]
_NON_PRODUCTION = ["development", " Development ", "test", "staging", ""]
_REASON_PHRASES = ("known default or placeholder", "is a placeholder")


def _shipped_credentials() -> dict[str, str]:
    """Every secret-classified variable with a non-empty value in .env.example (commented or not)."""
    return {
        n: v
        for n, v in _env_example().items()
        if v and n in cc.CONTRACT_BY_NAME and cc.CONTRACT_BY_NAME[n].secret
    }


def _with_partners(env: dict[str, str], name: str) -> dict[str, str]:
    """Complete id/secret pairs with synthetic ids so the shipped secret itself is what is judged."""
    for cid, csec in cc._OAUTH_PAIRS:
        if name == csec:
            env[cid] = "client-" + secrets.token_hex(6)
            env.setdefault("OIDC_ISSUER_URL", "https://idp.trust.test")
    return env


def _scrubbed(text: str) -> str:
    for phrase in _REASON_PHRASES:
        text = text.replace(phrase, "")
    return text


def test_env_example_ships_the_expected_credential_set():
    shipped = _shipped_credentials()
    # Drift guard: these are the defaults the Coordinator named; new ones are picked up automatically.
    assert {
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
        "OPENAI_API_KEY",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
    } <= set(shipped)
    ex = _env_example()
    assert "SESSION_SECRET" in ex and not ex["SESSION_SECRET"], "SESSION_SECRET must ship empty"


@pytest.mark.parametrize("name", sorted(_shipped_credentials()))
@pytest.mark.parametrize("app_env", _PRODUCTION_SPELLINGS)
def test_every_env_example_credential_is_refused_in_production(name, app_env):
    value = _shipped_credentials()[name]
    env = _with_partners(good_production_env(), name)
    env["APP_ENV"] = app_env
    env[name] = value
    with pytest.raises(cc.ConfigContractError) as ei:
        cc.enforce_startup_contract("api", env)
    assert name in {p.name for p in ei.value.problems}, f".env.example {name} accepted"
    text = _scrubbed(str(ei.value) + repr(ei.value.problems))
    assert value not in text, f"value of {name} echoed in the error"


def test_env_example_minio_s3_pair_and_db_password_are_refused_together():
    ex = _env_example()
    env = good_production_env()
    for n in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "POSTGRES_PASSWORD", "DATABASE_URL"):
        env[n] = ex[n]
    with pytest.raises(cc.ConfigContractError) as ei:
        cc.enforce_startup_contract("worker", env)
    assert {"S3_ACCESS_KEY", "S3_SECRET_KEY", "POSTGRES_PASSWORD", "DATABASE_URL"} <= {
        p.name for p in ei.value.problems
    }
    text = _scrubbed(str(ei.value))
    db_password = re.match(r"^[a-z+]+://[^:@/]+:([^@]+)@", ex["DATABASE_URL"]).group(1)
    for v in (ex["S3_ACCESS_KEY"], ex["S3_SECRET_KEY"], ex["POSTGRES_PASSWORD"], db_password):
        assert v not in text


@pytest.mark.parametrize(
    "name", ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_WEBHOOK_SECRETS"]
)
def test_stripe_placeholders_are_refused_and_generated_values_pass(name):
    env = good_production_env()
    env["STRIPE_SECRET_KEY"] = "sk_test_" + secrets.token_hex(12)
    env["STRIPE_WEBHOOK_SECRET"] = "whsec_" + secrets.token_hex(12)
    assert not fatal(cc.validate_environment(env))
    env[name] = "placeholder"
    assert name in names(cc.validate_environment(env))
    if name == "STRIPE_WEBHOOK_SECRETS":  # every comma item is checked
        env[name] = "whsec_" + secrets.token_hex(12) + ",placeholder"
        assert name in names(cc.validate_environment(env))


def test_stripe_webhook_secrets_alone_satisfy_the_pairing_rule():
    env = good_production_env()
    env["STRIPE_SECRET_KEY"] = "sk_test_" + secrets.token_hex(12)
    env["STRIPE_WEBHOOK_SECRETS"] = "whsec_" + secrets.token_hex(12)
    assert not fatal(cc.validate_environment(env))


@pytest.mark.parametrize("app_env", _PRODUCTION_SPELLINGS)
def test_generated_non_default_credentials_pass_in_production(app_env):
    env = good_production_env()
    env["APP_ENV"] = app_env
    assert cc.enforce_startup_contract("api", env) == []


@pytest.mark.parametrize("app_env", _NON_PRODUCTION)
def test_env_example_defaults_are_allowed_outside_production(app_env):
    """Dev/test keep working with every value .env.example ships (commented ones uncommented too)."""
    env = dict(_env_example())
    env["APP_ENV"] = app_env
    problems = cc.enforce_startup_contract("api", env)  # must not raise
    assert not (names(fatal(problems)) & set(_shipped_credentials()))
    cc.refuse_demo_seed_in_production(env)  # seeding stays available outside production


@pytest.mark.parametrize("app_env", _PRODUCTION_SPELLINGS)
def test_production_detection_is_master_is_production_env(app_env):
    from app.core.session import is_production_env

    env = good_production_env()
    env["APP_ENV"] = app_env
    assert is_production_env(env)
    with pytest.raises(SystemExit):
        cc.refuse_demo_seed_in_production(env)


def test_config_contract_has_no_second_production_detector(monkeypatch):
    src = (API_ROOT / "app/core/config_contract.py").read_text()
    assert "is_production_env" in src
    assert not re.search(r"""==\s*["']production["']""", src), "own APP_ENV comparison"
    # Behavioural proof: the contract follows whatever is_production_env decides.
    ex = _env_example()
    env = good_production_env()
    env["S3_ACCESS_KEY"], env["S3_SECRET_KEY"] = ex["S3_ACCESS_KEY"], ex["S3_SECRET_KEY"]
    monkeypatch.setattr(cc, "is_production_env", lambda env=None: False)
    assert not fatal(cc.validate_environment(env))
    cc.enforce_startup_contract("api", env)
    monkeypatch.setattr(cc, "is_production_env", lambda env=None: True)
    env["APP_ENV"] = "development"
    assert {"S3_ACCESS_KEY", "S3_SECRET_KEY"} <= names(cc.validate_environment(env))


@pytest.mark.parametrize("app_env", _PRODUCTION_SPELLINGS)
def test_process_env_spellings_refuse_env_example_s3_defaults(monkeypatch, app_env):
    """Real startup path (os.environ + Settings): same detector as the SESSION_SECRET gate."""
    from app.core.config import get_settings
    from app.core.session import enforce_production_session_secret, is_production_env

    ex = _env_example()
    env = good_production_env()
    env["APP_ENV"] = app_env
    env["S3_ACCESS_KEY"], env["S3_SECRET_KEY"] = ex["S3_ACCESS_KEY"], ex["S3_SECRET_KEY"]
    _apply_env(monkeypatch, env)
    try:
        assert is_production_env()
        enforce_production_session_secret("api")  # master's gate passes (strong generated secret)
        with pytest.raises(cc.ConfigContractError) as ei:
            cc.enforce_startup_contract("api")
        assert {"S3_ACCESS_KEY", "S3_SECRET_KEY"} <= {p.name for p in ei.value.problems}
        assert ex["S3_SECRET_KEY"] not in _scrubbed(str(ei.value))
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("app_env", _PRODUCTION_SPELLINGS)
def test_api_lifespan_refuses_env_example_defaults_before_db(monkeypatch, app_env):
    import asyncio
    import app.main as main_mod
    from app.core.config import get_settings

    ex = _env_example()
    env = good_production_env()
    env["APP_ENV"] = app_env
    for n in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "DATABASE_URL"):
        env[n] = ex[n]
    _apply_env(monkeypatch, env)
    called = []
    monkeypatch.setattr(main_mod, "_verify_db_connectivity", lambda: called.append(1))

    async def run():
        async with main_mod.lifespan(main_mod.app):
            pass

    try:
        with pytest.raises(cc.ConfigContractError):
            asyncio.run(run())
    finally:
        get_settings.cache_clear()
    assert not called


def test_cli_refuses_env_example_defaults_without_echoing_them():
    ex = _env_example()
    bad = good_production_env()
    bad["APP_ENV"] = " PRODUCTION "
    for n in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "POSTGRES_PASSWORD", "OPENAI_API_KEY"):
        bad[n] = ex[n]
    base = {
        k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "SYSTEMROOT", "PYTHONPATH")
    }
    r = subprocess.run(
        [sys.executable, "-m", "app.core.config_contract", "check"],
        cwd=API_ROOT,
        env={**base, **bad},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 2
    out = _scrubbed(r.stdout + r.stderr)
    for n in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "POSTGRES_PASSWORD", "OPENAI_API_KEY"):
        assert n in out
        assert ex[n] not in out, f"value of {n} echoed by the CLI"
