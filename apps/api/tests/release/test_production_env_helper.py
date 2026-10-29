"""TC-03-001a: app code must use is_production_env(), not a raw app_env comparison."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

API_APP = Path(__file__).resolve().parents[2] / "app"
# The helper itself is the only place a production comparison of the environment may live.
ALLOWLIST = {Path("core/session.py")}

# A direct production check on app_env. The helper does not use this shape.
_RAW_PRODUCTION_COMPARE = re.compile(
    r"""(?x)
    (?:
        \bapp_env\b \s* (?:==|!=) \s* [\'\"]production[\'\"]
        |
        getattr\( [^)\n]* \bapp_env\b [^)\n]* \) \s* (?:==|!=) \s* [\'\"]production[\'\"]
    )
    """
)


def _app_sources() -> list[tuple[Path, str]]:
    return [
        (path.relative_to(API_APP), path.read_text(encoding="utf-8"))
        for path in API_APP.rglob("*.py")
    ]


def test_no_raw_app_env_production_comparison_outside_the_helper():
    offenders: list[str] = []
    for rel, src in _app_sources():
        if rel in ALLOWLIST:
            continue
        for lineno, line in enumerate(src.splitlines(), start=1):
            if _RAW_PRODUCTION_COMPARE.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert offenders == []


def test_helper_is_allowlisted_and_present():
    helper = (API_APP / "core" / "session.py").read_text(encoding="utf-8")
    assert "def is_production_env(" in helper
    assert Path("core/session.py") in ALLOWLIST


@pytest.mark.parametrize(
    "rel",
    [
        "api/routes/auth.py",
        "api/routes/workspaces.py",
        "api/routes/trust_requests.py",
        "main.py",
        "services/billing_provider.py",
        "services/message_providers/selection.py",
        "core/config.py",
    ],
)
def test_listed_call_sites_use_the_helper(rel):
    src = (API_APP / rel).read_text(encoding="utf-8")
    assert "is_production_env(" in src
    assert _RAW_PRODUCTION_COMPARE.search(src) is None
