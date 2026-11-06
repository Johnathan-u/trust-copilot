"""TC-02-005 release checks: pinned backend lint, type and unit gates.

Acceptance:
  TC-02-005-AC1  Pinned lint/type scope covers the critical contract modules
                 with no blanket suppression.
  TC-02-005-AC2  Unit tests execute without a database or external calls and
                 fail when a known regression is introduced.

Two layers:

* Static policy checks read repository files only. Each policy function is also
  exercised against synthetic bad inputs so it cannot pass vacuously.
* Execution checks run ruff, mypy and ``tests/unit`` from apps/api. The unit
  run points ``TC_TEST_DATABASE_URL`` at a closed local port and drops
  ``TC_REQUIRE_DB``. CI sets that flag on the parent pytest step;
  ``pytest_sessionstart`` would otherwise try to migrate the closed port and
  exit 3 before any unit test runs. A child process then patches job
  classification so an unexplained failure becomes retryable; the unit suite
  must fail. Set ``TC_REQUIRE_API_QUALITY=1`` (CI does) to turn a missing
  ruff or mypy into an error instead of a skip.

No network, production system or external account is contacted.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
API = REPO_ROOT / "apps" / "api"
PYPROJECT = API / "pyproject.toml"
RUFF_TOML = REPO_ROOT / "ruff.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEV_LOCK = API / "requirements-dev.lock"
RUNTIME_LOCK = API / "requirements.lock"
UNIT_DIR = API / "tests" / "unit"

# Critical contract modules. Lint and type both use this list.
REQUIRED_SCOPE = (
    "app/core/api_errors.py",
    "app/core/job_errors.py",
    "app/core/roles.py",
    "app/schemas/job.py",
    "app/services/model_outcomes.py",
    "app/services/source_registry_service.py",
)
PINNED_SELECT = ("E", "F", "I", "B")
# A code or category that turns the whole rule set off for a file or the project.
BLANKET_RULES = frozenset({"ALL", "E", "F", "I", "B"})
UNIT_IMPORTS = (
    "app.core.api_errors",
    "app.core.job_errors",
    "app.core.roles",
    "app.schemas.job",
    "app.services.model_outcomes",
    "app.services.source_registry_service",
)
# Strings that make conftest classify a module as integration. Unit files must
# not contain them; this release module is marked unit explicitly.
_INTEGRATION_HINTS = (
    "SessionLocal",
    "TestClient",
    "create_engine",
    "from app.main import",
    "import app.main",
    "engine.connect",
    "get_db",
)
_NOQA = re.compile(r"#\s*noqa(?P<rest>[^\n]*)", re.IGNORECASE)
_TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore(?P<rest>[^\n]*)", re.IGNORECASE)
_FILE_NOQA = re.compile(r"#\s*(?:ruff|flake8):\s*noqa\b", re.IGNORECASE)
_MYPY_IGNORE_FILE = re.compile(r"#\s*mypy:\s*ignore-errors\b", re.IGNORECASE)
_CODE = re.compile(r"[A-Z]+[0-9]+")
CLOSED_DB_URL = "postgresql://postgres:postgres@127.0.0.1:1/trustcopilot_quality_test"


def _load() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _mypy_config(project: dict | None = None) -> dict:
    tool = (project if project is not None else _load()).get("tool") or {}
    return tool.get("mypy") or {}


def _ruff_tables(project: dict) -> list[dict]:
    """Ruff tables that can suppress rules. Root ruff.toml is included."""
    tables = []
    ruff = (project.get("tool") or {}).get("ruff") or {}
    tables.append(ruff)
    if "lint" in ruff:
        tables.append(ruff["lint"])
    root = tomllib.loads(RUFF_TOML.read_text(encoding="utf-8"))
    tables.append(root)
    if "lint" in root:
        tables.append(root["lint"])
    return tables


def _ignore_values(table: dict) -> list[str]:
    ignore = table.get("ignore") or []
    return [str(item) for item in ignore]


def _per_file_ignores(table: dict) -> dict[str, list[str]]:
    raw = table.get("per-file-ignores") or table.get("per_file_ignores") or {}
    return {str(key): [str(item) for item in value] for key, value in raw.items()}


def _covers_scope(pattern: str, path: str) -> bool:
    pattern = pattern.replace("\\", "/")
    if fnmatch.fnmatch(path, pattern):
        return True
    if pattern.rstrip("/") in {path, path.rsplit("/", 1)[0]}:
        return True
    return False


def scope_problems(project: dict) -> list[str]:
    """The pinned mypy file list is the lint and type scope."""
    files = [str(item) for item in _mypy_config(project).get("files") or []]
    problems = []
    if files != list(REQUIRED_SCOPE):
        problems.append(f"scope {files!r} is not the pinned critical list")
    for path in REQUIRED_SCOPE:
        if not (API / path).is_file():
            problems.append(f"missing critical module {path}")
    return problems


def mypy_config_problems(cfg: dict) -> list[str]:
    problems = []
    if cfg.get("python_version") != "3.11":
        problems.append("mypy python_version is not 3.11")
    if cfg.get("follow_imports") != "silent":
        problems.append("follow_imports must be silent so reports stay on the scope")
    if cfg.get("ignore_errors") is True:
        problems.append("ignore_errors is set")
    if cfg.get("disallow_untyped_defs") is not True:
        problems.append("disallow_untyped_defs is off")
    if cfg.get("check_untyped_defs") is not True:
        problems.append("check_untyped_defs is off")
    if cfg.get("warn_unused_ignores") is not True:
        problems.append("warn_unused_ignores is off")
    codes = [str(item) for item in cfg.get("enable_error_code") or []]
    if "ignore-without-code" not in codes:
        problems.append("ignore-without-code is not enabled")
    disabled = [str(item) for item in cfg.get("disable_error_code") or []]
    if "ignore-without-code" in disabled:
        problems.append("ignore-without-code is disabled")
    for override in cfg.get("overrides") or []:
        if override.get("ignore_errors") is True:
            problems.append("mypy override sets ignore_errors")
        modules = override.get("module") or []
        if isinstance(modules, str):
            modules = [modules]
        for module in modules:
            text = str(module)
            if text in {"*", "app.*", "app.*.*"} or text.startswith("app.core"):
                problems.append(f"mypy override blankets {text}")
    excluded = cfg.get("exclude") or []
    for item in excluded:
        for path in REQUIRED_SCOPE:
            if _covers_scope(str(item), path):
                problems.append(f"mypy exclude covers {path}")
    return problems


def ruff_config_problems(project: dict) -> list[str]:
    problems = []
    root = tomllib.loads(RUFF_TOML.read_text(encoding="utf-8"))
    selected = [str(item) for item in (root.get("lint") or {}).get("select") or []]
    for code in PINNED_SELECT:
        if code not in selected:
            problems.append(f"root ruff select drops {code}")
    for table in _ruff_tables(project):
        blanket = BLANKET_RULES.intersection(_ignore_values(table))
        if blanket:
            problems.append(f"blanket ruff ignore {sorted(blanket)}")
        for pattern, codes in _per_file_ignores(table).items():
            if not BLANKET_RULES.intersection(codes):
                continue
            for path in REQUIRED_SCOPE:
                if _covers_scope(pattern, path):
                    problems.append(f"per-file ignore blankets {path}")
        for item in table.get("exclude") or []:
            for path in REQUIRED_SCOPE:
                if _covers_scope(str(item), path):
                    problems.append(f"ruff exclude covers {path}")
    return problems


def _specific_codes(rest: str) -> bool:
    body = rest.split("#", 1)[0].strip()
    if body.startswith(":"):
        body = body[1:].strip()
    if not body:
        return False
    parts = [part.strip() for part in body.split(",")]
    return all(_CODE.fullmatch(part) for part in parts)


def _specific_type_ignore(rest: str) -> bool:
    body = rest.split("#", 1)[0].strip()
    if not (body.startswith("[") and body.endswith("]") and len(body) > 2):
        return False
    parts = [part.strip() for part in body[1:-1].split(",")]
    return all(re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts)


def blanket_suppression_problems(files: dict[str, str]) -> list[str]:
    """Reject file-wide and code-less noqa / type-ignore. Coded ones stay allowed."""
    problems = []
    for name, text in files.items():
        if _FILE_NOQA.search(text):
            problems.append(f"{name}: file-wide noqa")
        if _MYPY_IGNORE_FILE.search(text):
            problems.append(f"{name}: mypy ignore-errors")
        for match in _NOQA.finditer(text):
            if not _specific_codes(match.group("rest")):
                problems.append(f"{name}: blanket noqa")
                break
        for match in _TYPE_IGNORE.finditer(text):
            if not _specific_type_ignore(match.group("rest")):
                problems.append(f"{name}: blanket type ignore")
                break
    return problems


def pin_problems(project: dict, dev_lock: str, runtime_lock: str) -> list[str]:
    dev = project["project"]["optional-dependencies"]["dev"]
    specs = {Requirement(item).name: Requirement(item) for item in dev}
    problems = []
    for name in ("ruff", "mypy"):
        spec = specs.get(name)
        if spec is None:
            problems.append(f"{name} is not a dev extra")
            continue
        if not spec.specifier or len(spec.specifier) != 1:
            problems.append(f"{name} is not an exact pin")
            continue
        pinned = next(iter(spec.specifier))
        if pinned.operator != "==":
            problems.append(f"{name} pin is {pinned.operator}, not ==")
        token = f"{name}=={pinned.version}"
        if token not in dev_lock:
            problems.append(f"{token} missing from the dev lock")
        if re.search(rf"(?m)^{name}==", runtime_lock):
            problems.append(f"{name} is in the runtime lock")
    runtime_names = {Requirement(item).name for item in project["project"]["dependencies"]}
    if "mypy" in runtime_names or "ruff" in runtime_names:
        problems.append("mypy or ruff is a runtime dependency")
    return problems


def ci_gate_problems(ci: str) -> list[str]:
    problems = []
    if "ruff --version" not in ci or "mypy --version" not in ci:
        problems.append("CI does not record ruff and mypy versions")
    if "--select E,F,I,B" not in ci:
        problems.append("CI does not select E,F,I,B for the critical modules")
    for path in REQUIRED_SCOPE:
        if path not in ci:
            problems.append(f"CI lint scope omits {path}")
    if not re.search(r"(?m)^\s*run:\s*mypy\s*$", ci):
        problems.append("CI does not run mypy on the pinned scope")
    if "TC_REQUIRE_API_QUALITY" not in ci:
        problems.append("CI does not require the API quality checks")
    steps = re.split(r"\n(?=\s+- name:)", ci)
    for label in ("Lint backend critical modules", "Type-check backend critical modules"):
        hits = [step for step in steps if f"- name: {label}" in step]
        if not hits:
            problems.append(f"CI is missing {label}")
        elif any("continue-on-error" in step for step in hits):
            problems.append(f"CI step {label} may not fail the build")
    return problems


def unit_suite_problems(files: dict[str, str]) -> list[str]:
    problems = []
    if len(files) < 4:
        problems.append("too few unit modules")
    blob = "\n".join(files.values())
    for module in UNIT_IMPORTS:
        if module not in blob:
            problems.append(f"{module} has no unit import")
    for name, text in files.items():
        if text.count("assert ") < 2:
            problems.append(f"{name}: fewer than 2 assertions")
        if re.search(
            r"pytest\.skip\(|pytest\.mark\.skip|pytestmark\s*=\s*pytest\.mark\.skip",
            text,
        ):
            problems.append(f"{name}: contains a skip")
        if "pytest.mark.unit" not in text:
            problems.append(f"{name}: missing unit marker")
        for hint in _INTEGRATION_HINTS:
            if hint in text:
                problems.append(f"{name}: integration hint {hint}")
    return problems


def _scoped_texts() -> dict[str, str]:
    return {path: (API / path).read_text(encoding="utf-8") for path in REQUIRED_SCOPE}


def _unit_texts() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8") for path in sorted(UNIT_DIR.glob("test_*.py"))
    }


# --------------------------------------------------------------------------- static


def test_scope_is_the_pinned_critical_modules():
    assert scope_problems(_load()) == []


def test_mypy_config_is_strict_on_that_scope_only():
    assert mypy_config_problems(_mypy_config()) == []


def test_ruff_config_has_no_blanket_ignore():
    assert ruff_config_problems(_load()) == []


def test_critical_modules_have_no_blanket_suppression():
    texts = _scoped_texts()
    assert len(texts) == len(REQUIRED_SCOPE)
    assert blanket_suppression_problems(texts) == []


def test_ruff_and_mypy_are_exact_dev_pins():
    assert (
        pin_problems(
            _load(),
            DEV_LOCK.read_text(encoding="utf-8"),
            RUNTIME_LOCK.read_text(encoding="utf-8"),
        )
        == []
    )


def test_ci_runs_the_pinned_lint_and_type_gates():
    assert ci_gate_problems(CI_WORKFLOW.read_text(encoding="utf-8")) == []


def test_unit_suite_covers_the_scope_without_db_hints():
    texts = _unit_texts()
    assert unit_suite_problems(texts) == []


# --------------------------------------------------------------------------- denial


def test_rejects_a_shrunk_or_shifted_scope():
    project = {"tool": {"mypy": {"files": ["app/core/roles.py"]}}}
    assert scope_problems(project) != []
    empty = {"tool": {"mypy": {"files": []}}}
    assert "pinned critical list" in scope_problems(empty)[0]


def test_rejects_mypy_blanket_settings():
    problems = mypy_config_problems(
        {
            "python_version": "3.12",
            "follow_imports": "skip",
            "ignore_errors": True,
            "disallow_untyped_defs": False,
            "check_untyped_defs": False,
            "warn_unused_ignores": False,
            "disable_error_code": ["ignore-without-code"],
            "exclude": ["app/core/*.py"],
            "overrides": [{"module": "app.*", "ignore_errors": True}],
        }
    )
    assert "mypy python_version is not 3.11" in problems
    assert "follow_imports must be silent so reports stay on the scope" in problems
    assert "ignore_errors is set" in problems
    assert "ignore-without-code is not enabled" in problems
    assert "ignore-without-code is disabled" in problems
    assert "mypy override sets ignore_errors" in problems
    assert "mypy override blankets app.*" in problems
    assert any("mypy exclude covers app/core/" in item for item in problems)


def test_rejects_blanket_ruff_ignore():
    project = {
        "tool": {
            "ruff": {
                "lint": {
                    "ignore": ["ALL"],
                    "per-file-ignores": {"app/core/*.py": ["E", "F", "I", "B"]},
                    "exclude": ["app/schemas/job.py"],
                }
            }
        }
    }
    problems = ruff_config_problems(project)
    assert any("blanket ruff ignore" in item for item in problems)
    assert any("per-file ignore blankets app/core/roles.py" in item for item in problems)
    assert any("ruff exclude covers app/schemas/job.py" in item for item in problems)


def test_rejects_blanket_suppressions_in_source():
    files = {
        "a.py": "import missing  # noqa\n",
        "b.py": "x: int = 'no'  # type: ignore\n",
        "c.py": "# ruff: noqa\nx = 1\n",
        "d.py": "x = 1  # type: ignore[assignment]\n",
        "e.py": "import os  # noqa: F401\n",
        "f.py": "# mypy: ignore-errors\n",
    }
    problems = blanket_suppression_problems(files)
    assert "a.py: blanket noqa" in problems
    assert "b.py: blanket type ignore" in problems
    assert "c.py: file-wide noqa" in problems
    assert "f.py: mypy ignore-errors" in problems
    assert not any(item.startswith("d.py") or item.startswith("e.py") for item in problems)


def test_rejects_unpinned_or_runtime_type_checker():
    project = {
        "project": {
            "dependencies": ["mypy>=1"],
            "optional-dependencies": {"dev": ["ruff>=0.5", "pytest"]},
        }
    }
    problems = pin_problems(project, "ruff==0.5.6 \\\n", "")
    assert "mypy is not a dev extra" in problems
    assert "ruff pin is >=, not ==" in problems
    assert "mypy or ruff is a runtime dependency" in problems


def test_rejects_ci_that_drops_the_gates():
    ci = """
      - name: Lint backend
        working-directory: apps/api
        continue-on-error: true
        run: ruff check .
    """
    problems = ci_gate_problems(ci)
    assert "CI does not record ruff and mypy versions" in problems
    assert "CI does not select E,F,I,B for the critical modules" in problems
    assert "CI does not run mypy on the pinned scope" in problems
    assert "CI is missing Lint backend critical modules" in problems
    assert "CI does not require the API quality checks" in problems


def test_rejects_a_hollow_unit_suite():
    files = {
        "test_a.py": "import pytest\npytestmark = pytest.mark.unit\n"
        "def test_one():\n    assert True\n",
    }
    problems = unit_suite_problems(files)
    assert "too few unit modules" in problems
    assert "test_a.py: fewer than 2 assertions" in problems
    assert "app.core.job_errors has no unit import" in problems
    skipped = {
        "test_a.py": "import pytest\npytestmark = pytest.mark.skip\n"
        "def test_one():\n    pytest.skip('no')\n    assert True\n    assert True\n",
        "test_b.py": "import pytest\npytestmark = pytest.mark.unit\n"
        "from app.core.api_errors import api_error_body\n"
        "from app.core.job_errors import classify\n"
        "from app.core.roles import can_admin\n"
        "from app.schemas.job import job_response\n"
        "from app.services.model_outcomes import outcome_spec\n"
        "from app.services.source_registry_service import KNOWN_SOURCES\n"
        "def test_two():\n    assert api_error_body\n    assert classify\n",
    }
    problems = unit_suite_problems(skipped)
    assert "test_a.py: contains a skip" in problems
    assert "test_a.py: missing unit marker" in problems


# --------------------------------------------------------------------------- execution


def _toolchain_reason() -> str | None:
    if shutil.which("ruff") is None:
        return "ruff not on PATH"
    if shutil.which("mypy") is None:
        return "mypy not on PATH"
    return None


_REASON = _toolchain_reason()
if _REASON and os.environ.get("TC_REQUIRE_API_QUALITY") == "1":
    raise RuntimeError(f"TC_REQUIRE_API_QUALITY=1 but API quality tools missing: {_REASON}")
needs_tools = pytest.mark.skipif(
    _REASON is not None, reason=f"API quality tools unavailable: {_REASON}"
)


def _run(
    args: list[str],
    cwd: Path = API,
    env: dict | None = None,
    timeout: int = 180,
    *,
    replace: bool = False,
):
    """Run a command. ``replace`` uses ``env`` as the whole environment.

    The default copies the parent environment and applies ``env`` on top.
    That copy puts ``TC_REQUIRE_DB`` back when the override only omits it,
    so the unit-suite child passes ``replace=True``.
    """
    if replace:
        merged = dict(env or {})
    else:
        merged = os.environ.copy()
        if env:
            merged.update(env)
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=merged,
        check=False,
    )


@pytest.fixture()
def probe_dir():
    path = Path(tempfile.mkdtemp(prefix=".tc-api-quality-", dir=API))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@needs_tools
def test_ruff_and_mypy_pass_on_the_pinned_scope():
    ruff = _run(["ruff", "check", "--select", "E,F,I,B", *REQUIRED_SCOPE])
    assert ruff.returncode == 0, ruff.stdout + ruff.stderr
    typed = _run(["mypy"])
    assert typed.returncode == 0, typed.stdout + typed.stderr
    assert "no issues found" in typed.stdout


@needs_tools
def test_ruff_fails_on_lint_and_import_regressions(probe_dir: Path):
    unsorted = probe_dir / "unsorted.py"
    unsorted.write_text(
        "import sys\nimport os\n\n\ndef value() -> str:\n    return os.linesep + sys.version\n",
        encoding="utf-8",
    )
    mutable = probe_dir / "mutable.py"
    mutable.write_text("def grow(items=[]):\n    return items\n", encoding="utf-8")
    undefined = probe_dir / "undefined.py"
    undefined.write_text("def broken() -> str:\n    return missing_name\n", encoding="utf-8")
    for path, rule in (
        (unsorted, "I001"),
        (mutable, "B006"),
        (undefined, "F821"),
    ):
        result = _run(["ruff", "check", "--select", "E,F,I,B", str(path)])
        assert result.returncode != 0, path.name
        assert rule in result.stdout + result.stderr


@needs_tools
def test_blanket_noqa_hides_a_ruff_error_and_the_policy_rejects_it(probe_dir: Path):
    hidden = probe_dir / "hidden.py"
    hidden.write_text("def broken() -> str:\n    return missing_name  # noqa\n", encoding="utf-8")
    result = _run(["ruff", "check", "--select", "E,F,I,B", str(hidden)])
    assert result.returncode == 0, result.stdout + result.stderr
    assert blanket_suppression_problems({"hidden.py": hidden.read_text(encoding="utf-8")}) == [
        "hidden.py: blanket noqa"
    ]


@needs_tools
def test_mypy_fails_on_a_bad_return_and_a_bare_type_ignore(probe_dir: Path):
    bad = probe_dir / "bad_types.py"
    bad.write_text(
        "def bad(value: int) -> str:\n    return value  # type: ignore\n",
        encoding="utf-8",
    )
    result = _run(["mypy", str(bad)])
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "ignore-without-code" in output
    clean = probe_dir / "clean_types.py"
    clean.write_text(
        "def add(left: int, right: int) -> int:\n    return left + right\n",
        encoding="utf-8",
    )
    ok = _run(["mypy", str(clean)])
    assert ok.returncode == 0, ok.stdout + ok.stderr


@needs_tools
def test_installed_ruff_and_mypy_match_the_pins():
    project = _load()
    specs = {
        Requirement(item).name: Requirement(item)
        for item in project["project"]["optional-dependencies"]["dev"]
    }
    ruff = _run(["ruff", "--version"])
    mypy = _run(["mypy", "--version"])
    assert ruff.returncode == 0 and mypy.returncode == 0
    assert f"ruff {next(iter(specs['ruff'].specifier)).version}" in ruff.stdout
    assert f"mypy {next(iter(specs['mypy'].specifier)).version}" in mypy.stdout


def child_unit_environ(extra: dict | None = None) -> dict[str, str]:
    """Environment for a ``tests/unit`` child.

    The closed port proves the suite does not open a database. ``TC_REQUIRE_DB``
    is removed, not inherited: with it set, ``pytest_sessionstart`` migrates
    before collection and exits 3 when that port is closed (CI sets the flag
    on the parent).
    """
    env = {key: value for key, value in os.environ.items()}
    env.pop("TC_REQUIRE_DB", None)
    env["TC_TEST_DATABASE_URL"] = CLOSED_DB_URL
    env["TRUST_COPILOT_TESTING"] = "1"
    env["TC_REQUIRE_API_QUALITY"] = ""
    if extra:
        env.update(extra)
    return env


def unit_child_env_problems(env: dict[str, str]) -> list[str]:
    """Reject a child that still requires Postgres or no longer uses the closed port."""
    problems = []
    if env.get("TC_REQUIRE_DB") == "1":
        problems.append("child still has TC_REQUIRE_DB=1")
    url = env.get("TC_TEST_DATABASE_URL") or ""
    if url != CLOSED_DB_URL or "127.0.0.1:1" not in url:
        problems.append("child database URL is not the closed 127.0.0.1:1 port")
    return problems


def _assert_unit_child_ran(output: str) -> None:
    assert "TC_REQUIRE_DB=1:" not in output
    assert "Postgres test database unavailable" not in output


def test_unit_child_env_drops_parent_database_requirement(monkeypatch):
    """Parent CI sets TC_REQUIRE_DB=1. The child must not keep it."""
    monkeypatch.setenv("TC_REQUIRE_DB", "1")
    monkeypatch.setenv(
        "TC_TEST_DATABASE_URL",
        "postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test",
    )
    env = child_unit_environ()
    assert unit_child_env_problems(env) == []
    assert "TC_REQUIRE_DB" not in env


def test_rejects_a_child_env_that_still_requires_the_database():
    kept = child_unit_environ()
    kept["TC_REQUIRE_DB"] = "1"
    assert unit_child_env_problems(kept) == ["child still has TC_REQUIRE_DB=1"]
    moved = child_unit_environ()
    moved["TC_TEST_DATABASE_URL"] = (
        "postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test"
    )
    assert unit_child_env_problems(moved) == [
        "child database URL is not the closed 127.0.0.1:1 port"
    ]


@needs_tools
def test_unit_suite_passes_with_the_database_port_closed():
    env = child_unit_environ()
    assert unit_child_env_problems(env) == []
    result = _run(
        [sys.executable, "-m", "pytest", "tests/unit", "-q", "-p", "no:cacheprovider", "-rs"],
        env=env,
        replace=True,
    )
    output = result.stdout + result.stderr
    _assert_unit_child_ran(output)
    assert result.returncode == 0, output
    assert "skipped" not in output
    assert "failed" not in output
    assert re.search(r"\d+ passed", output)


@needs_tools
def test_unit_suite_fails_when_unknown_errors_become_retryable(probe_dir: Path):
    plugin = probe_dir / "tc_api_quality_regression.py"
    plugin.write_text(
        "import app.core.job_errors as job_errors\n"
        "_original = job_errors._classify\n"
        "\n"
        "def _regressed(exc):\n"
        "    code = _original(exc)\n"
        "    if code == job_errors.INTERNAL_ERROR:\n"
        "        return job_errors.TIMEOUT\n"
        "    return code\n"
        "\n"
        "def pytest_configure(config):\n"
        "    job_errors._classify = _regressed\n",
        encoding="utf-8",
    )
    env = child_unit_environ(
        {"PYTHONPATH": str(probe_dir) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    )
    assert unit_child_env_problems(env) == []
    result = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_job_error_contract.py",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "tc_api_quality_regression",
        ],
        env=env,
        replace=True,
    )
    output = result.stdout + result.stderr
    _assert_unit_child_ran(output)
    assert result.returncode != 0, output
    assert "test_unknown_exception_is_terminal" in output
    assert "unknown failures must stay terminal" in output
