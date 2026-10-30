"""One-use deterministic transport for an already reviewed tracker snapshot."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BASE = "d64e3803df975d25622cf28a2556178828db3c60"
TREE = "17cb200a6c385b6cedc3c9a073284c208c39d097"
LEASE = "codex-1d3d4d8034b5-2026-10-30T21:01:27.554Z"
STATE_SHA256 = "17e0b4497172965b2b4925d6a02bd84c25a6e94fb167c591af77ca1f8e34fd95"
DATA_SHA256 = "7861d5b9b4ab17ef46f120794a8002a5cf9f44242650a4d3cbac49061dc1c48a"
PATCH = Path("docs/planning/autonomy-materialization.patch.json")
HELPERS = [
    str(PATCH),
    "scripts/materialize_backlog_batch.py",
    ".github/workflows/materialize-backlog-batch.yml",
]


def git(*args, env=None):
    return subprocess.check_output(["git", *args], text=True, env=env).strip()


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def check_lease(path):
    state = json.loads(Path(path).read_text())
    require(state["lease_owner"] == LEASE, "coordinator lease changed")
    expiry = datetime.fromisoformat(state["lease_expires_at"].replace("Z", "+00:00"))
    require(expiry > datetime.now(timezone.utc), "coordinator lease expired")


def prepare():
    require(
        set(git("diff", "--name-only", f"{BASE}...HEAD").splitlines()) == set(HELPERS),
        "unexpected materialization source changes",
    )
    require(not git("status", "--porcelain"), "worktree is not clean")
    require(
        hashlib.sha256(PATCH.read_bytes()).hexdigest()
        == "1100db566f0baf46d1a8c812029c02ef50e6b72ea065ca8d953d4e8475821b29",
        "reviewed patch hash differs",
    )
    state = json.loads(Path("docs/planning/backlog-state.json").read_text())
    require(state["revision"] == 5, "expected ledger revision 5")
    reason = (
        "Reconcile nine reviewed authorization PRs and assign three bounded "
        "implementation children under renewed autonomous authority"
    )
    subprocess.run(
        [
            sys.executable,
            "scripts/backlog_tracker.py",
            "update",
            "--expected-revision",
            "5",
            "--actor",
            "codex-pm",
            "--reason",
            reason,
            "--patch",
            str(PATCH),
        ],
        check=True,
    )
    for command in ("build", "check"):
        subprocess.run([sys.executable, "scripts/backlog_tracker.py", command], check=True)
    expected = {
        "docs/planning/backlog-state.json": STATE_SHA256,
        "docs/tracker/data.js": DATA_SHA256,
    }
    for path, digest in expected.items():
        require(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path)
    subprocess.run(["git", "add", "--", *expected], check=True)
    require(
        set(git("diff", "--cached", "--name-only").splitlines()) == set(expected),
        "only generated state/data may be staged for the token-authenticated push",
    )
    # GITHUB_TOKEN never edits workflow paths. Prove the eventual connector cleanup
    # tree through an isolated index, while retaining helpers in the actual index.
    with tempfile.TemporaryDirectory(prefix="tc-reviewed-tree-") as directory:
        index = Path(directory) / "index"
        index.write_bytes(Path(git("rev-parse", "--git-path", "index")).read_bytes())
        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        subprocess.run(
            ["git", "update-index", "--force-remove", "--", *HELPERS], check=True, env=env
        )
        require(
            git("write-tree", env=env) == TREE,
            "connector cleanup tree differs from independent review",
        )
    print(f"Verified eventual cleanup tree {TREE}; helpers remain for connector cleanup.")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "check-lease":
        check_lease(sys.argv[2])
    elif len(sys.argv) == 2 and sys.argv[1] == "prepare":
        prepare()
    else:
        raise SystemExit("use check-lease PATH or prepare")
