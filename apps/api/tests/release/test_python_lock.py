"""TC-02-002: locked Python dependencies and the PostgreSQL driver.

AC1  A fresh locked install imports the app and connects through the explicitly installed
     SQLAlchemy driver (psycopg2 via psycopg2-binary; SQLAlchemy stays below 2.1, whose
     ``postgresql://`` default is psycopg 3).
AC2  Runtime and dev dependencies are locked separately with exact versions and hashes, the dev
     lock reuses the runtime pins, and the lock is closed over what the app requires. Two clean
     builds therefore resolve the same runtime versions (the two-build run itself is recorded in
     artifacts/acceptance/TC-02-002/).

The lock-file checks are static. The installed-version and DB checks run against the current
interpreter, which CI installs from requirements-dev.lock. Synthetic data only; no network.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import pytest
from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]
PYPROJECT = API_ROOT / "pyproject.toml"
RUNTIME_LOCK = API_ROOT / "requirements.lock"
DEV_LOCK = API_ROOT / "requirements-dev.lock"
LOCK_SCRIPT = REPO_ROOT / "scripts" / "lock-python-deps.sh"

_PIN_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)\s*(?:;\s*(?P<marker>[^\\]+?))?\s*$"
)
_HASH_RE = re.compile(r"--hash=sha256:[0-9a-f]{64}")


# --- lock parsing / checking (pure functions, exercised with synthetic input below) ----------


def parse_lock(text: str) -> tuple[dict[str, dict], list[str]]:
    """Return ({name: {version, marker, hashes}}, problems) for a pip-compile style lock."""
    entries: dict[str, dict] = {}
    problems: list[str] = []
    logical: list[str] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            if buf:
                logical.append(buf)
                buf = ""
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        logical.append(buf + line)
        buf = ""
    if buf:
        logical.append(buf)
    for item in logical:
        req, _, rest = item.strip().partition(" --hash")
        rest = "--hash" + rest if rest else ""
        req = req.strip()
        if req.startswith("-"):
            problems.append(f"option line not allowed in a lock: {req!r}")
            continue
        m = _PIN_RE.match(req)
        if not m:
            problems.append(f"not an exact pin: {req!r}")
            continue
        name = canonicalize_name(m.group("name"))
        hashes = _HASH_RE.findall(rest)
        if not hashes:
            problems.append(f"{name}: no sha256 hash")
        if name in entries:
            problems.append(f"{name}: listed twice")
        entries[name] = {
            "version": m.group("version"),
            "marker": (m.group("marker") or "").strip(),
            "hashes": hashes,
        }
    return entries, problems


def lock_problems(runtime_text: str, dev_text: str, dev_only: set[str]) -> list[str]:
    """Problems in a runtime/dev lock pair; empty when the pair is acceptable."""
    runtime, problems = parse_lock(runtime_text)
    dev, dev_problems = parse_lock(dev_text)
    problems += [f"dev lock: {p}" for p in dev_problems]
    for name in sorted(dev_only):
        if name in runtime:
            problems.append(f"dev-only package {name} is in the runtime lock")
        if name not in dev:
            problems.append(f"dev package {name} missing from the dev lock")
    for name, e in sorted(runtime.items()):
        d = dev.get(name)
        if d is None:
            problems.append(f"{name} is in the runtime lock but not the dev lock")
        elif (d["version"], d["marker"]) != (e["version"], e["marker"]):
            problems.append(f"{name}: dev lock {d['version']} differs from runtime {e['version']}")
    sa = runtime.get("sqlalchemy")
    if sa is None:
        problems.append("sqlalchemy is not locked")
    elif not (Version("2.0") <= Version(sa["version"]) < Version("2.1")):
        problems.append(f"sqlalchemy {sa['version']} is outside >=2.0,<2.1")
    if "psycopg2-binary" not in runtime:
        problems.append("psycopg2-binary (the SQLAlchemy driver) is not locked")
    for banned in ("psycopg", "pymupdf"):
        if banned in runtime:
            problems.append(f"{banned} must not be in the runtime lock")
    return problems


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _dev_only_names() -> set[str]:
    dev = _pyproject()["project"]["optional-dependencies"]["dev"]
    return {canonicalize_name(Requirement(r).name) for r in dev}


def _applies(marker: str) -> bool:
    return not marker or Marker(marker).evaluate()


# --- static lock checks ------------------------------------------------------------------------


def test_lock_files_and_generator_are_checked_in():
    assert RUNTIME_LOCK.is_file() and DEV_LOCK.is_file()
    script = LOCK_SCRIPT.read_text(encoding="utf-8")
    for flag in ("--universal", "--python-version 3.11", "--generate-hashes", "--extra dev"):
        assert flag in script
    assert "--constraint requirements.lock" in script
    for lock in (RUNTIME_LOCK, DEV_LOCK):
        assert "scripts/lock-python-deps.sh" in lock.read_text(encoding="utf-8")[:300]


def test_runtime_and_dev_locks_are_exact_hashed_and_separated():
    assert (
        lock_problems(
            RUNTIME_LOCK.read_text(encoding="utf-8"),
            DEV_LOCK.read_text(encoding="utf-8"),
            _dev_only_names(),
        )
        == []
    )


def test_pyproject_keeps_dev_tools_out_of_runtime_dependencies():
    project = _pyproject()["project"]
    runtime = {canonicalize_name(Requirement(r).name) for r in project["dependencies"]}
    assert {"pytest", "ruff"} <= _dev_only_names()
    assert not runtime & _dev_only_names()


def test_every_direct_dependency_is_locked_within_its_specifier():
    runtime, _ = parse_lock(RUNTIME_LOCK.read_text(encoding="utf-8"))
    dev, _ = parse_lock(DEV_LOCK.read_text(encoding="utf-8"))
    project = _pyproject()["project"]
    checks = [(r, runtime) for r in project["dependencies"]]
    checks += [(r, dev) for r in project["optional-dependencies"]["dev"]]
    for spec, lock in checks:
        req = Requirement(spec)
        name = canonicalize_name(req.name)
        assert name in lock, f"{name} is not locked"
        assert req.specifier.contains(
            lock[name]["version"], prereleases=True
        ), f"{name}=={lock[name]['version']} does not satisfy {req.specifier}"


def test_sqlalchemy_is_held_below_2_1_with_the_psycopg2_driver():
    deps = {
        Requirement(r).name.lower(): Requirement(r) for r in _pyproject()["project"]["dependencies"]
    }
    spec = deps["sqlalchemy"].specifier
    assert spec.contains("2.0.55") and not spec.contains("2.1.0") and not spec.contains("2.1.0b1")
    assert "psycopg2-binary" in deps
    assert "pymupdf" not in deps and "psycopg" not in deps  # TC-01-003a replaced PyMuPDF with pypdf
    assert "pypdf" in deps


@pytest.mark.parametrize(
    "case",
    [
        "no_hash",
        "range_pin",
        "dev_in_runtime",
        "version_drift",
        "sqlalchemy_21",
        "no_driver",
        "psycopg3",
        "pymupdf",
        "option_line",
        "duplicate",
    ],
)
def test_lock_checker_rejects_bad_locks(case):
    h = "    --hash=sha256:" + "0" * 64
    good_rt = [f"sqlalchemy==2.0.55 \\\n{h}", f"psycopg2-binary==2.9.13 \\\n{h}"]
    good_dev = good_rt + [f"pytest==9.1.1 \\\n{h}"]
    rt, dev = list(good_rt), list(good_dev)
    if case == "no_hash":
        rt.append("six==1.17.0")
        dev.append("six==1.17.0")
    elif case == "range_pin":
        rt.append(f"six>=1.0 \\\n{h}")
        dev.append(f"six>=1.0 \\\n{h}")
    elif case == "dev_in_runtime":
        rt.append(f"pytest==9.1.1 \\\n{h}")
    elif case == "version_drift":
        dev[0] = f"sqlalchemy==2.0.54 \\\n{h}"
    elif case == "sqlalchemy_21":
        rt[0] = dev[0] = f"sqlalchemy==2.1.0 \\\n{h}"
    elif case == "no_driver":
        rt.pop(1)
        dev.pop(1)
    elif case == "psycopg3":
        rt.append(f"psycopg==3.2.0 \\\n{h}")
        dev.append(f"psycopg==3.2.0 \\\n{h}")
    elif case == "pymupdf":
        rt.append(f"pymupdf==1.24.0 \\\n{h}")
        dev.append(f"pymupdf==1.24.0 \\\n{h}")
    elif case == "option_line":
        rt.append("--index-url https://example.invalid/simple")
    elif case == "duplicate":
        rt.append(rt[0])
        dev.append(dev[0])
    assert lock_problems("\n".join(good_rt), "\n".join(good_dev), {"pytest"}) == []
    assert lock_problems("\n".join(rt), "\n".join(dev), {"pytest"}) != []


# --- installed environment (CI installs requirements-dev.lock) ---------------------------------


def test_installed_versions_equal_the_dev_lock():
    dev, _ = parse_lock(DEV_LOCK.read_text(encoding="utf-8"))
    wrong = {}
    for name, e in dev.items():
        if not _applies(e["marker"]):
            continue
        try:
            got = metadata.version(name)
        except metadata.PackageNotFoundError:
            got = None
        if got != e["version"]:
            wrong[name] = (got, e["version"])
    assert wrong == {}, (
        "installed (got, locked) differ; install with "
        "`pip install --require-hashes -r requirements-dev.lock`"
    )


def _requires(dist_name: str, extras: set[str]) -> list[tuple[str, set[str]]]:
    out = []
    for spec in metadata.requires(dist_name) or []:
        req = Requirement(spec)
        if req.marker is not None:
            envs = [{"extra": x} for x in (extras or {""})]
            if not any(req.marker.evaluate(env) for env in envs):
                continue
        out.append((canonicalize_name(req.name), set(req.extras)))
    return out


def test_runtime_lock_is_closed_over_the_app_requirements():
    """Walk the installed metadata from pyproject's runtime deps: every reachable package is in
    the runtime lock, and no lock entry for this platform is unreachable (no stray pins)."""
    runtime, _ = parse_lock(RUNTIME_LOCK.read_text(encoding="utf-8"))
    todo = []
    for spec in _pyproject()["project"]["dependencies"]:
        req = Requirement(spec)
        todo.append((canonicalize_name(req.name), set(req.extras)))
    seen: dict[str, set[str]] = {}
    while todo:
        name, extras = todo.pop()
        if name in seen and extras <= seen[name]:
            continue
        seen[name] = seen.get(name, set()) | extras
        todo.extend(_requires(name, seen[name]))
    missing = sorted(n for n in seen if n not in runtime)
    stray = sorted(n for n, e in runtime.items() if _applies(e["marker"]) and n not in seen)
    assert missing == [] and stray == [], {"missing": missing, "stray": stray}


def test_psycopg3_is_not_installed():
    # With psycopg 3 absent, SQLAlchemy cannot silently switch drivers; psycopg2 is the only one.
    with pytest.raises(metadata.PackageNotFoundError):
        metadata.version("psycopg")
    metadata.version("psycopg2-binary")


# --- AC1: fresh interpreter imports the app and connects through psycopg2 ----------------------

_PROBE = """
import json, importlib.metadata as md
import app.main  # noqa: F401  (full app import, routers included)
from sqlalchemy import text
from app.core.database import engine
with engine.connect() as conn:
    one = conn.execute(text("select 1")).scalar()
    server = conn.execute(text("show server_version")).scalar()
print(json.dumps({
    "dialect": engine.dialect.name, "driver": engine.dialect.driver,
    "dbapi": engine.dialect.dbapi.__name__, "select1": one, "server_major": server.split(".")[0],
    "sqlalchemy": md.version("sqlalchemy"), "psycopg2_binary": md.version("psycopg2-binary"),
}))
"""


def _probe_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI", "STRIPE"))}
    env.update(
        TRUST_COPILOT_TESTING="1",  # never read a .env file
        SESSION_SECRET="test-secret",
        APP_ENV="development",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env


def test_fresh_interpreter_imports_app_and_connects_with_psycopg2():
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=API_ROOT,
        env=_probe_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        tail = proc.stderr.strip().splitlines()[-1:] or ["(no stderr)"]
        db_down = "OperationalError" in proc.stderr and os.environ.get("TC_REQUIRE_DB") != "1"
        if db_down:
            pytest.skip(f"test Postgres unavailable locally ({tail[0][:200]}); CI requires it")
        pytest.fail(f"probe failed: {tail[0][:300]}")
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    runtime, _ = parse_lock(RUNTIME_LOCK.read_text(encoding="utf-8"))
    assert got["dialect"] == "postgresql"
    assert got["driver"] == "psycopg2" and got["dbapi"] == "psycopg2"
    assert got["select1"] == 1
    assert got["sqlalchemy"] == runtime["sqlalchemy"]["version"]
    assert got["psycopg2_binary"] == runtime["psycopg2-binary"]["version"]


# --- CI fails on any DB-test skip (Coordinator ruling for TC-02-002) ---------------------------

_CHILD_CONFTEST = """
from tests.conftest import pytest_runtest_makereport  # noqa: F401  (the hook under test)


def pytest_configure(config):
    for m in ("integration", "unit", "provider", "live_stack", "external_data"):
        config.addinivalue_line("markers", m)
"""

_CHILD_TESTS = """
import pytest


@pytest.mark.integration
def test_db_skip():
    pytest.skip("no seed rows")


@pytest.mark.integration
@pytest.mark.external_data
def test_db_external_data_skip():
    pytest.skip("dataset not checked in")


@pytest.mark.integration
@pytest.mark.xfail(reason="known", strict=False)
def test_db_xfail():
    raise AssertionError


@pytest.mark.unit
def test_unit_skip():
    pytest.skip("not a DB test")


@pytest.fixture
def needs_db():
    pytest.skip("Postgres not available")


@pytest.mark.integration
def test_db_fixture_skip(needs_db):
    pass
"""


def _run_child(tmp_path: Path, require_db: bool) -> dict[str, str]:
    (tmp_path / "conftest.py").write_text(_CHILD_CONFTEST, encoding="utf-8")
    (tmp_path / "test_child.py").write_text(_CHILD_TESTS, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "TC_REQUIRE_DB"}
    env["PYTHONPATH"] = str(API_ROOT)
    if require_db:
        env["TC_REQUIRE_DB"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider", str(tmp_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = {}
    for line in proc.stdout.splitlines():
        m = re.search(r"::(test_\w+) (PASSED|FAILED|SKIPPED|ERROR|XFAIL)\b", line)
        if m:
            out.setdefault(m.group(1), m.group(2))
    out["_rc"] = str(proc.returncode)
    return out


def test_db_test_skip_fails_when_db_is_required(tmp_path):
    got = _run_child(tmp_path, require_db=True)
    assert got["test_db_skip"] == "FAILED"
    assert got["test_db_fixture_skip"] == "ERROR"  # skip raised in setup -> setup error
    assert got["test_db_external_data_skip"] == "SKIPPED"
    assert got["test_unit_skip"] == "SKIPPED"
    assert got["test_db_xfail"] == "XFAIL"
    assert got["_rc"] == "1"


def test_db_test_skip_stays_a_skip_without_tc_require_db(tmp_path):
    got = _run_child(tmp_path, require_db=False)
    assert got["test_db_skip"] == "SKIPPED"
    assert got["test_db_fixture_skip"] == "SKIPPED"
    assert got["_rc"] == "0"
