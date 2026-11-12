"""Rules form, delivery log and permissions through a real browser and API.

Chromium talks to Next, Next proxies to a real API process, and that process
uses PostgreSQL. Both service processes are stopped and reaped between phases.
A new database session is not a process restart.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import bindparam, inspect, text

from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import NotificationLog, User, Workspace, WorkspaceMember
from tests.conftest import established_user

pytestmark = pytest.mark.integration

TABLE_KEYS = (
    ("notification_delivery_attempts", "id"),
    ("notification_log", "id"),
    ("notification_dedupe_claims", "dedupe_key"),
    ("notification_channel_preferences", "id"),
    ("notification_unsubscribes", "id"),
    ("notification_policies", "id"),
    ("in_app_notifications", "id"),
    ("audit_events", "id"),
    ("idempotency_keys", "id"),
    ("user_sessions", "id"),
    ("api_keys", "id"),
    ("custom_roles", "id"),
    ("tags", "id"),
    ("workspace_members", "id"),
    ("users", "id"),
    ("workspaces", "id"),
)


def snapshot():
    with SessionLocal() as db:
        return {
            name: {row[0] for row in db.execute(text(f"SELECT {key} FROM {name}"))}
            for name, key in TABLE_KEYS
            if inspect(db.connection()).has_table(name)
        }


def _rows(table, workspace_id):
    with SessionLocal() as db:
        return [
            dict(row)
            for row in db.execute(
                text(f"SELECT * FROM {table} WHERE workspace_id = :ws ORDER BY id"),
                {"ws": workspace_id},
            ).mappings()
        ]


def _policy_actions(workspace_id):
    with SessionLocal() as db:
        return (
            db.execute(
                text(
                    "SELECT action FROM audit_events "
                    "WHERE workspace_id = :ws AND action LIKE 'notification.policy%' "
                    "ORDER BY id"
                ),
                {"ws": workspace_id},
            )
            .scalars()
            .all()
        )


@pytest.fixture
def actors(_ensure_test_data):
    if not _ensure_test_data:
        pytest.fail("PostgreSQL is required for notification rules acceptance")
    before = snapshot()
    token = uuid.uuid4().hex
    data = {}
    try:
        with SessionLocal() as db:
            db.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('workspaces', 'id'), "
                    "(SELECT GREATEST(COALESCE(MAX(id), 1), 1) FROM workspaces))"
                )
            )
            ws = Workspace(name="Rules acceptance", slug=f"rules-{token}")
            db.add(ws)
            db.flush()
            data["ws"] = ws.id
            people = (
                ("admin", "Rules Admin", "admin", False),
                ("editor", "Rules Editor", "editor", False),
                ("paused", "Rules Paused", "editor", True),
            )
            for key, display_name, role, suspended in people:
                user = established_user(
                    email=f"rules-{key}-{token}@example.com",
                    display_name=display_name,
                    password_hash=hash_password("test-password"),
                )
                db.add(user)
                db.flush()
                db.add(
                    WorkspaceMember(
                        workspace_id=ws.id,
                        user_id=user.id,
                        role=role,
                        suspended=suspended,
                    )
                )
                data[key] = {"id": user.id, "email": user.email, "name": display_name}
            log_recipient = f"rules-log-{token}@example.com"
            log = NotificationLog(
                workspace_id=ws.id,
                event_type="member.joined",
                channel="email",
                recipient_email=log_recipient,
                subject="Member joined notice",
                status="failed",
                delivery_state="dead-lettered",
                delivered_to_provider=False,
                provider_mode="fixture",
                dedupe_key="ab" * 32,
                attempt_count=1,
                created_at=datetime(2026, 11, 11, 12, 0, 0),
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            data["log_id"] = log.id
            data["log_recipient"] = log_recipient
        yield data
    finally:
        current = snapshot()
        with SessionLocal() as db:
            for name, key in TABLE_KEYS:
                created = list(current.get(name, set()) - before.get(name, set()))
                if created:
                    stmt = text(f"DELETE FROM {name} WHERE {key} IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    )
                    db.execute(stmt, {"ids": created})
            db.commit()
        after = snapshot()
        assert after == before, {
            name: (len(before.get(name, set())), len(after.get(name, set())))
            for name, _ in TABLE_KEYS
        }


@contextmanager
def _rules_service(command, cwd, env, log_path):
    """Own and reap only this acceptance test's service process group."""
    with log_path.open("w") as log:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            yield process
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                pass
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=10)
            assert process.returncode is not None, "Acceptance service was not reaped"


def _wait_ready(process, url):
    deadline = time.monotonic() + 120
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            assert process.poll() is None, "Acceptance service exited before becoming ready"
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.2)
    pytest.fail("Acceptance service did not become ready within 120 seconds")


def _assert_persisted(actors, seeded_logs):
    policies = _rows("notification_policies", actors["ws"])
    logs = _rows("notification_log", actors["ws"])
    assert len(policies) == 1
    policy = policies[0]
    assert policy["workspace_id"] == actors["ws"]
    assert policy["event_type"] == "member.joined"
    assert policy["enabled"] is True
    assert policy["recipient_type"] == "user"
    assert policy["recipient_value"] == str(actors["editor"]["id"])
    assert logs == seeded_logs
    assert logs[0]["recipient_email"] == actors["log_recipient"]
    assert logs[0]["status"] == "failed"
    assert logs[0]["delivery_state"] == "dead-lettered"
    assert logs[0]["delivered_to_provider"] is False
    assert logs[0]["provider_mode"] == "fixture"
    assert _policy_actions(actors["ws"]) == [
        "notification.policy_created",
        "notification.policy_updated",
        "notification.policy_updated",
    ]
    return policies, logs


def test_rules_ui_api_and_database_agree_after_full_process_restart(actors, tmp_path):
    """Create, disable and re-enable a rule, then compare the UI with stored rows.

    The delivery log is checked before and after both processes restart. A
    non-admin sees none of the admin controls.
    """
    from tests import _safety

    api_root = Path(__file__).resolve().parents[2]
    web_root = api_root.parent / "web"
    node = shutil.which("node")
    next_cli = web_root / "node_modules/next/dist/bin/next"
    playwright_cli = web_root / "node_modules/@playwright/test/cli.js"
    assert node and next_cli.is_file() and playwright_cli.is_file(), "Web toolchain required"
    _safety.validate_test_database_url(os.environ["DATABASE_URL"])

    seeded_logs = _rows("notification_log", actors["ws"])
    assert len(seeded_logs) == 1
    assert _rows("notification_policies", actors["ws"]) == []
    fixture = {
        "adminEmail": actors["admin"]["email"],
        "editorEmail": actors["editor"]["email"],
        "password": "test-password",
        "memberUserId": actors["editor"]["id"],
        "memberName": actors["editor"]["name"],
        "adminName": actors["admin"]["name"],
        "suspendedName": actors["paused"]["name"],
        "logRecipient": actors["log_recipient"],
        "logId": actors["log_id"],
    }
    with socket.socket() as api_socket, socket.socket() as web_socket:
        api_socket.bind(("127.0.0.1", 0))
        web_socket.bind(("127.0.0.1", 0))
        api_port, web_port = api_socket.getsockname()[1], web_socket.getsockname()[1]
    api_url, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
    env = {
        **os.environ,
        "APP_ENV": "test",
        "TRUST_COPILOT_TESTING": "1",
        "TC_RULES_API_PORT": str(api_port),
        "TC_RULES_BASE_URL": web_url,
        "TC_RULES_FIXTURE": json.dumps(fixture),
        "API_UPSTREAM": api_url,
        "FRONTEND_URL": web_url,
        "APP_BASE_URL": web_url,
        "TRUSTED_ORIGINS": web_url,
        "S3_ACCESS_KEY": "",
        "S3_SECRET_KEY": "",
        # Stay inside the tree ESLint and Prettier already ignore. A separate
        # dist directory is linted by the later web quality checks, and Next
        # rewrites tsconfig.json to point at it.
        "NEXT_DIST_DIR": ".next",
        "NEXT_TELEMETRY_DISABLED": "1",
        "PLAYWRIGHT_HTML_OPEN": "never",
    }
    _safety.scrub_provider_env(env)
    assert env.get("SESSION_SECRET"), "A stable signing value is required across process restarts"
    bootstrap = (
        "import os; from tests import _safety; "
        "_safety.scrub_provider_env(); "
        "_safety.validate_test_database_url(os.environ['DATABASE_URL']); "
        "_safety.install_network_guard(); "
        "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', "
        "port=int(os.environ['TC_RULES_API_PORT']))"
    )
    output = web_root / "test-results/rules-restart"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("before.json", "after.json", "processes.json"):
        (output / name).unlink(missing_ok=True)
    checkpoints = []
    persisted = None
    for phase in ("before", "after"):
        phase_env = {
            **env,
            "TC_RULES_PHASE": phase,
            "PLAYWRIGHT_JSON_OUTPUT_FILE": str(output / f"{phase}.json"),
            "PLAYWRIGHT_HTML_OUTPUT_DIR": str(web_root / "playwright-report/rules-restart" / phase),
        }
        with (
            _rules_service(
                [sys.executable, "-c", bootstrap],
                api_root,
                phase_env,
                tmp_path / f"api-{phase}.log",
            ) as api,
            _rules_service(
                [node, str(next_cli), "dev", "--hostname", "127.0.0.1", "--port", str(web_port)],
                web_root,
                phase_env,
                tmp_path / f"web-{phase}.log",
            ) as web,
        ):
            _wait_ready(api, f"{api_url}/healthz")
            _wait_ready(web, f"{web_url}/login")
            browser_log = tmp_path / f"browser-{phase}.log"
            with _rules_service(
                [
                    node,
                    str(playwright_cli),
                    "test",
                    "--config=playwright.rules.config.ts",
                    "--grep",
                    f"{phase} restart:",
                ],
                cwd=web_root,
                env=phase_env,
                log_path=browser_log,
            ) as browser:
                browser.wait(timeout=240)
            assert browser.returncode == 0, browser_log.read_text()
            report = json.loads((output / f"{phase}.json").read_text())
            assert report["stats"]["expected"] == 1
            assert all(report["stats"][key] == 0 for key in ("unexpected", "skipped", "flaky"))
        checkpoints.append(
            {
                "phase": phase,
                "api_pid": api.pid,
                "web_pid": web.pid,
                "api_exit": api.returncode,
                "web_exit": web.returncode,
            }
        )
        (output / "processes.json").write_text(json.dumps(checkpoints, indent=2) + "\n")
        for port in (api_port, web_port):
            deadline = time.monotonic() + 10
            while True:
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", port)) != 0:
                        break
                assert time.monotonic() < deadline, "Old service still listening"
                time.sleep(0.1)
        policies, logs = _assert_persisted(actors, seeded_logs)
        if persisted is None:
            persisted = (policies, logs)
        else:
            assert (policies, logs) == persisted, "Restart changed the stored rule or delivery log"
    assert checkpoints[0]["api_pid"] != checkpoints[1]["api_pid"]
    assert checkpoints[0]["web_pid"] != checkpoints[1]["web_pid"]
    assert isinstance(actors["editor"]["id"], int)
    assert actors["editor"]["id"] != actors["admin"]["id"]
    # The stored recipient is the member user id, not a membership row id.
    with SessionLocal() as db:
        member = (
            db.query(WorkspaceMember)
            .filter_by(workspace_id=actors["ws"], user_id=actors["editor"]["id"])
            .one()
        )
        assert str(member.user_id) == persisted[0][0]["recipient_value"]
        if member.id != member.user_id:
            assert persisted[0][0]["recipient_value"] != str(member.id)
        user = db.get(User, actors["editor"]["id"])
        assert user is not None
        assert user.email == actors["editor"]["email"]
