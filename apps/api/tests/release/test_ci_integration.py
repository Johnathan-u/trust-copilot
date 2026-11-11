"""TC-02-007: CI starts real services and required checks cannot skip silently.

Parses `.github/workflows/ci.yml` and runs the gates against deliberate failures.
The database, storage and browser steps are not started here. Negative controls
use a child pytest, the release-spec shell, or the e2e report checker.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from tests.conftest import _pytestmark_names

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[4]
API = ROOT / "apps" / "api"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
CHECKER = ROOT / "scripts" / "ci" / "check-release-e2e-report.mjs"
UI23 = "e2e/release/ui-23.spec.ts"
# 16 direct cases plus loops of 4, 3, 2, 3 and 2 in ui-23.spec.ts.
UI23_TESTS = 30
UI23_CALL_SITES = 21

_REQUIRE_FLAGS = (
    "TC_REQUIRE_DB",
    "TC_REQUIRE_STORAGE",
    "TC_REQUIRE_WEB_TOOLCHAIN",
    "TC_REQUIRE_API_QUALITY",
)


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job_steps(job: str) -> list[dict]:
    return list(_workflow()["jobs"][job]["steps"])


def _step(job: str, name: str) -> dict:
    return next(step for step in _job_steps(job) if step.get("name") == name)


def _e2e_script() -> str:
    return _step("web-release-e2e", "Run release Playwright specs")["run"]


def _candidate_block(script: str) -> str:
    start = script.index("candidates=(")
    end = script.index("\ndone\n", start)
    return script[start : end + len("\ndone\n")]


def _candidates(script: str) -> list[str]:
    block = _candidate_block(script)
    return re.findall(r"e2e/release/[\w.-]+\.spec\.ts", block)


def _required_specs(script: str) -> list[tuple[str, str]]:
    specs = re.findall(r"--require-spec\s+(\S+)", script)
    floors = re.findall(r"--min-tests\s+(\d+)", script)
    assert len(specs) == len(floors)
    return list(zip(specs, floors, strict=True))


def _redact(text: str) -> str:
    redacted = re.sub(r"postgresql://[^@\s'\"]+@", "postgresql://***@", text)
    for key in ("DATABASE_URL", "TC_TEST_DATABASE_URL", "TC_TEST_S3_SECRET_KEY", "S3_SECRET_KEY"):
        value = os.environ.get(key) or ""
        if value:
            redacted = redacted.replace(value, "***")
    return redacted[-800:]


def _run_child(
    source: str, *, updates: dict[str, str], drops: tuple[str, ...]
) -> subprocess.CompletedProcess[str]:
    directory = API / "tests" / "release" / f"_tc02007_{uuid.uuid4().hex}"
    directory.mkdir()
    try:
        (directory / "test_probe.py").write_text(source, encoding="utf-8")
        # A collected test keeps pytest from exiting 5 when the only other
        # module is a collection-time skip. The full suite has the same shape.
        (directory / "test_anchor.py").write_text(
            "def test_anchor():\n    assert True\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        for key in drops:
            env.pop(key, None)
        env.update(updates)
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(directory),
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            cwd=API,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_database_storage_and_chromium_wait_until_ready():
    build = _job_steps("build")
    names = [step.get("name", "") for step in build]
    postgres = _step("build", "Start isolated Postgres (pgvector) for this run")
    storage = _step("build", "Start isolated S3-compatible storage (moto) for this run")
    pg_script = postgres["run"]
    s3_script = storage["run"]
    pg_done = pg_script.index("\ndone\n")
    s3_done = s3_script.index("\ndone\n")

    assert pg_script.count("pg_isready -h 127.0.0.1") == 2
    assert "seq 1 60" in pg_script
    assert pg_script.rindex("pg_isready -h 127.0.0.1") > pg_done
    assert "@sha256:" in postgres["env"]["PG_IMAGE"]

    image = storage["env"]["S3_IMAGE"]
    assert image.startswith("motoserver/moto:")
    assert "@sha256:" in image
    assert "minio" not in image.lower()
    assert "seq 1 60" in s3_script
    assert s3_script.count("/moto-api/") == 2
    assert s3_script.rindex("/moto-api/") > s3_done
    assert "127.0.0.1:9000:5000" in s3_script
    assert "test-raw" in s3_script and "test-exports" in s3_script
    assert "TC_TEST_S3_ENDPOINT=http://127.0.0.1:9000" in s3_script
    assert "TC_TEST_S3_ACCESS_KEY" in s3_script and "TC_TEST_S3_SECRET_KEY" in s3_script
    assert "::add-mask::" in s3_script
    assert names.index(storage["name"]) < names.index("Run backend tests")

    for job, step_name, before in (
        ("build", "Install Chromium for integrated inbox acceptance", "Run backend tests"),
        ("web-release-e2e", "Install Playwright Chromium", "Run release Playwright specs"),
    ):
        steps = _job_steps(job)
        step_names = [step.get("name", "") for step in steps]
        step = _step(job, step_name)
        assert "playwright install --with-deps chromium" in step["run"]
        assert "continue-on-error" not in yaml.safe_dump(step)
        assert step_names.index(step_name) < step_names.index(before)


def test_backend_step_requires_db_storage_web_and_api_quality():
    env = _step("build", "Run backend tests")["env"]
    for flag in _REQUIRE_FLAGS:
        assert str(env[flag]) == "1", flag
    conftest = (API / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'os.environ.get("TC_TEST_S3_ENDPOINT")' in conftest
    assert 'os.environ.get("TC_TEST_S3_ACCESS_KEY")' in conftest
    assert 'os.environ.get("TC_TEST_S3_SECRET_KEY")' in conftest


def test_every_listed_release_spec_is_required():
    script = _e2e_script()
    assert "not on this revision" not in script
    candidates = _candidates(script)
    required = _required_specs(script)
    required_names = [spec for spec, _floor in required]
    assert candidates
    assert required_names == list(dict.fromkeys(required_names))
    assert set(candidates) == set(required_names)
    floors = dict(required)
    assert floors[UI23] == str(UI23_TESTS)
    text = (ROOT / "apps" / "web" / UI23).read_text(encoding="utf-8")
    assert len(re.findall(r"(?m)^[ \t]*test[(`]", text)) == UI23_CALL_SITES


def test_missing_candidate_spec_fails_the_list_step(tmp_path):
    script = _e2e_script()
    gate = _candidate_block(script)
    assert "missing release spec" in gate
    for spec in _candidates(script):
        path = tmp_path / spec
        path.parent.mkdir(parents=True, exist_ok=True)
        if spec != UI23:
            path.write_text("// present\n", encoding="utf-8")
    missing = subprocess.run(
        ["bash", "-c", gate],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert missing.returncode != 0
    assert "ERROR: missing release spec" in missing.stdout
    assert UI23 in missing.stdout

    for spec in _candidates(script):
        path = tmp_path / spec
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("// present\n", encoding="utf-8")
    present = subprocess.run(
        ["bash", "-c", gate],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert present.returncode == 0, present.stdout + present.stderr


def test_checker_fails_when_a_required_spec_is_missing(tmp_path):
    report = tmp_path / "release-e2e.json"
    html = tmp_path / "playwright-report"
    axe = tmp_path / "axe"
    html.mkdir()
    axe.mkdir()
    (html / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (axe / "axe-sample.json").write_text(
        json.dumps({"violationCount": 0, "violations": []}),
        encoding="utf-8",
    )
    report.write_text(
        json.dumps(
            {
                "stats": {"unexpected": 0, "skipped": 0, "expected": 1, "flaky": 0},
                "suites": [
                    {
                        "specs": [
                            {
                                "file": "e2e/release/design-tokens.spec.ts",
                                "ok": True,
                                "tests": [{"status": "expected"}],
                            }
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            "node",
            str(CHECKER),
            "--report",
            str(report),
            "--html-report",
            str(html),
            "--axe-dir",
            str(axe),
            "--require-spec",
            UI23,
            "--min-tests",
            str(UI23_TESTS),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode != 0
    assert "spec did not run" in proc.stderr
    assert UI23 in proc.stderr


def test_blind_pack_module_is_marked_external_data():
    names = _pytestmark_names(API / "tests" / "test_trust_scoring_blind.py")
    assert names == {"external_data"}


def test_deliberate_integration_skip_fails_under_tc_require_db():
    proc = _run_child(
        "import pytest\n"
        "pytestmark = pytest.mark.integration\n"
        "def test_deliberate_integration_skip():\n"
        "    pytest.skip('deliberate integration skip')\n",
        updates={"TC_REQUIRE_DB": "1"},
        drops=("TC_REQUIRE_STORAGE",),
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, _redact(output)
    assert "DB (integration) test skipped instead of running" in output


def test_unmarked_module_skip_fails_under_tc_require_db():
    proc = _run_child(
        "import pytest\n"
        "def test_should_not_run():\n"
        "    raise AssertionError('module skip should have prevented this')\n"
        "pytest.skip('unmarked module-level skip', allow_module_level=True)\n",
        updates={"TC_REQUIRE_DB": "1"},
        drops=("TC_REQUIRE_STORAGE",),
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, _redact(output)
    assert "collection-time skip is not allowed" in output


def test_marked_external_data_module_skip_stays_allowed():
    proc = _run_child(
        "import pytest\n"
        "pytestmark = pytest.mark.external_data\n"
        "pytest.skip('external_data: synthetic allowed skip', allow_module_level=True)\n",
        updates={"TC_REQUIRE_DB": "1"},
        drops=("TC_REQUIRE_STORAGE",),
    )
    output = proc.stdout + proc.stderr
    assert "collection-time skip is not allowed" not in output
    assert proc.returncode == 0, _redact(output)


def test_storage_unavailability_fails_under_tc_require_storage():
    proc = _run_child(
        "def test_storage_gate_reaches_the_test():\n    assert True\n",
        updates={
            "TC_REQUIRE_STORAGE": "1",
            "TC_TEST_S3_ENDPOINT": "http://127.0.0.1:1",
        },
        drops=("TC_REQUIRE_DB",),
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, _redact(output)
    assert "TC_REQUIRE_STORAGE=1: object storage unavailable" in output
