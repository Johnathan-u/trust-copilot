"""Run one isolated in-memory guard-removal control; tracked code is never edited."""

import ast
import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps/api"
sys.path.insert(0, str(API))
import pytest  # noqa: E402
import tests.conftest  # noqa: E402,F401 -- install existing scrubbed environment/network guard
from app import worker  # noqa: E402

mode = sys.argv[1]
path = API / "app/worker.py"
before = hashlib.sha256(path.read_bytes()).hexdigest()
source = inspect.getsource(worker.run_export)
controls = {
    "job_payload": (
        "if ws_id != job.workspace_id or ws_id != current_workspace:",
        "if False:",
        "sqlite and new-export and foreign_payload_and_parent",
    ),
    "current_job": (
        "if ws_id != job.workspace_id or ws_id != current_workspace:",
        "if ws_id != job.workspace_id:",
        "sqlite and new-export and job_moved_stale_identity",
    ),
    "active_parent": (
        "            Questionnaire.deleted_at.is_(None),\n",
        "",
        "sqlite and new-export and parent_archived and not stale_identity",
    ),
    "exact_replay": (
        "if existing_rec.workspace_id != ws_id or existing_rec.questionnaire_id != qnr_id:",
        "if existing_rec.workspace_id != ws_id:",
        "sqlite and different_own_questionnaire",
    ),
    "current_replay": (
        ".filter(ExportRecord.job_id == job.id)\n        .populate_existing()",
        ".filter(ExportRecord.job_id == job.id)",
        "sqlite and moved_parent_stale_identity",
    ),
    "reference_types": (
        "if any(type(value) is not int or not 0 < value <= 2147483647 "
        "for value in (qnr_id, ws_id)):",
        "if False:",
        "sqlite and True-workspace_id",
    ),
    "current_file": (
        "        .populate_existing()\n        .first()",
        "        .first()",
        "sqlite and new-export and parent_without_file_stale_identity",
    ),
}
if mode == "baseline_added_cases":
    original = subprocess.check_output(
        ["git", "show", "dea5f5afe87dfa73a0321a0f0311847ed233432f:apps/api/app/worker.py"],
        cwd=ROOT,
        text=True,
    )
    node = next(
        node
        for node in ast.parse(original).body
        if isinstance(node, ast.FunctionDef) and node.name == "run_export"
    )
    replacement = ast.get_source_segment(original, node)
    selection = "sqlite and (job_deleted or parent_without_file_stale_identity)"
else:
    old, new, selection = controls[mode]
    assert old in source, mode
    replacement = source.replace(old, new, 1)
namespace = dict(worker.__dict__)
exec(compile(replacement, f"<negative-control:{mode}>", "exec"), namespace)
worker.run_export = namespace["run_export"]
print(json.dumps({"control": mode, "source_sha256": before, "selection": selection}), flush=True)
code = pytest.main(
    [
        str(API / "tests/release/test_authorization_export_worker.py"),
        "-k",
        selection,
        "-q",
        "--tb=short",
    ]
)
assert code == 1, f"Expected assertion failure, got {code}"
assert hashlib.sha256(path.read_bytes()).hexdigest() == before
print(
    json.dumps({"control": mode, "expected_test_exit": int(code), "source_unchanged": True}),
    flush=True,
)
