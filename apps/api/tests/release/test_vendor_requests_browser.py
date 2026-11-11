"""Real browser, API, and PostgreSQL agreement for outbound vendor requests.

Chromium talks to Next, which proxies to a real API process and PostgreSQL.
No page route stands in for the API. Both processes are reaped between phases.
"""

import hashlib
import json
import os
import secrets
import shutil
import socket
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import bindparam, inspect, text

from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import User, VendorRequest, Workspace, WorkspaceMember
from app.models.tag import Tag
from app.services import vendor_request_service as service
from app.services.tag_service import SYSTEM_TAGS
from tests import _safety
from tests.release.test_domain_in_app_notifications import _inbox_service, _inbox_wait_ready

pytestmark = pytest.mark.integration

FINAL_RESPONSE = "Synthetic final vendor response"
SNAPSHOT_TABLES = (
    "vendor_requests",
    "audit_events",
    "idempotency_keys",
    "user_sessions",
    "workspace_members",
    "users",
    "workspaces",
    "tags",
)


def _snapshots():
    with SessionLocal() as db:
        tables = set(inspect(db.connection()).get_table_names())
        return {
            name: hashlib.sha256(
                "\n".join(
                    db.execute(text(f"SELECT row_to_json(t)::text FROM {name} t ORDER BY 1"))
                    .scalars()
                    .all()
                ).encode()
            ).hexdigest()
            for name in SNAPSHOT_TABLES
            if name in tables
        }


def _in_ids(db, sql, ids):
    if ids:
        return db.execute(text(sql).bindparams(bindparam("ids", expanding=True)), {"ids": ids})
    return None


def _vendor_rows(workspace_id):
    with SessionLocal() as db:
        return [
            dict(row)
            for row in db.execute(
                text("SELECT * FROM vendor_requests WHERE workspace_id = :ws ORDER BY id"),
                {"ws": workspace_id},
            ).mappings()
        ]


def _closed(ports):
    for port in ports:
        deadline = time.monotonic() + 10
        while True:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) != 0:
                    break
            assert time.monotonic() < deadline, "An owned service still listens after cleanup"
            time.sleep(0.1)


@pytest.fixture
def vendor_browser_rows(_ensure_test_data):
    assert _ensure_test_data, "PostgreSQL is required for vendor-request browser acceptance"
    baseline = _snapshots()
    token = secrets.token_hex(8)
    password = secrets.token_urlsafe(18)
    ws_ids, user_ids, tag_ids = [], [], []
    data = {
        "password": password,
        "sendEmail": f"created-{token}@example.com",
        "resendEmail": f"resend-{token}@example.com",
        "completeEmail": f"complete-{token}@example.com",
        "finalResponse": FINAL_RESPONSE,
    }
    try:
        with SessionLocal() as db:
            for entry in SYSTEM_TAGS:
                if (
                    db.query(Tag)
                    .filter_by(workspace_id=None, category=entry["category"], key=entry["key"])
                    .first()
                    is None
                ):
                    tag = Tag(workspace_id=None, is_system=True, **entry)
                    db.add(tag)
                    db.flush()
                    tag_ids.append(tag.id)
            while True:
                wid = 100000 + secrets.randbelow(1000000000)
                if db.get(Workspace, wid) is None:
                    break
            ws_ids.append(wid)
            db.add(Workspace(id=wid, name="Vendor browser", slug=f"vendor-ui-{token}"))
            db.flush()
            user = User(
                email=f"vendor-browser-{token}@test.local",
                display_name="Synthetic admin",
                password_hash=hash_password(password),
                email_verified=True,
            )
            db.add(user)
            db.flush()
            user_ids.append(user.id)
            db.add(
                WorkspaceMember(workspace_id=wid, user_id=user.id, role="admin", suspended=False)
            )
            seeded = VendorRequest(
                workspace_id=wid,
                vendor_email=data["resendEmail"],
                message="Seeded prior acceptance.",
                status="pending",
                delivery_status="accepted",
                link_token=None,
                link_token_hash=service.digest(secrets.token_urlsafe(32)),
                expires_at=service.now() + timedelta(days=7),
                last_delivery_at=service.now(),
                last_delivery_error=None,
            )
            db.add(seeded)
            db.flush()
            data.update(
                email=user.email,
                workspaceId=wid,
                resendId=seeded.id,
                resendHash=seeded.link_token_hash,
            )
            db.commit()
        yield data
    finally:
        with SessionLocal() as db:
            _in_ids(db, "DELETE FROM vendor_requests WHERE workspace_id IN :ids", ws_ids)
            _in_ids(db, "DELETE FROM audit_events WHERE workspace_id IN :ids", ws_ids)
            _in_ids(db, "DELETE FROM audit_events WHERE user_id IN :ids", user_ids)
            for wid in ws_ids:
                db.execute(
                    text("DELETE FROM idempotency_keys WHERE idempotency_key LIKE :prefix"),
                    {"prefix": f"ws:{wid}:vendor-%"},
                )
            _in_ids(db, "DELETE FROM user_sessions WHERE user_id IN :ids", user_ids)
            _in_ids(db, "DELETE FROM workspace_members WHERE workspace_id IN :ids", ws_ids)
            _in_ids(db, "DELETE FROM users WHERE id IN :ids", user_ids)
            _in_ids(db, "DELETE FROM workspaces WHERE id IN :ids", ws_ids)
            _in_ids(db, "DELETE FROM tags WHERE id IN :ids", tag_ids)
            db.commit()
        assert (
            _snapshots() == baseline
        ), "Owned cleanup did not restore complete baseline table hashes"


def _expect_saved(rows, data):
    by_email = {row["vendor_email"]: row for row in rows}
    assert set(by_email) == {data["sendEmail"], data["resendEmail"], data["completeEmail"]}
    sent = by_email[data["sendEmail"]]
    assert sent["delivery_status"] == "unavailable"
    assert sent["last_delivery_error"] == "provider_unavailable"
    assert sent["revoked_at"] is not None
    assert sent["submitted_at"] is None
    assert sent["response_payload"] is None
    assert sent["link_token"] is None
    resent = by_email[data["resendEmail"]]
    assert resent["id"] == data["resendId"]
    assert resent["delivery_status"] == "unavailable"
    assert resent["last_delivery_error"] == "provider_unavailable"
    assert resent["link_token_hash"] == data["resendHash"]
    assert resent["revoked_at"] is None
    assert resent["submitted_at"] is None
    completed = by_email[data["completeEmail"]]
    assert completed["status"] == "completed"
    assert completed["submitted_at"] is not None
    assert completed["delivery_status"] == "not_sent"
    assert completed["revoked_at"] is None
    assert completed["response_payload"] == data["finalResponse"]
    assert completed["response_digest"] == service.digest(data["finalResponse"])
    assert completed["link_token"] is None and completed["link_token_hash"]
    assert sum(row["submitted_at"] is not None for row in rows) == 1


def test_vendor_request_ui_api_and_database_agree_after_full_process_restart(
    vendor_browser_rows, tmp_path
):
    """Create, console-send, revoke, and resend, then restart both processes.

    Completed is absent until the public page posts /api/vendor-response/submit.
    """
    data = vendor_browser_rows
    api_root = Path(__file__).resolve().parents[2]
    web_root = api_root.parent / "web"
    node = shutil.which("node")
    next_cli = web_root / "node_modules/next/dist/bin/next"
    playwright = web_root / "node_modules/@playwright/test/cli.js"
    assert node and next_cli.is_file() and playwright.is_file(), "Locked web toolchain is required"
    _safety.validate_test_database_url(os.environ["DATABASE_URL"])
    output = web_root / "test-results/vendor-requests-restart"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("before.json", "after.json", "processes.json", "assertions.json"):
        (output / name).unlink(missing_ok=True)
    fixture = {key: value for key, value in data.items() if key != "resendHash"}
    checkpoints = []
    saved = None
    with socket.socket() as api_socket, socket.socket() as web_socket:
        api_socket.bind(("127.0.0.1", 0))
        web_socket.bind(("127.0.0.1", 0))
        api_port, web_port = api_socket.getsockname()[1], web_socket.getsockname()[1]
    api_url, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
    env = {
        **os.environ,
        "APP_ENV": "test",
        "TRUST_COPILOT_TESTING": "1",
        "TC_ALLOW_PROVIDER_TESTS": "0",
        "TC_VENDOR_API_PORT": str(api_port),
        "TC_VENDOR_BASE_URL": web_url,
        "TC_VENDOR_FIXTURE": json.dumps(fixture),
        "API_UPSTREAM": api_url,
        "FRONTEND_URL": web_url,
        "APP_BASE_URL": web_url,
        "TRUSTED_ORIGINS": web_url,
        "S3_ACCESS_KEY": "",
        "S3_SECRET_KEY": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "NEXT_DIST_DIR": ".next",
        "NEXT_TELEMETRY_DISABLED": "1",
        "PLAYWRIGHT_HTML_OPEN": "never",
    }
    _safety.scrub_provider_env(env)
    assert env.get("SESSION_SECRET"), "A stable signing secret is required across process restarts"
    assert "SMTP_HOST" not in env
    bootstrap = (
        "import os; from tests import _safety; "
        "_safety.scrub_provider_env(); "
        "_safety.validate_test_database_url(os.environ['DATABASE_URL']); "
        "_safety.install_network_guard(); "
        "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', "
        "port=int(os.environ['TC_VENDOR_API_PORT']))"
    )
    for phase in ("before", "after"):
        phase_env = {
            **env,
            "TC_VENDOR_PHASE": phase,
            "PLAYWRIGHT_JSON_OUTPUT_FILE": str(output / f"{phase}.json"),
            "PLAYWRIGHT_HTML_OUTPUT_DIR": str(
                web_root / "playwright-report/vendor-requests-restart" / phase
            ),
        }
        with (
            _inbox_service(
                [sys.executable, "-c", bootstrap],
                api_root,
                phase_env,
                tmp_path / f"api-{phase}.log",
            ) as api,
            _inbox_service(
                [
                    node,
                    str(next_cli),
                    "dev",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(web_port),
                ],
                web_root,
                phase_env,
                tmp_path / f"web-{phase}.log",
            ) as web,
        ):
            _inbox_wait_ready(api, f"{api_url}/healthz")
            _inbox_wait_ready(web, f"{web_url}/login")
            browser_log = tmp_path / f"browser-{phase}.log"
            with _inbox_service(
                [
                    node,
                    str(playwright),
                    "test",
                    "--config=playwright.vendor-requests.config.ts",
                    "--grep",
                    f"{phase} restart:",
                ],
                web_root,
                phase_env,
                browser_log,
            ) as browser:
                browser.wait(timeout=300)
        _closed((api_port, web_port))
        checkpoints.append(
            {
                "phase": phase,
                "api_pid": api.pid,
                "web_pid": web.pid,
                "api_exit": api.returncode,
                "web_exit": web.returncode,
                "browser_exit": browser.returncode,
            }
        )
        (output / "processes.json").write_text(json.dumps(checkpoints, indent=2) + "\n")
        assert browser.returncode == 0, f"Real browser phase failed; inspect {browser_log.name}"
        report = json.loads((output / f"{phase}.json").read_text())
        assert report["stats"]["expected"] == 1
        assert all(report["stats"][key] == 0 for key in ("unexpected", "skipped", "flaky"))
        rows = _vendor_rows(data["workspaceId"])
        _expect_saved(rows, data)
        if saved is None:
            saved = rows
        else:
            assert rows == saved, "Restart changed the saved vendor_requests rows"
    assert checkpoints[0]["api_pid"] != checkpoints[1]["api_pid"]
    assert checkpoints[0]["web_pid"] != checkpoints[1]["web_pid"]
    (output / "assertions.json").write_text(
        json.dumps(
            {
                "restart_persisted": True,
                "console_send_unavailable": True,
                "console_resend_unavailable": True,
                "revoked_without_completion": True,
                "completed_only_with_submission": True,
                "rows_unchanged_across_restart": True,
            },
            indent=2,
        )
        + "\n"
    )
