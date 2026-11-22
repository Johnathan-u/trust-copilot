"""TC-02-009: CI keeps redacted release evidence and a written retention period.

Parses the workflow files. The database, browsers and Actions are not started.
Negative cases pass a modified workflow document to the same checker.
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = ROOT / ".github" / "workflows"
REDACTOR = ROOT / "scripts" / "ci" / "redact-playwright-artifacts.py"
RUNBOOK = ROOT / "docs" / "ops" / "ci-evidence.md"
NOTE = ROOT / "docs" / "release" / "tickets" / "TC-02-009.md"
WEB = ROOT / "apps" / "web"
CI_JOBS = ("build", "web-release-e2e")
EVIDENCE_MARK = "TC-02-009 evidence"
RETENTION_DAYS = 14

# Values that must not be written to a job log. Mask registration and
# GITHUB_ENV assignment are the two allowed uses.
_MASKED_NAMES = (
    "PG_PASSWORD",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "DATABASE_URL",
    "TC_TEST_DATABASE_URL",
    "TC_TEST_S3_ACCESS_KEY",
    "TC_TEST_S3_SECRET_KEY",
    "SESSION_SECRET",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
    "URL",
)

_PAGES_ACTIONS = (
    "actions/deploy-pages",
    "actions/upload-pages-artifact",
    "peaceiris/actions-gh-pages",
    "jamesives/github-pages-deploy-action",
)

_UNGUARDED_PAGES = """\
name: Pages
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/deploy-pages@v4
"""

_SUCCESS_IF_PAGES = """\
name: Pages
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
jobs:
  deploy:
    runs-on: ubuntu-latest
    if: success()
    steps:
      - uses: actions/deploy-pages@v4
"""

_GUARDED_PAGES = """\
name: Pages
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
jobs:
  deploy:
    runs-on: ubuntu-latest
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    steps:
      - uses: actions/deploy-pages@v4
"""


def _load_workflows() -> dict[str, str]:
    paths = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    return {path.name: path.read_text(encoding="utf-8") for path in paths}


def _load_configs() -> dict[str, str]:
    configs = sorted(WEB.glob("playwright*.ts"))
    return {path.name: path.read_text(encoding="utf-8") for path in configs}


def _jobs(doc: dict) -> dict:
    jobs = doc.get("jobs") or {}
    return jobs if isinstance(jobs, dict) else {}


def _steps(job: dict) -> list:
    steps = job.get("steps") or []
    return steps if isinstance(steps, list) else []


def _trigger(doc: dict) -> dict:
    raw = doc.get(True, doc.get("on"))
    if isinstance(raw, str):
        return {raw: {}}
    if isinstance(raw, list):
        return {str(item): {} for item in raw}
    if isinstance(raw, dict):
        return raw
    return {}


def _evidence_runs(job: dict) -> str:
    parts: list[str] = []
    for step in _steps(job):
        run = step.get("run")
        if isinstance(run, str) and EVIDENCE_MARK in run:
            parts.append(run)
    return "\n".join(parts)


def _walk_strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _digests(job: dict) -> list[str]:
    found: list[str] = []
    for text in _walk_strings(job):
        for digest in re.findall(r"sha256:[0-9a-f]{64}", text):
            if digest not in found:
                found.append(digest)
    return found


def _is_log_echo(line: str) -> bool:
    if "::add-mask::" in line:
        return False
    if "GITHUB_ENV" in line and ">>" in line:
        return False
    return bool(re.search(r"(?:^|[;&|]\s*)(?:echo|printf)\b", line.strip()))


def _expanded_names(line: str) -> list[str]:
    found = []
    for name in _MASKED_NAMES:
        if re.search(rf"(?:\$\{{{name}\b|\$\b{name}\b)", line):
            found.append(name)
    return found


def _conclusion_requires_success(condition: str) -> bool:
    normalized = condition.replace(" ", "")
    if "github.event.workflow_run.conclusion" not in normalized:
        return False
    if "failure" in normalized or "cancelled" in normalized:
        return False
    return "success" in normalized


def _step_deploys_pages(step: dict) -> bool:
    uses = str(step.get("uses") or "").lower()
    return any(uses.startswith(action) for action in _PAGES_ACTIONS)


def _job_deploys_pages(job: dict) -> bool:
    return any(_step_deploys_pages(step) for step in _steps(job))


def _pages_guarded(job: dict) -> bool:
    if _conclusion_requires_success(str(job.get("if") or "")):
        return True
    for step in _steps(job):
        if not _step_deploys_pages(step):
            continue
        step_if = str(step.get("if") or "")
        if not _conclusion_requires_success(step_if):
            return False
    return True


def _upload_problems(filename: str, doc: dict) -> list[str]:
    problems = []
    for job_name, job in _jobs(doc).items():
        if not isinstance(job, dict):
            continue
        for index, step in enumerate(_steps(job), start=1):
            uses = str(step.get("uses") or "")
            if not uses.startswith("actions/upload-artifact"):
                continue
            days = (step.get("with") or {}).get("retention-days")
            if days != RETENTION_DAYS:
                label = step.get("name") or f"step {index}"
                problems.append(
                    f"{filename} job {job_name} upload {label!r} "
                    f"retention-days is {days!r}, expected {RETENTION_DAYS}"
                )
    return problems


def _echo_problems(filename: str, doc: dict) -> list[str]:
    problems = []
    for job_name, job in _jobs(doc).items():
        if not isinstance(job, dict):
            continue
        for step in _steps(job):
            run = step.get("run")
            if not isinstance(run, str):
                continue
            for line in run.splitlines():
                if not _is_log_echo(line):
                    continue
                if "${{ secrets." in line:
                    problems.append(f"{filename} job {job_name} echoes a secrets context value")
                for name in _expanded_names(line):
                    problems.append(f"{filename} job {job_name} echoes {name} without a mask")
    return problems


def _pages_problems(filename: str, doc: dict) -> list[str]:
    workflow_run = _trigger(doc).get("workflow_run")
    if not isinstance(workflow_run, dict):
        return []
    types = workflow_run.get("types") or []
    if isinstance(types, str):
        types = [types]
    if types and "completed" not in types:
        return []
    problems = []
    for job_name, job in _jobs(doc).items():
        if not isinstance(job, dict) or not _job_deploys_pages(job):
            continue
        if not _pages_guarded(job):
            problems.append(
                f"{filename} job {job_name} deploys Pages on workflow_run "
                "without requiring a successful conclusion"
            )
    return problems


def _image_problems(job_name: str, job: dict, evidence: str) -> list[str]:
    digests = _digests(job)
    if not digests:
        if "image: none" not in evidence:
            return [f"{job_name} evidence does not print image: none"]
        return []
    problems = []
    for digest in digests:
        if not re.search(rf"image:.*{re.escape(digest)}", evidence):
            problems.append(f"{job_name} evidence does not print image digest {digest}")
    return problems


def _command_problems(job_name: str, evidence: str) -> list[str]:
    problems = []
    if "command:" not in evidence:
        problems.append(f"{job_name} evidence does not print the test command")
    if not re.search(r"totals:\s*passed=\S+\s+failed=\S+\s+skipped=", evidence):
        problems.append(f"{job_name} evidence does not print passed, failed and skipped totals")
    if job_name == "build" and "command: pytest -rs" not in evidence:
        problems.append("build evidence command is not pytest -rs")
    if job_name != "web-release-e2e":
        return problems
    if "npx --no-install playwright test" not in evidence:
        problems.append("web-release-e2e evidence does not print the Playwright command")
    if "check-release-e2e-report.mjs" not in evidence:
        problems.append("web-release-e2e evidence does not print the axe command")
    if not re.search(r"playwright:\s*passed=\S+\s+failed=\S+\s+skipped=", evidence):
        problems.append("web-release-e2e evidence does not print Playwright totals")
    if not re.search(r"axe:\s*passed=\S+\s+failed=\S+\s+skipped=", evidence):
        problems.append("web-release-e2e evidence does not print axe totals")
    return problems


def _job_evidence_problems(doc: dict) -> list[str]:
    problems = []
    jobs = _jobs(doc)
    for job_name in CI_JOBS:
        job = jobs.get(job_name)
        if not isinstance(job, dict):
            problems.append(f"ci.yml has no {job_name} job")
            continue
        evidence = _evidence_runs(job)
        if EVIDENCE_MARK not in evidence:
            problems.append(f"{job_name} does not print the evidence block")
            continue
        if "commit: ${{ github.sha }}" not in evidence:
            problems.append(f"{job_name} evidence does not print the commit SHA")
        problems.extend(_image_problems(job_name, job, evidence))
        problems.extend(_command_problems(job_name, evidence))
    return problems


def _step_run(job: dict, name: str) -> str:
    for step in _steps(job):
        if step.get("name") == name:
            run = step.get("run")
            return run if isinstance(run, str) else ""
    return ""


def _mask_problems(doc: dict) -> list[str]:
    problems = []
    build = _jobs(doc).get("build")
    if not isinstance(build, dict):
        return ["ci.yml has no build job to mask generated secrets"]
    postgres = _step_run(build, "Start isolated Postgres (pgvector) for this run")
    storage = _step_run(build, "Start isolated S3-compatible storage (moto) for this run")
    password_mask = 'echo "::add-mask::$PG_PASSWORD"'
    if password_mask not in postgres:
        problems.append("Postgres password is not masked")
    elif postgres.find(password_mask) > postgres.find('POSTGRES_PASSWORD="$PG_PASSWORD"'):
        problems.append("Postgres password is used before it is masked")
    for name, use in (
        ("S3_ACCESS_KEY", 'AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"'),
        ("S3_SECRET_KEY", 'AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"'),
    ):
        marker = f'echo "::add-mask::${name}"'
        if marker not in storage:
            problems.append(f"{name} is not masked")
        elif storage.find(marker) > storage.find(use):
            problems.append(f"{name} is used before it is masked")
    return problems


def _redaction_problems(doc: dict, redactor_source: str) -> list[str]:
    problems = []
    if "zipfile" not in redactor_source or "trace" not in redactor_source.lower():
        problems.append("Playwright redactor does not rewrite trace zip members")
    jobs = _jobs(doc)
    for job_name in CI_JOBS:
        job = jobs.get(job_name)
        if not isinstance(job, dict):
            continue
        steps = _steps(job)
        redact_at = None
        for index, step in enumerate(steps):
            run = step.get("run")
            if isinstance(run, str) and "redact-playwright-artifacts.py" in run:
                redact_at = index
                if "python3" not in run:
                    problems.append(f"{job_name} redactor is not invoked with python3")
                if "playwright-report" not in run or "test-results" not in run:
                    problems.append(f"{job_name} redactor does not cover reports and traces")
        if redact_at is None:
            problems.append(f"{job_name} does not run the Playwright redactor")
            continue
        for step in steps[redact_at + 1 :]:
            uses = str(step.get("uses") or "")
            if not uses.startswith("actions/upload-artifact"):
                continue
            blob = yaml.safe_dump(step.get("with") or {})
            if "playwright-report" not in blob and "test-results" not in blob:
                continue
            condition = str(step.get("if") or "")
            if "redact-playwright" not in condition:
                label = step.get("name") or uses
                problems.append(f"{job_name} uploads {label} before a successful redaction")
    return problems


def _trace_problems(configs: dict[str, str]) -> list[str]:
    problems = []
    default = configs.get("playwright.config.ts", "")
    if "trace: 'on-first-retry'" not in default:
        problems.append("playwright.config.ts does not keep trace on-first-retry")
    for name, text in configs.items():
        if name == "playwright.config.ts":
            continue
        if "trace: 'off'" not in text:
            problems.append(f"{name} does not set trace off")
    return problems


def evidence_problems(
    workflows: dict[str, str],
    *,
    redactor_source: str,
    configs: dict[str, str],
) -> list[str]:
    """Return every TC-02-009 problem in these workflow documents."""
    problems: list[str] = []
    parsed: dict[str, dict] = {}
    for name in sorted(workflows):
        text = workflows[name]
        try:
            doc = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            problems.append(f"{name} is not valid YAML: {exc}")
            continue
        if not isinstance(doc, dict):
            problems.append(f"{name} is not a workflow")
            continue
        parsed[name] = doc
        problems.extend(_upload_problems(name, doc))
        problems.extend(_echo_problems(name, doc))
        problems.extend(_pages_problems(name, doc))
    ci = parsed.get("ci.yml")
    if ci is None:
        problems.append("ci.yml is missing")
        return problems
    problems.extend(_job_evidence_problems(ci))
    problems.extend(_mask_problems(ci))
    problems.extend(_redaction_problems(ci, redactor_source))
    problems.extend(_trace_problems(configs))
    return problems


def _problems_for(workflows: dict[str, str] | None = None) -> list[str]:
    return evidence_problems(
        _load_workflows() if workflows is None else workflows,
        redactor_source=REDACTOR.read_text(encoding="utf-8"),
        configs=_load_configs(),
    )


def test_repository_workflows_meet_the_evidence_contract():
    problems = _problems_for()
    assert problems == []


def test_evidence_blocks_are_valid_bash():
    doc = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    for job_name in CI_JOBS:
        evidence = _evidence_runs(_jobs(doc)[job_name])
        assert evidence.strip(), job_name
        cleaned = re.sub(r"\$\{\{[^}]*\}\}", "sha", evidence)
        proc = subprocess.run(
            ["bash", "-n"],
            input=cleaned,
            text=True,
            capture_output=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr


def test_missing_sha_line_fails_the_checker():
    workflows = _load_workflows()
    workflows["ci.yml"] = workflows["ci.yml"].replace('echo "commit: ${{ github.sha }}"\n', "", 1)
    problems = _problems_for(workflows)
    assert any("build" in item and "commit SHA" in item for item in problems)


def test_missing_retention_fails_the_checker():
    workflows = _load_workflows()
    workflows["ci.yml"] = workflows["ci.yml"].replace("retention-days: 14\n", "", 1)
    problems = _problems_for(workflows)
    assert any("retention-days" in item for item in problems)


def test_unmasked_secret_echo_fails_the_checker():
    workflows = _load_workflows()
    old = 'echo "::add-mask::$PG_PASSWORD"\n'
    leaked = old + '          echo "leaked $PG_PASSWORD"\n'
    assert old in workflows["ci.yml"]
    workflows["ci.yml"] = workflows["ci.yml"].replace(old, leaked, 1)
    problems = _problems_for(workflows)
    assert any("echoes PG_PASSWORD" in item for item in problems)


def test_pages_deploy_without_conclusion_fails_the_checker():
    for document in (_UNGUARDED_PAGES, _SUCCESS_IF_PAGES):
        workflows = _load_workflows()
        workflows["pages.yml"] = document
        problems = _problems_for(workflows)
        assert any("without requiring a successful conclusion" in item for item in problems)


def test_pages_deploy_that_requires_success_is_accepted():
    workflows = _load_workflows()
    workflows["pages.yml"] = _GUARDED_PAGES
    problems = [item for item in _problems_for(workflows) if "Pages" in item]
    assert problems == []


def test_runbook_documents_retention_logs_and_pages():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "14" in text
    assert "retention" in text.lower()
    assert "log" in text.lower()
    assert "pages" in text.lower()
    assert "image: none" in text


def test_release_note_maps_the_criteria():
    text = NOTE.read_text(encoding="utf-8")
    for item in ("AC1", "AC2", "DoD1", "DoD2", "DoD3", "DoD4", "DoD5"):
        assert item in text


def test_this_module_does_not_skip():
    text = Path(__file__).read_text(encoding="utf-8")
    assert "pytest" + ".skip" not in text
    assert "pytest" + ".importorskip" not in text


def test_redactor_strips_report_text_and_trace_zip(tmp_path):
    # secret-inventory: synthetic
    connection = "postgresql://app:example@localhost:5432/db"
    report = tmp_path / "playwright-report"
    report.mkdir()
    (report / "index.html").write_text(
        "<p>synthetic page title</p>"
        f"<p>{connection}</p>"
        "<p>Authorization: Bearer example-value</p>"
        "<p>password=example</p>",
        encoding="utf-8",
    )
    results = tmp_path / "test-results" / "case"
    results.mkdir(parents=True)
    zip_path = results / "trace.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "0-trace.network",
            connection + "\nCookie: session=example\n",
        )
        archive.writestr("resources/page.png", b"\x89PNG\r\nnot-really")
    shot = results / "shot.png"
    shot.write_bytes(b"\x89PNG\r\nkeep")
    missing = tmp_path / "missing"
    command = [
        sys.executable,
        str(REDACTOR),
        str(report),
        str(tmp_path / "test-results"),
        str(missing),
    ]
    for _ in range(2):
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr
        assert "postgresql://app:example" not in proc.stdout
    html = (report / "index.html").read_text(encoding="utf-8")
    assert "synthetic page title" in html
    assert "example@localhost" not in html
    assert "Bearer example-value" not in html
    assert "password=example" not in html
    assert "redacted" in html
    with zipfile.ZipFile(zip_path) as archive:
        network = archive.read("0-trace.network").decode("utf-8")
        assert "example@localhost" not in network
        assert "session=example" not in network
        assert "redacted" in network
        assert archive.read("resources/page.png") == b"\x89PNG\r\nnot-really"
    assert shot.read_bytes() == b"\x89PNG\r\nkeep"


STAT_READER = ROOT / "scripts" / "ci" / "read-playwright-stat.mjs"


def _e2e_script() -> str:
    doc = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    job = _jobs(doc)["web-release-e2e"]
    return _step_run(job, "Run release Playwright specs")


def _assigned(script: str, name: str) -> str:
    match = re.search(rf'(?m)^[ \t]*{name}="([^"]*)"', script)
    assert match, name
    return match.group(1)


def test_rules_json_is_outside_playwright_output_dirs():
    script = _e2e_script()
    evidence_dir = _assigned(script, "evidence_dir")
    rules_json = _assigned(script, "rules_json").replace("${evidence_dir}", evidence_dir)
    release_json = _assigned(script, "release_json").replace("${evidence_dir}", evidence_dir)
    axe_log = _assigned(script, "axe_log").replace("${evidence_dir}", evidence_dir)
    assert "RUNNER_TEMP" in evidence_dir
    for path in (rules_json, release_json, axe_log):
        assert "test-results" not in path, path
        assert "playwright-report" not in path, path
    assert 'PLAYWRIGHT_JSON_OUTPUT_FILE="$rules_json"' in script
    assert 'PLAYWRIGHT_JSON_OUTPUT_FILE="$release_json"' in script
    assert '--report "$release_json"' in script
    assert 'load_counts "$rules_json" "$rules_status"' in script
    assert 'load_counts "$release_json" "$playwright_status"' in script
    for text in _load_configs().values():
        for output in re.findall(r"outputDir:\s*[`'\"]([^`'\"]+)", text):
            root_name = output.split("/", 1)[0]
            assert root_name not in rules_json
            assert root_name not in release_json
    reader_fail = script.index('if [[ "$evidence_reader_status" -ne 0 ]]')
    totals = script.index('echo "totals:')
    assert reader_fail < totals
    assert "rules evidence exit ${rules_status}" in script
    assert '"$rules_status" -ne 0' in script


def _read_stat(path: Path, field: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(STAT_READER), str(path), field],
        capture_output=True,
        text=True,
        check=False,
    )


def test_stat_reader_fails_when_the_report_is_missing(tmp_path):
    proc = _read_stat(tmp_path / "missing.json", "expected")
    assert proc.returncode != 0
    assert proc.stdout == ""


def test_stat_reader_fails_when_the_report_is_unreadable(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    proc = _read_stat(bad, "expected")
    assert proc.returncode != 0
    assert proc.stdout == ""


def test_stat_reader_prints_a_readable_count(tmp_path):
    report = tmp_path / "ok.json"
    report.write_text(
        '{"stats":{"expected":3,"unexpected":0,"flaky":0,"skipped":1}}',
        encoding="utf-8",
    )
    proc = _read_stat(report, "expected")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "3"
