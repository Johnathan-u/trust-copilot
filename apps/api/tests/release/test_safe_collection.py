"""TC-02-001 release test: importing/collecting tests cannot contact production or use
checked-in credentials, and markers / unsafe-script exclusions are explicit.

Run from apps/api:  python -m pytest tests/release/test_safe_collection.py -q
Needs no database, no network and no running stack.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

from tests import _safety

pytestmark = pytest.mark.unit

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]
TESTS_DIR = API_ROOT / "tests"
MANUAL_DIR = API_ROOT / "scripts" / "manual_live"

# sha256 of the session-signing secret that used to be hardcoded in tests/ (value redacted).
LEAKED_SESSION_SECRET_SHA256 = "9368da3761b0d4fe8b487f86225b803f39d5b37b26e1ab064e1808e4d471d6c8"

# Former tests/ residents that performed live HTTP / forged cookies / read local-only paths.
FORMER_UNSAFE_SCRIPTS = {
    "test_alerts_api.py": "probe_alerts_api.py",
    "test_coverage_api.py": "probe_coverage_api.py",
    "e2e_pipeline_test.py": "e2e_pipeline_check.py",
    "full_ui_backend_test.py": "full_ui_backend_check.py",
    "run_3dataset_test.py": "run_3dataset_check.py",
    "run_10dataset_test.py": "run_10dataset_check.py",
    "fetch_ds5.py": "fetch_ds5.py",
    "fetch_full_qa.py": "fetch_full_qa.py",
    "pipeline_data_audit.py": "pipeline_data_audit.py",
    "pipeline_deep_audit.py": "pipeline_deep_audit.py",
    "_inspect_blind.py": "inspect_blind.py",
    "_run_blind_full.py": "run_blind_full.py",
    "verify_mapping_counter.py": "verify_mapping_counter.py",
}

CANARY_ENV = {
    # If any of these leak into the collected process or are used, the assertions below fail.
    "OPENAI_API_KEY": "sk-canary-tc02001-should-be-scrubbed",
    "STRIPE_SECRET_KEY": "sk_test_canary_tc02001",
    "SENTRY_DSN": "https://canary@sentry.invalid/1",
    "SMTP_PASSWORD": "canary-smtp",
    "DATABASE_URL": "postgresql://prod_user:prod_pw@db.production.invalid:5432/trustcopilot",
    "TC_API": "https://api.production.invalid",
}

TRACER = textwrap.dedent(
    """
    import os, socket
    _log = os.environ["TC_SOCKET_TRACE_FILE"]
    def _trace(self, addr):
        with open(_log, "a") as f:
            f.write(repr(addr) + "\\n")
        raise ConnectionRefusedError("socket tracer: connection attempt recorded")
    socket.socket.connect = _trace
    socket.socket.connect_ex = lambda self, addr: (_trace(self, addr), 111)[1]
    """
)


def _clean_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "TC_TEST_", "COV_"))}
    env.pop("TRUST_COPILOT_TESTING", None)
    env.pop(_safety.PROVIDER_OPT_IN_ENV, None)
    env.update(CANARY_ENV)
    (tmp_path / "sitecustomize.py").write_text(TRACER)
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(API_ROOT)])
    env["TC_SOCKET_TRACE_FILE"] = str(tmp_path / "socket_trace.log")
    env.update(extra)
    return env


def _socket_trace(tmp_path: Path) -> list[str]:
    log = tmp_path / "socket_trace.log"
    return log.read_text().splitlines() if log.exists() else []


def _collected_test_files() -> list[Path]:
    return sorted(p for p in TESTS_DIR.rglob("*.py") if "__pycache__" not in p.parts)


# --------------------------------------------------------------------------------------------
# AC1 - importing or collecting tests cannot contact production or use checked-in credentials
# --------------------------------------------------------------------------------------------


def test_full_collection_opens_no_sockets_with_hostile_env(tmp_path):
    """Collect the whole suite with production-looking env + a socket tracer: zero connects."""
    env = _clean_env(tmp_path)
    proc = subprocess.run(
        check=False,
        args=[
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests",
        ],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-4000:]
    assert re.search(r"\d+ tests collected", out), out[-2000:]
    assert "error" not in out.lower().split("tests collected")[-1], out[-2000:]
    assert _socket_trace(tmp_path) == [], (
        f"collection attempted connections: {_socket_trace(tmp_path)}"
    )
    collected_files = {ln.split("::", 1)[0] for ln in out.splitlines() if "::" in ln}
    for former in FORMER_UNSAFE_SCRIPTS:
        assert f"tests/{former}" not in collected_files


def test_conftest_scrubs_provider_credentials_and_pins_local_test_db(tmp_path):
    probe = textwrap.dedent(
        """
        import os, socket, json
        import tests.conftest  # noqa: F401  (runs the isolation block)
        from tests import _safety
        res = {
            "openai": "OPENAI_API_KEY" in os.environ,
            "stripe": "STRIPE_SECRET_KEY" in os.environ,
            "sentry": "SENTRY_DSN" in os.environ,
            "smtp": "SMTP_PASSWORD" in os.environ,
            "db": os.environ["DATABASE_URL"],
            "testing": os.environ.get("TRUST_COPILOT_TESTING"),
        }
        try:
            socket.create_connection(("203.0.113.10", 443), timeout=1)
            res["egress"] = "connected"
        except _safety.NetworkAccessBlocked:
            res["egress"] = "blocked"
        from app.core.config import get_settings
        get_settings.cache_clear()
        res["settings_openai"] = bool(getattr(get_settings(), "openai_api_key", None))
        print("RESULT=" + json.dumps(res))
        """
    )
    proc = subprocess.run(
        check=False,
        args=[sys.executable, "-c", probe],
        cwd=API_ROOT,
        env=_clean_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT=")][-1]
    import json

    res = json.loads(line.split("=", 1)[1])
    assert (
        res["openai"] is False
        and res["stripe"] is False
        and res["sentry"] is False
        and res["smtp"] is False
    )
    assert res["settings_openai"] is False
    assert res["testing"] == "1"
    assert "production.invalid" not in res["db"] and res["db"].endswith("/trustcopilot_test")
    assert res["egress"] == "blocked"
    assert _socket_trace(tmp_path) == [], "the guard must block before any real connect()"


def test_conftest_never_reads_dotenv_files():
    src = (TESTS_DIR / "conftest.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            assert name not in {"load_dotenv", "dotenv_values"}, "conftest must not load .env"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value != ".env", "conftest must not reference a .env file"


@pytest.mark.parametrize("module", ["app.worker", "app.main", "app.core.database"])
def test_app_modules_do_not_load_dotenv_under_tests(tmp_path, module):
    probe = textwrap.dedent(
        f"""
        import os, dotenv
        calls = []
        dotenv.load_dotenv = lambda *a, **k: calls.append([str(x) for x in a]) or False
        os.environ["TRUST_COPILOT_TESTING"] = "1"
        os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/trustcopilot_test"
        os.environ.pop("TRUST_COPILOT_IN_DOCKER", None)
        import {module}  # noqa
        print("CALLS=%d" % len(calls))
        """
    )
    proc = subprocess.run(
        check=False,
        args=[sys.executable, "-c", probe],
        cwd=API_ROOT,
        env=_clean_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert "CALLS=0" in proc.stdout, f"{module} loaded .env under TRUST_COPILOT_TESTING=1"
    assert _socket_trace(tmp_path) == []


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@db.production.invalid:5432/trustcopilot_test",
        "postgresql://u:p@10.0.0.5:5432/trustcopilot_test",
        "postgresql://u:p@localhost:5432/trustcopilot",
        "mysql://u:p@localhost/x_test",
    ],
)
def test_unsafe_test_database_targets_are_refused(url):
    with pytest.raises(_safety.UnsafeTestTargetError):
        _safety.validate_test_database_url(url)


def test_local_test_database_targets_are_accepted():
    for url in (
        "postgresql://postgres:postgres@localhost:5432/trustcopilot_test",
        "postgresql://postgres:postgres@127.0.0.1:55432/trustcopilot_test",
        "postgresql://postgres:postgres@postgres:5432/trustcopilot_test",
    ):
        assert _safety.validate_test_database_url(url) == url


def test_network_guard_blocks_external_allows_loopback():
    assert _safety.guard_installed()
    before = list(_safety._STATE.blocked)
    try:
        with pytest.raises(_safety.NetworkAccessBlocked):
            socket.create_connection(("198.51.100.7", 443), timeout=1)
        with pytest.raises(_safety.NetworkAccessBlocked):
            socket.getaddrinfo("api.openai.com", 443)
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        try:
            c = socket.create_connection(srv.getsockname(), timeout=2)
            c.close()
        finally:
            srv.close()
    finally:
        _safety._STATE.blocked[:] = before
    with pytest.raises(_safety.UnsafeTestTargetError):
        # The allowlist itself refuses non-local hosts.
        os.environ[_safety.EXTRA_ALLOWED_HOSTS_ENV] = "api.openai.com"
        try:
            _safety.install_network_guard()
        finally:
            os.environ.pop(_safety.EXTRA_ALLOWED_HOSTS_ENV, None)
    assert _safety.guard_installed()


_SYNTHETIC = re.compile(r"(?i)test|fake|dummy|example|canary|placeholder")
_SECRET_PATTERNS = [
    re.compile(r"""(?i)\b\w*secret\w*\s*=\s*["'](?!test-secret["'])[^"'\s]{16,}["']"""),
    re.compile(r"sk-(?!canary)[A-Za-z0-9]{20,}"),
    re.compile(r"sk_live_[A-Za-z0-9]{10,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"[A-Za-z0-9._%+-]+@(gmail|outlook|hotmail|yahoo)\.com"),
]


@pytest.mark.parametrize("root", [TESTS_DIR, MANUAL_DIR], ids=["tests", "scripts-manual_live"])
def test_no_checked_in_credentials_or_personal_identities(root):
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or path == Path(__file__):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat in _SECRET_PATTERNS:
            for m in pat.finditer(text):
                if _SYNTHETIC.search(m.group(0)):
                    continue  # clearly synthetic fixture value (e.g. xoxb-test-token)
                offenders.append(f"{path.relative_to(API_ROOT)}: {pat.pattern[:30]}")
        for token in set(re.findall(r"[A-Za-z0-9_\-]{40,}", text)):
            if hashlib.sha256(token.encode()).hexdigest() == LEAKED_SESSION_SECRET_SHA256:
                offenders.append(f"{path.relative_to(API_ROOT)}: formerly hardcoded session secret")
    assert offenders == []


_NET_ROOTS = {"requests", "httpx", "urllib", "urllib3", "socket", "http", "aiohttp", "boto3"}
_NET_VERBS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "request",
    "urlopen",
    "create_connection",
    "connect",
    "send",
    "stream",
    "fetch",
}


def _root_name(node):
    while isinstance(node, (ast.Attribute, ast.Call)):
        node = node.value if isinstance(node, ast.Attribute) else node.func
    return node.id if isinstance(node, ast.Name) else None


def _module_level_network_calls(tree: ast.Module) -> list[str]:
    session_vars: set[str] = set()
    found = []
    for stmt in tree.body:
        if isinstance(
            stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)
        ):
            continue
        if isinstance(stmt, ast.If) and "__main__" in ast.unparse(stmt.test):
            continue
        for node in ast.walk(stmt):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and _root_name(node.value) in _NET_ROOTS
            ):
                session_vars.update(t.id for t in node.targets if isinstance(t, ast.Name))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _NET_VERBS
            ):
                root = _root_name(node.func)
                if root in _NET_ROOTS or root in session_vars:
                    found.append(f"line {node.lineno}: {ast.unparse(node.func)}")
    return found


def test_no_collected_module_performs_network_io_at_import():
    offenders = {}
    for path in _collected_test_files():
        calls = _module_level_network_calls(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
        if calls:
            offenders[str(path.relative_to(API_ROOT))] = calls
    assert offenders == {}


def test_static_detector_flags_the_former_unsafe_pattern():
    """Self-check: the AST detector catches the shape of the removed tests/test_coverage_api.py."""
    sample = 'import requests\nS = requests.Session()\nr = S.get("http://localhost:8000/x")\n'
    assert _module_level_network_calls(ast.parse(sample))
    guarded = 'import requests\ndef main():\n    requests.get("http://x")\nif __name__ == "__main__":\n    main()\n'
    assert not _module_level_network_calls(ast.parse(guarded))


# --------------------------------------------------------------------------------------------
# AC2 - markers and explicit unsafe-script exclusions are reviewed and documented
# --------------------------------------------------------------------------------------------


def _pytest_ini() -> dict:
    return tomllib.loads((API_ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]


def test_pytest_config_restricts_collection_and_enforces_markers():
    ini = _pytest_ini()
    assert ini["testpaths"] == ["tests"]
    assert ini["python_files"] == ["test_*.py"]
    assert "--strict-markers" in ini["addopts"]
    names = {m.split(":", 1)[0].strip() for m in ini["markers"]}
    assert {"unit", "integration", "provider", "live_stack", "external_data"} <= names
    assert "scripts" in ini["norecursedirs"]


def test_unknown_marker_is_rejected(tmp_path):
    probe = tmp_path / "test_probe_marker.py"
    probe.write_text(
        "import pytest\n@pytest.mark.not_a_registered_marker\ndef test_x():\n    pass\n"
    )
    proc = subprocess.run(
        check=False,
        args=[
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "-c",
            str(API_ROOT / "pyproject.toml"),
            "--rootdir",
            str(API_ROOT),
            str(probe),
        ],
        cwd=API_ROOT,
        env=_clean_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
    assert "not_a_registered_marker" in proc.stdout + proc.stderr


def test_unsafe_scripts_moved_out_of_test_tree():
    for former, new in FORMER_UNSAFE_SCRIPTS.items():
        assert not (TESTS_DIR / former).exists(), f"{former} must not live under tests/"
        assert (MANUAL_DIR / new).exists(), f"{new} missing from scripts/manual_live"
    readme = (MANUAL_DIR / "README.md").read_text()
    for former in FORMER_UNSAFE_SCRIPTS:
        assert f"tests/{former}" in readme, f"README.md must document the move of tests/{former}"
    for path in _collected_test_files():
        assert path.name.startswith(("test_", "conftest", "_safety", "__init__")), path


@pytest.mark.parametrize(
    "script,env_extra,expect",
    [
        (
            "probe_coverage_api.py",
            {"TC_API": "https://api.production.invalid", "TC_SESSION_SECRET": "x"},
            "not a local stack host",
        ),
        (
            "probe_alerts_api.py",
            {"TC_API": "http://localhost:8000", "TC_SESSION_SECRET": ""},
            "TC_SESSION_SECRET",
        ),
        ("fetch_full_qa.py", {"TC_API": "http://10.1.2.3:8000"}, "not a local stack host"),
        (
            "pipeline_deep_audit.py",
            {"TC_API": "https://trustcopilot.example.com"},
            "not a local stack host",
        ),
    ],
)
def test_manual_live_scripts_refuse_remote_targets_and_missing_secret(
    tmp_path, script, env_extra, expect
):
    env = _clean_env(tmp_path)
    env.update(env_extra)
    proc = subprocess.run(
        check=False,
        args=[sys.executable, str(MANUAL_DIR / script)],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert expect in proc.stdout + proc.stderr
    assert _socket_trace(tmp_path) == []


def test_auto_classification_markers_applied(request):
    # This module is explicitly `unit`; collection-time classification must keep it that way.
    assert request.node.get_closest_marker("unit") is not None
    assert request.node.get_closest_marker("integration") is None


def test_external_data_module_skips_with_explicit_reason(tmp_path):
    proc = subprocess.run(
        check=False,
        args=[
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rs",
            "-p",
            "no:cacheprovider",
            "tests/test_trust_scoring_blind.py",
        ],
        cwd=API_ROOT,
        env=_clean_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "external_data: blind test pack not checked in" in proc.stdout
    assert _socket_trace(tmp_path) == []


def test_playwright_config_refuses_non_local_api_upstream(tmp_path):
    node = shutil.which("node")
    cfg = (REPO_ROOT / "apps" / "web" / "playwright.config.ts").read_text()
    assert "Refusing to run E2E" in cfg and "LOCAL_UPSTREAM_HOSTS" in cfg
    if not node:
        pytest.skip("node not installed; static check above still enforced")
    snippet = cfg[cfg.index("const LOCAL_UPSTREAM_HOSTS") : cfg.index("export default")]
    js = tmp_path / "guard.js"
    js.write_text(snippet + "\nconsole.log('OK ' + apiUpstream)\n")
    ok = subprocess.run(
        check=False,
        args=[node, str(js)],
        env={"PATH": os.environ.get("PATH", ""), "API_UPSTREAM": "http://127.0.0.1:18080"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert ok.returncode == 0 and "OK http://127.0.0.1:18080" in ok.stdout
    bad = subprocess.run(
        check=False,
        args=[node, str(js)],
        env={"PATH": os.environ.get("PATH", ""), "API_UPSTREAM": "https://api.production.invalid"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert bad.returncode != 0 and "Refusing to run E2E" in bad.stderr
