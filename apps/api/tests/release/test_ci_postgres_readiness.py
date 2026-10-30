"""Execute the actual CI startup shell against a deterministic entrypoint lifecycle.

No Docker or PostgreSQL is started here. The socket-only initialization server,
its shutdown, and the final TCP server are explicit simulated process states.
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[4]

# One executable fixture handles only the external commands used by the real step.
# It records readiness transport/results, never container password arguments.
_FAKE_COMMAND = r"""
import json, os, sys
from pathlib import Path
command = Path(sys.argv[0]).name
args = sys.argv[1:]
state_file = Path(os.environ['TC_READINESS_STATE'])
state = json.loads(state_file.read_text())
status = 0
if command == 'openssl':
    assert args == ['rand', '-hex', '24']
    print(os.environ['TC_SYNTHETIC_RANDOM'])
elif command == 'sleep':
    assert args == ['1']
    state['sleeps'] += 1
elif command == 'docker' and args[0] == 'run':
    assert args[1:4] == ['-d', '--name', 'tc-ci-pg']
    state['image'] = args[-1]
    state['bind'] = args[args.index('-p') + 1]
    print('synthetic-container')
elif command == 'docker' and args[:3] == ['exec', 'tc-ci-pg', 'pg_isready']:
    options = args[3:]
    transport = 'socket'
    if '-h' in options:
        index = options.index('-h')
        assert options[index + 1] == '127.0.0.1'
        options = options[:index] + options[index + 2:]
        transport = 'tcp'
    assert options == ['-U', 'tc_ci', '-d', 'tc_ci_42_1_test']
    count = len(state['probes']) + 1
    scenario = os.environ['TC_READINESS_SCENARIO']
    if scenario == 'bootstrap':
        # Official entrypoint: initialize, socket-only temp server, fast stop,
        # then the final postgres process begins listening on TCP.
        phase = ['initializing', 'socket-bootstrap', 'shutdown', 'final-server'][min(count, 4) - 1]
        status = 0 if phase == 'final-server' or (phase == 'socket-bootstrap' and transport == 'socket') else (1 if phase == 'shutdown' else 2)
    elif scenario == 'never':
        phase, status = 'unavailable', 2
    elif scenario == 'final-failure':
        phase, status = ('ready', 0) if count == 1 else ('rejecting', 1)
    else:
        assert scenario == 'ready'
        phase, status = 'ready', 0
    state['probes'].append({'transport': transport, 'phase': phase, 'status': status})
else:
    raise AssertionError('Unexpected command in startup step')
state_file.write_text(json.dumps(state))
sys.exit(status)
"""


@pytest.mark.parametrize(
    "scenario,expected_exit,probes,sleeps",
    [("bootstrap", 0, 5, 3), ("ready", 0, 2, 0), ("never", 2, 61, 60), ("final-failure", 1, 2, 0)],
)
def test_readiness_waits_for_final_tcp_server_and_keeps_failure_bound(
    tmp_path, scenario, expected_exit, probes, sleeps
):
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    step = next(
        entry
        for entry in workflow["jobs"]["build"]["steps"]
        if entry.get("name") == "Start isolated Postgres (pgvector) for this run"
    )
    script = (
        step["run"].replace("${{ github.run_id }}", "42").replace("${{ github.run_attempt }}", "1")
    )
    assert "${{" not in script
    commands = tmp_path / "bin"
    commands.mkdir()
    for name in ("docker", "openssl", "sleep"):
        command = commands / name
        command.write_text(f"#!{sys.executable}\n" + _FAKE_COMMAND)
        command.chmod(0o700)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"probes": [], "sleeps": 0}))
    exports = tmp_path / "github-env"
    exports.touch()
    bash = shutil.which("bash")
    assert bash
    result = subprocess.run(
        [bash, "-e", "-c", script],
        env={
            **os.environ,
            **step["env"],
            "PATH": str(commands) + os.pathsep + os.environ["PATH"],
            "GITHUB_ENV": str(exports),
            "TC_READINESS_STATE": str(state_file),
            "TC_READINESS_SCENARIO": scenario,
            "TC_SYNTHETIC_RANDOM": secrets.token_hex(24),
        },
        capture_output=True,
        text=True,
        timeout=15,
    )
    state = json.loads(state_file.read_text())
    exit_status = result.returncode
    assert exit_status == expected_exit
    assert len(state["probes"]) == probes
    assert state["sleeps"] == sleeps
    assert all(probe["transport"] == "tcp" for probe in state["probes"])
    assert state["image"] == step["env"]["PG_IMAGE"]
    assert "@sha256:" in state["image"]
    assert state["bind"] == "127.0.0.1:5432:5432"
    if expected_exit == 0:
        lines = exports.read_text().splitlines()
        assert len(lines) == 2
        values = dict(line.split("=", 1) for line in lines)
        assert values["DATABASE_URL"] == values["TC_TEST_DATABASE_URL"]
        assert values["DATABASE_URL"].endswith("@127.0.0.1:5432/tc_ci_42_1_test")
        assert state["probes"][-1]["status"] == 0
    else:
        assert exports.read_text() == "", "An unready database must not be published to later steps"
