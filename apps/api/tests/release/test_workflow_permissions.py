"""TC-02-SEC-001 CI hardening: read-only GITHUB_TOKEN and no persisted checkout credentials.

Every GitHub Actions workflow under .github/workflows must:

* declare a workflow-level ``permissions`` block that grants no write scope;
* give every job an effective permissions block (its own, or the workflow's) as an
  explicit mapping, never ``write-all``/``read-all``;
* grant a write scope only at job level, only for scopes listed in
  ``ALLOWED_JOB_WRITES`` (currently none), and never ``contents: write``;
* set ``persist-credentials: false`` on every ``actions/checkout`` step;
* not use the ``pull_request_target`` trigger.

Static checks only: the YAML files are parsed, nothing is executed. Each policy
helper is also run against synthetic bad workflows so it cannot pass vacuously.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# (workflow file name, job id) -> scopes that job may hold with "write".
# Each entry needs a comment in the workflow explaining why. None today.
ALLOWED_JOB_WRITES: dict[tuple[str, str], set[str]] = {}

READ_LEVELS = {"read", "none"}


def _workflow_files() -> list[Path]:
    return sorted([*WORKFLOWS_DIR.glob("*.yml"), *WORKFLOWS_DIR.glob("*.yaml")])


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict), f"{path.name}: not a YAML mapping"
    return data


def _triggers(wf: dict):
    # PyYAML (YAML 1.1) reads the bare key ``on`` as boolean True.
    return wf.get("on", wf.get(True))


def _permission_problems(name: str, perms, *, job: str | None) -> list[str]:
    where = f"{name}:{job or '<workflow>'}"
    if perms is None:
        return [f"{where}: no permissions block"]
    if isinstance(perms, str):
        return [f"{where}: permissions must be an explicit mapping, not {perms!r}"]
    if not isinstance(perms, dict):
        return [f"{where}: permissions must be a mapping"]
    problems = []
    allowed = ALLOWED_JOB_WRITES.get((name, job), set()) if job else set()
    for scope, level in perms.items():
        if level in READ_LEVELS:
            continue
        if level != "write":
            problems.append(f"{where}: {scope}: unknown level {level!r}")
        elif scope == "contents":
            problems.append(f"{where}: contents: write is never allowed")
        elif scope not in allowed:
            problems.append(f"{where}: {scope}: write is not allow-listed")
    return problems


def workflow_problems(name: str, wf: dict) -> list[str]:
    problems = []
    triggers = _triggers(wf)
    trigger_names = triggers if isinstance(triggers, (list, dict)) else [triggers]
    if "pull_request_target" in trigger_names:
        problems.append(f"{name}: pull_request_target is not allowed")
    top = wf.get("permissions")
    problems += _permission_problems(name, top, job=None)
    jobs = wf.get("jobs") or {}
    if not jobs:
        problems.append(f"{name}: no jobs")
    for job_id, job in jobs.items():
        if "permissions" in job:
            problems += _permission_problems(name, job["permissions"], job=job_id)
        for i, step in enumerate(job.get("steps") or []):
            uses = str(step.get("uses", ""))
            if uses.split("@", 1)[0] == "actions/checkout":
                if (step.get("with") or {}).get("persist-credentials") is not False:
                    problems.append(
                        f"{name}:{job_id}: step {i} checkout without persist-credentials: false"
                    )
    return problems


def test_workflows_exist():
    names = {p.name for p in _workflow_files()}
    assert {"ci.yml", "deploy.yml"} <= names


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_workflow_is_least_privilege(path: Path):
    assert workflow_problems(path.name, _load(path)) == []


@pytest.mark.parametrize("path", _workflow_files(), ids=lambda p: p.name)
def test_every_checkout_sets_persist_credentials_false(path: Path):
    wf = _load(path)
    checkouts = [
        step
        for job in (wf.get("jobs") or {}).values()
        for step in job.get("steps") or []
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkouts, f"{path.name}: no checkout step found"
    for step in checkouts:
        assert (step.get("with") or {}).get("persist-credentials") is False


def test_ci_build_job_has_read_only_contents():
    wf = _load(WORKFLOWS_DIR / "ci.yml")
    assert wf["permissions"] == {"contents": "read"}
    for job in wf["jobs"].values():
        assert job.get("permissions", wf["permissions"]).get("contents") == "read"


def test_deploy_has_no_write_scope():
    wf = _load(WORKFLOWS_DIR / "deploy.yml")
    for job_id, job in wf["jobs"].items():
        perms = job.get("permissions", wf.get("permissions")) or {}
        assert "write" not in perms.values(), job_id


# --- denial cases: the policy helper rejects synthetic bad workflows ---------------

_GOOD_STEP = {"uses": "actions/checkout@v4", "with": {"persist-credentials": False}}


def _wf(top=None, job_perms=None, step=None, on=None):
    job = {"runs-on": "ubuntu-latest", "steps": [step or _GOOD_STEP]}
    if job_perms is not None:
        job["permissions"] = job_perms
    wf = {True: on or {"push": None}, "jobs": {"build": job}}
    if top is not None:
        wf["permissions"] = top
    return wf


def test_policy_accepts_a_good_workflow():
    assert workflow_problems("x.yml", _wf(top={"contents": "read"})) == []


@pytest.mark.parametrize(
    "wf",
    [
        _wf(),  # no workflow-level block
        _wf(top="write-all"),
        _wf(top="read-all"),
        _wf(top={"contents": "write"}),
        _wf(top={"packages": "write"}),  # write at workflow level
        _wf(top={"contents": "read"}, job_perms={"contents": "write"}),
        _wf(top={"contents": "read"}, job_perms={"packages": "write"}),  # not allow-listed
        _wf(top={"contents": "read"}, job_perms={"contents": "admin"}),
        _wf(top={"contents": "read"}, step={"uses": "actions/checkout@v4"}),
        _wf(
            top={"contents": "read"},
            step={"uses": "actions/checkout@v4", "with": {"persist-credentials": True}},
        ),
        _wf(
            top={"contents": "read"},
            step={"uses": "actions/checkout@v4", "with": {"persist-credentials": "false"}},
        ),
        _wf(top={"contents": "read"}, on={"pull_request_target": None}),
    ],
)
def test_policy_rejects_bad_workflows(wf):
    assert workflow_problems("x.yml", wf) != []
