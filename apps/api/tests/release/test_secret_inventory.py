"""TC-07-001 release gate: exposed signing literals, cookies and traces stay contained.

Every "secret" used here is generated at runtime; this file must never contain a real or
realistic credential literal (it is excluded from the scanner only so that the synthetic
positive fixtures below can be built).
"""

from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import importlib.util
import io
import json
import secrets
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCANNER_PATH = REPO_ROOT / "scripts" / "security" / "secret_inventory.py"


def _load_scanner():
    spec = importlib.util.spec_from_file_location("tc_secret_inventory", SCANNER_PATH)
    assert spec and spec.loader, f"scanner missing at {SCANNER_PATH}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def scanner():
    return _load_scanner()


def _git_available() -> bool:
    try:
        return subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--git-dir"],
                              capture_output=True, check=False).returncode == 0
    except FileNotFoundError:
        return False


def _blocks(findings):
    return [f for f in findings if f.severity == "block"]


# ---------------------------------------------------------------------------
# AC: the working tree contains no blocking secret literals (regression gate)
# ---------------------------------------------------------------------------

def test_tree_has_no_blocking_secret_literals(scanner):
    findings = scanner.scan_tree(REPO_ROOT)
    blocks = _blocks(findings)
    # Location-only message: never echo values.
    assert not blocks, "secret literals reintroduced:\n" + "\n".join(
        f"{f.location()} {f.rule} ({f.kind})" for f in blocks)


def test_scanner_cli_exit_code_is_zero_on_tree(tmp_path):
    out = tmp_path / "tree.json"
    proc = subprocess.run([sys.executable, str(SCANNER_PATH), "tree", "--root", str(REPO_ROOT),
                           "--json", str(out)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout[-2000:]
    data = json.loads(out.read_text())
    assert data["summary"]["block"] == 0
    # Report contains locations and rule names only, never a value field.
    for f in data["findings"]:
        assert set(f) <= {"source", "path", "line", "rule", "kind", "severity", "commit"}


# ---------------------------------------------------------------------------
# Scanner detects each class of exposure (synthetic, runtime-generated values)
# ---------------------------------------------------------------------------

def _fake_session_cookie() -> str:
    key = secrets.token_bytes(32)
    payload = base64.urlsafe_b64encode(json.dumps({"uid": 1, "ws": 1}).encode()).decode()
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _cases() -> list[tuple[str, str, str]]:
    tok = secrets.token_urlsafe(48)
    pw = secrets.token_urlsafe(24)
    pem = "-----BEGIN " + "RSA PRIVATE KEY-----\n" + base64.b64encode(secrets.token_bytes(48)).decode() + "\n"
    return [
        ("signing literal in a test script", "apps/api/tests/x_live.py", f'SECRET = "{tok}"\n'),
        ("hmac with literal key", "apps/api/tests/x_live2.py",
         f'sig = hmac.new(b"{tok}", payload, hashlib.sha256)\n'),
        ("cookie jar line", ".curl_cookies.txt",
         f"localhost\tFALSE\t/\tFALSE\t0\ttc_session\t{_fake_session_cookie()}\n"),
        ("env default", "apps/api/app/core/x.py", f'S = os.getenv("SESSION_SECRET", "{tok}")\n'),
        ("compose inline DB password", "docker-compose.prod.yml",
         f"      DATABASE_URL: postgresql://tc:{pw}@postgres:5432/tc\n"),
        ("compose secret value", "docker-compose.prod.yml", f"      POSTGRES_PASSWORD: {pw}\n"),
        ("pem private key", "deploy/key.pem", pem),
    ]


@pytest.mark.parametrize("label,path,text", _cases(), ids=[c[0] for c in _cases()])
def test_scanner_blocks_synthetic_exposures(scanner, label, path, text):
    findings = scanner.scan_text(text, path)
    assert _blocks(findings), f"scanner missed: {label}"


def test_scanner_scans_trace_archives_in_memory(scanner):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z2:
            z2.writestr("0-trace.network",
                        json.dumps({"headers": [{"name": "Cookie", "value": "tc_session=" + _fake_session_cookie()}]}))
        zf.writestr("data/trace.zip", inner.getvalue())
    findings = scanner._scan_archive(buf.getvalue(), "apps/web/test-results/x/trace.zip", "artifact")
    assert _blocks(findings)


def test_scanner_ignores_references_and_placeholders(scanner):
    py_safe = "\n".join([
        'SESSION_SECRET = os.environ["SESSION_SECRET"]',
        'session_secret: str = os.getenv("SESSION_SECRET", "")',
        "secret = secrets.token_urlsafe(48)",
    ]) + "\n"
    cfg_safe = "\n".join([
        "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?must be set}",
        "SESSION_SECRET=<generate-me>",
        "SESSION_SECRET=",
        "$env:SESSION_SECRET = [Convert]::ToBase64String($bytes)",
    ]) + "\n"
    assert not _blocks(scanner.scan_text(py_safe, "apps/api/app/core/example.py"))
    assert not _blocks(scanner.scan_text(cfg_safe, "docker-compose.prod.yml"))
    assert not _blocks(scanner.scan_text(cfg_safe, "scripts/example.ps1"))


def test_scanner_output_never_contains_values(scanner, capsys, tmp_path):
    tok = secrets.token_urlsafe(48)
    (tmp_path / "leak.py").write_text(f'API_TOKEN = "{tok}"\n')
    rc = scanner.main(["paths", "leak.py", "--root", str(tmp_path), "--json", str(tmp_path / "o.json")])
    out = capsys.readouterr().out
    assert rc == 1
    assert tok not in out
    assert tok not in (tmp_path / "o.json").read_text()


# ---------------------------------------------------------------------------
# Cookie jars, Playwright reports and traces are removed and ignored
# ---------------------------------------------------------------------------

REMOVED_ARTIFACTS = [
    ".curl_cookies.txt", ".tmp_cookies.txt", ".tmp_test_cookies.txt",
    "apps/web/playwright-report", "apps/web/test-results",
]
IGNORED_SAMPLES = [
    ".curl_cookies.txt", "cookies.txt", "x_cookies_y.txt", ".tmp_anything.json",
    "apps/web/playwright-report/index.html", "apps/web/test-results/a/trace.zip",
    "apps/web/blob-report/report.zip", "session.har", "apps/api/.seed-credentials.local",
]


@pytest.mark.skipif(not _git_available(), reason="git metadata not available")
def test_cookie_jars_and_traces_not_tracked():
    tracked = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True,
                             text=True, check=True).stdout.splitlines()
    bad = [p for p in tracked
           if any(p == a or p.startswith(a + "/") for a in REMOVED_ARTIFACTS)
           or p.endswith((".har", "trace.zip")) or "cookies" in Path(p).name.lower() and p.endswith(".txt")]
    assert not bad, f"tracked cookie/trace artifacts: {bad}"


@pytest.mark.skipif(not _git_available(), reason="git metadata not available")
@pytest.mark.parametrize("path", IGNORED_SAMPLES)
def test_sensitive_artifacts_are_gitignored(path):
    rc = subprocess.run(["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--no-index", path],
                        capture_output=True, check=False).returncode
    assert rc == 0, f"{path} is not gitignored"


# ---------------------------------------------------------------------------
# Signing secret: no literal fallback; production refuses weak secrets
# ---------------------------------------------------------------------------

def test_no_dev_secret_literal_in_session_module():
    import app.core.session as session_mod
    assert not hasattr(session_mod, "_DEV_SECRET")
    src = Path(session_mod.__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and len(node.value.value) >= 16:
            names = [getattr(t, "id", "") for t in node.targets]
            assert not any("SECRET" in n.upper() for n in names), f"literal secret at line {node.lineno}"


def test_config_has_no_secret_defaults(monkeypatch):
    from app.core.config import Settings
    for var in ("SESSION_SECRET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    for name in ("session_secret", "s3_access_key", "s3_secret_key"):
        assert getattr(s, name) in ("", None), f"{name} has a non-empty default"


@pytest.mark.parametrize("value", ["", "placeholder", "test-secret", "changeme", "a" * 64, "short-but-random-9f"])
def test_production_rejects_weak_session_secret(monkeypatch, value):
    from app.core import session as session_mod
    from app.core.config import get_settings
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", value)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            session_mod.get_session_secret()
    finally:
        get_settings.cache_clear()


def test_production_accepts_generated_secret(monkeypatch):
    from app.core import session as session_mod
    from app.core.config import get_settings
    strong = secrets.token_urlsafe(48)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", strong)
    get_settings.cache_clear()
    try:
        assert session_mod.get_session_secret() == strong
    finally:
        get_settings.cache_clear()


def test_dev_fallback_is_random_per_process(monkeypatch):
    from app.core import session as session_mod
    from app.core.config import get_settings
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SESSION_SECRET", "")
    monkeypatch.setattr(session_mod, "_EPHEMERAL_SECRET", None)
    get_settings.cache_clear()
    try:
        a = session_mod.get_session_secret()
        assert len(a) >= 32 and a == session_mod.get_session_secret()
        monkeypatch.setattr(session_mod, "_EPHEMERAL_SECRET", None)
        assert session_mod.get_session_secret() != a
    finally:
        get_settings.cache_clear()


def test_storage_client_requires_explicit_credentials(monkeypatch):
    from app.core.config import get_settings
    from app.services import storage
    monkeypatch.setenv("S3_ACCESS_KEY", "")
    monkeypatch.setenv("S3_SECRET_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="S3_"):
            storage.StorageClient()
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Logs/traces: secret material is redacted
# ---------------------------------------------------------------------------

def test_log_redaction_masks_cookies_tokens_and_url_credentials():
    import logging
    from app.core.logging_config import JsonFormatter, redact
    cookie = _fake_session_cookie()
    pw = secrets.token_urlsafe(16)
    for text in (f"Cookie: tc_session={cookie}", f"Authorization: Bearer {pw}",
                 f"postgresql://tc:{pw}@db/tc", f"password={pw}"):
        cleaned = redact(text)
        assert cookie not in cleaned and pw not in cleaned
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "login %s", (f"tc_session={cookie}",), None)
    rec.session_secret = pw
    out = JsonFormatter().format(rec)
    assert cookie not in out and pw not in out


# ---------------------------------------------------------------------------
# Live-API helper scripts: no literals, not collected, need explicit env
# ---------------------------------------------------------------------------

LIVE_SCRIPTS = [
    "tests/test_coverage_api.py", "tests/test_alerts_api.py", "tests/fetch_ds5.py",
    "tests/fetch_full_qa.py", "tests/run_10dataset_test.py", "tests/run_3dataset_test.py",
]
API_ROOT = REPO_ROOT / "apps" / "api"


@pytest.mark.parametrize("rel", LIVE_SCRIPTS)
def test_live_scripts_have_no_module_level_side_effects(rel):
    path = API_ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} not present")
    tree = ast.parse(path.read_text())
    collectable = path.name.startswith("test_") or path.stem.endswith("_test")
    if collectable:
        assert "__test__ = False" in path.read_text(), f"{rel} must opt out of pytest collection"
    for node in (tree.body if collectable else []):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            pytest.fail(f"{rel}:{node.lineno} performs a call at import time")
    src = path.read_text()
    assert "_live_session" in src, f"{rel} must use tests/_live_session.py"


def test_live_session_helper_requires_env(monkeypatch):
    sys.path.insert(0, str(API_ROOT / "tests"))
    try:
        import _live_session
        monkeypatch.delenv("TC_SESSION_SECRET", raising=False)
        with pytest.raises(SystemExit):
            _live_session.live_session_secret()
    finally:
        sys.path.remove(str(API_ROOT / "tests"))


def test_seed_scripts_have_no_password_literals():
    for rel in ("scripts/seed_demo_workspace.py", "scripts/seed_qa_test_data.py"):
        tree = ast.parse((API_ROOT / rel).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                names = [getattr(t, "id", "") for t in node.targets]
                assert not any("PASSWORD" in n.upper() for n in names), f"{rel}:{node.lineno}"


def test_web_login_bundle_has_no_demo_password_literal():
    src = (REPO_ROOT / "apps/web/app/login/page.tsx").read_text()
    assert "NEXT_PUBLIC_DEMO_LOGIN_PASSWORD" in src
    assert "password: DEMO_LOGIN_PASSWORD" in src


# ---------------------------------------------------------------------------
# Encryption-key consumers (credential store, MFA, Slack) fail closed in production
# (Integrations input: credential store previously fell back to a hardcoded key)
# ---------------------------------------------------------------------------

_KEY_CONSUMERS = [
    ("app.services.credential_store_service", "_get_fernet"),
    ("app.core.mfa", "_fernet"),
    ("app.services.slack_service", "_fernet"),
]


@pytest.mark.parametrize("module,func", _KEY_CONSUMERS)
@pytest.mark.parametrize("value", ["", "placeholder", "changeme"])
def test_encryption_key_consumers_fail_closed_in_production(monkeypatch, module, func, value):
    import importlib
    from app.core.config import get_settings
    mod = importlib.import_module(module)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", value)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            getattr(mod, func)()
    finally:
        get_settings.cache_clear()


def test_credential_store_has_no_literal_fallback():
    src = (API_ROOT / "app/services/credential_store_service.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("getenv", "get") \
                and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant) \
                and "SECRET" in str(node.args[0].value).upper():
            default = node.args[1]
            assert isinstance(default, ast.Constant) and default.value in ("", None), \
                f"credential_store_service.py:{node.lineno} has a literal secret fallback"


def test_credential_store_roundtrip_with_generated_secret(monkeypatch):
    from app.core.config import get_settings
    from app.services import credential_store_service as cs
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(48))
    get_settings.cache_clear()
    try:
        plain = secrets.token_urlsafe(16)
        assert cs.decrypt(cs.encrypt(plain)) == plain
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Compose files: no inline production credentials; dev defaults are overridable
# ---------------------------------------------------------------------------

def test_prod_compose_requires_credentials_from_env():
    text = (REPO_ROOT / "docker-compose.prod.yml").read_text()
    for var in ("POSTGRES_PASSWORD", "POSTGRES_USER", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"):
        assert f"${{{var}:?" in text, f"docker-compose.prod.yml must require {var} (${{{var}:?...}})"
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("DATABASE_URL:") or s.startswith("- DATABASE_URL="):
            pytest.fail("docker-compose.prod.yml must not inline DATABASE_URL")


def test_dev_compose_credentials_are_overridable():
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    for var in ("POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "MINIO_ROOT_USER", "POSTGRES_USER"):
        line = next(l for l in text.splitlines() if l.strip().startswith(f"{var}:"))
        assert "${" + var in line, f"docker-compose.yml {var} must be an overridable variable"
    for line in text.splitlines():
        if line.strip().startswith("DATABASE_URL:"):
            assert "${POSTGRES_PASSWORD" in line


# ---------------------------------------------------------------------------
# Deploy docs: operators generate every secret; committed values are retired
# (AC2 owner statement 2026-10-27). Cheap text checks, no values involved.
# ---------------------------------------------------------------------------

import re  # noqa: E402

DEPLOY_ENTRYPOINTS = ("README.md", ".env.example", "docker-compose.prod.yml")

_CRED_PAIR = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+`?\s*/\s*`[^`\s]+`")
_MD_ASSIGN = re.compile(
    r"(?i)\b[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_KEY|TOKEN)[A-Z0-9_]*\s*[=:]\s*`?([^\s`|,;)]+)"
)
_PLACEHOLDER = re.compile(r"(?i)^(<.*>|\$\{.*|\$[A-Z_]+|\.\.\.|placeholder\S*|changeme|change-me|x+|\*+|\"\"|''|none|null|unset)$")
_NOT_A_VALUE = re.compile(r"^[\d<>=.,()%+-]+$")  # e.g. "SESSION_SECRET: 32)" describes a length, not a value
_REUSE = re.compile(
    r"(?i)\b(re-?use|keep|copy|use)\s+(the\s+)?(same|existing|committed|default|example|old|sample|demo|dev)\s+"
    r"(passwords?|secrets?|keys?|credentials?|tokens?|values?)"
)
_NEGATION = re.compile(r"(?i)\b(never|not|don't|do not|must not|no)\b")


def _deploy_doc_paths() -> list[Path]:
    paths = [REPO_ROOT / p for p in DEPLOY_ENTRYPOINTS]
    paths += [REPO_ROOT / "scripts" / "README.md", REPO_ROOT / "apps" / "api" / "scripts" / "README.md"]
    for p in sorted((REPO_ROOT / "docs").rglob("*.md")):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("docs/release/tickets/"):
            continue  # ticket docs describe the exposure inventory (paths only), not deploy steps
        paths.append(p)
    return [p for p in paths if p.exists()]


def deploy_doc_problems(text: str, *, markdown: bool) -> list[str]:
    """Return line-numbered problem descriptions (never the matched value)."""
    problems: list[str] = []
    for n, line in enumerate(text.splitlines(), 1):
        if _CRED_PAIR.search(line):
            problems.append(f"line {n}: login/password literal pair")
        if _REUSE.search(line) and not _NEGATION.search(line):
            problems.append(f"line {n}: tells the operator to reuse an existing/committed credential")
        if markdown:
            for m in _MD_ASSIGN.finditer(line):
                if not _PLACEHOLDER.match(m.group(1)) and not _NOT_A_VALUE.match(m.group(1)):
                    problems.append(f"line {n}: credential assignment with a literal value")
    return problems


def test_deploy_entrypoints_require_operator_generated_secrets():
    for rel in DEPLOY_ENTRYPOINTS:
        text = (REPO_ROOT / rel).read_text()
        assert "openssl rand" in text, f"{rel} must tell operators to generate secrets (e.g. openssl rand)"
        flat = re.sub(r"\s*\n\s*#?\s*", " ", text)  # join wrapped comment lines
        assert re.search(r"(?i)generate every secret", flat), f"{rel} must say every secret is operator-generated"
        assert re.search(r"(?i)\bretired\b", flat), f"{rel} must state previously exposed values are retired"
        assert re.search(r"(?i)never be reused", flat), f"{rel} must say retired values must never be reused"


def test_deploy_docs_never_point_at_committed_values():
    failures = []
    for p in _deploy_doc_paths():
        rel = p.relative_to(REPO_ROOT).as_posix()
        for problem in deploy_doc_problems(p.read_text(errors="replace"), markdown=p.suffix == ".md"):
            failures.append(f"{rel} {problem}")
    assert not failures, "Deploy docs must not hand out or reuse credentials:\n" + "\n".join(failures)


@pytest.mark.parametrize(
    "template",
    [
        "- **Demo login:** `ops@example.test` / `{v}` (after seed)",
        "For production, reuse the committed secret from docker-compose.yml.",
        "Copy the example password into .env.production.",
        "Set SESSION_SECRET={v} before deploying.",
        "Use `MINIO_ROOT_PASSWORD: {v}` in production.",
    ],
)
def test_deploy_doc_checker_flags_bad_guidance(template):
    bad = template.format(v="k" + secrets.token_hex(8))  # letter prefix: never all-digit
    assert deploy_doc_problems(bad, markdown=True), "checker must flag this guidance"


@pytest.mark.parametrize(
    "line",
    [
        "Generate every secret with `openssl rand -hex 32`; never reuse a committed value.",
        "Set SESSION_SECRET=<generated> and S3_SECRET_KEY=${S3_SECRET_KEY}.",
        "Do not copy the example password into production.",
        "Credentials shorter than 16 characters (SESSION_SECRET: 32) are refused.",
    ],
)
def test_deploy_doc_checker_allows_good_guidance(line):
    assert deploy_doc_problems(line, markdown=True) == []
