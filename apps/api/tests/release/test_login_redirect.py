"""TC-07-003 named release test for post-login ``next`` targets.

The check lives in the web app. No API route reads ``next``. This file runs
the vitest files that already cover the acceptance criteria:

* ``apps/web/lib/post-login-path.test.ts`` (dangerous targets and safe paths)
* ``apps/web/tests/unit/login-next.test.ts`` (password, MFA, enrolment)
* ``apps/web/tests/unit/middleware.test.ts`` (pathname written into ``next``)

CI sets ``TC_REQUIRE_WEB_TOOLCHAIN=1``. A missing Node 24 or vitest binary
then fails this module at import. Without that flag the test skips.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
WEB = REPO_ROOT / "apps" / "web"
VITEST_FILES = (
    "lib/post-login-path.test.ts",
    "tests/unit/login-next.test.ts",
    "tests/unit/middleware.test.ts",
)
# Counts on the batch-4 baseline. A later test may add cases. Removing one
# of these checks fails this release test.
MINIMUM_TESTS = {
    "post-login-path.test.ts": 7,
    "login-next.test.ts": 3,
    "middleware.test.ts": 4,
}


def _toolchain_reason() -> str | None:
    node = shutil.which("node")
    if not node:
        return "node not on PATH"
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    if not out.stdout.startswith("v24."):
        return f"Node 24 required, found {out.stdout.strip()!r}"
    if not (WEB / "node_modules" / ".bin" / "vitest").exists():
        return "apps/web/node_modules/.bin/vitest missing (run npm ci --ignore-scripts)"
    return None


_REASON = _toolchain_reason()
if _REASON and os.environ.get("TC_REQUIRE_WEB_TOOLCHAIN") == "1":
    raise RuntimeError(f"TC_REQUIRE_WEB_TOOLCHAIN=1 but web toolchain unavailable: {_REASON}")

needs_toolchain = pytest.mark.skipif(
    _REASON is not None,
    reason=f"web toolchain unavailable: {_REASON}",
)


def _vitest() -> str:
    return str(WEB / "node_modules" / ".bin" / "vitest")


@needs_toolchain
def test_login_redirect_web_checks(tmp_path: Path) -> None:
    """Run the web checks that reject dangerous post-login URLs."""
    report = tmp_path / "vitest.json"
    env = {**os.environ, "CI": "1", "NO_COLOR": "1", "FORCE_COLOR": "0"}
    result = subprocess.run(
        [
            _vitest(),
            "run",
            "--reporter=default",
            "--reporter=json",
            f"--outputFile={report}",
            *VITEST_FILES,
        ],
        cwd=WEB,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        check=False,
    )
    output = result.stdout + result.stderr
    print(output)
    code = result.returncode
    assert code == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["numFailedTests"] == 0
    assert data["numPendingTests"] == 0
    assert data["numTodoTests"] == 0
    assert data["numPassedTests"] == data["numTotalTests"]
    assert data["numPassedTests"] >= sum(MINIMUM_TESTS.values())
    by_name = {Path(row["name"]).name: row for row in data["testResults"]}
    assert set(MINIMUM_TESTS) <= set(by_name)
    for name, minimum in MINIMUM_TESTS.items():
        row = by_name[name]
        assert row["status"] == "passed", name
        assert len(row["assertionResults"]) >= minimum, name
