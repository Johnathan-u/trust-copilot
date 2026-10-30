"""TC-04-006d: real browser/API/migrated-PostgreSQL expiry display acceptance."""

import json
import math
import os
import shutil
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.database import SessionLocal
from app.models import UserSession, Workspace
from tests import _safety
from tests.release.test_domain_in_app_notifications import _inbox_service, _inbox_wait_ready
from tests.release import test_logout_all_browser
from tests.release.test_logout_all_browser import (
    _BOOTSTRAP,
    _assert_credential_free_reports,
    _checkpoint,
    _closed,
    _snapshot,
)


logout_browser_rows = test_logout_all_browser.logout_browser_rows


@pytest.mark.integration
def test_session_expiry_real_browsers_and_unchanged_authority(logout_browser_rows, tmp_path):
    credentials, user_ids, workspace_ids = logout_browser_rows
    api_root = Path(__file__).resolve().parents[2]
    web_root = api_root.parent / "web"
    node = shutil.which("node")
    next_cli = web_root / "node_modules/next/dist/bin/next"
    playwright = web_root / "node_modules/@playwright/test/cli.js"
    assert node and next_cli.is_file() and playwright.is_file(), "Locked web toolchain required"
    _safety.validate_test_database_url(os.environ["DATABASE_URL"])
    output = web_root / "test-results/session-expiry"
    html_report = web_root / "playwright-report/session-expiry"
    for directory in (output, html_report):
        shutil.rmtree(directory, ignore_errors=True)
    output.mkdir(parents=True)
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    ready = tmp_path / "ready"
    network = output / "network.jsonl"
    assertions = []
    with socket.socket() as api_socket, socket.socket() as web_socket, socket.socket() as storage:
        for listener in (api_socket, web_socket, storage):
            listener.bind(("127.0.0.1", 0))
        api_port, web_port, storage_port = [
            listener.getsockname()[1] for listener in (api_socket, web_socket, storage)
        ]
        api_socket.close()
        web_socket.close()
        api_url, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
        env = {
            **os.environ,
            "APP_ENV": "test",
            "TRUST_COPILOT_TESTING": "1",
            "TC_ALLOW_PROVIDER_TESTS": "0",
            # Reuse the existing guarded subprocess, with this test's own ports/logs.
            "TC_LOGOUT_API_PORT": str(api_port),
            "TC_LOGOUT_STORAGE_PORT": str(storage_port),
            "TC_LOGOUT_READY_MARKER": str(ready),
            "TC_LOGOUT_STORAGE_LOG": str(network),
            "TC_SESSION_BASE_URL": web_url,
            "TC_SESSION_CHECKPOINT_DIR": str(checkpoints),
            "TC_SESSION_FIXTURE_FILE": str(credentials),
            "API_UPSTREAM": api_url,
            "FRONTEND_URL": web_url,
            "APP_BASE_URL": web_url,
            "TRUSTED_ORIGINS": web_url,
            "S3_ENDPOINT": f"http://127.0.0.1:{storage_port}",
            "S3_ACCESS_KEY": "test-key",
            "S3_SECRET_KEY": "test-secret",
            "S3_USE_SSL": "false",
            "S3_BUCKET_RAW": "test-session-expiry-raw",
            "S3_BUCKET_EXPORTS": "test-session-expiry-exports",
            "AWS_MAX_ATTEMPTS": "1",
            "AWS_RETRY_MODE": "standard",
            "NO_PROXY": "127.0.0.1,localhost",
            "NEXT_DIST_DIR": ".next",
            "NEXT_TELEMETRY_DISABLED": "1",
            "PLAYWRIGHT_JSON_OUTPUT_FILE": str(output / "report.json"),
            "PLAYWRIGHT_HTML_OUTPUT_DIR": str(html_report),
            "PLAYWRIGHT_HTML_OPEN": "never",
        }
        _safety.scrub_provider_env(env)
        assert env.get("SESSION_SECRET"), "Stable signing secret required across services"
        try:
            with (
                _inbox_service(
                    [sys.executable, "-c", _BOOTSTRAP], api_root, env, tmp_path / "api.log"
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
                    env,
                    tmp_path / "web.log",
                ) as web,
            ):
                _inbox_wait_ready(api, f"{api_url}/healthz")
                _inbox_wait_ready(web, f"{web_url}/login")
                ready.touch()
                with _inbox_service(
                    [node, str(playwright), "test", "--config=playwright.session-expiry.config.ts"],
                    web_root,
                    env,
                    tmp_path / "browser.log",
                ) as browser:
                    for index, width in enumerate((360, 1440)):
                        shorten = _checkpoint(checkpoints, "shorten", width, browser)
                        with SessionLocal() as db:
                            assert (
                                db.query(UserSession).filter_by(user_id=user_ids[index]).count()
                                == 1
                            )
                            db.get(Workspace, workspace_ids[index]).session_max_age_seconds = 120
                            db.commit()
                        before = _snapshot()
                        shorten.touch()
                        warning = _checkpoint(checkpoints, "warning", width, browser)
                        assert (
                            _snapshot() == before
                        ), "Expiry checks/retry changed persisted authority"
                        warning.touch()
                        phase = "expire" if index == 0 else "revoke"
                        finish = _checkpoint(checkpoints, phase, width, browser)
                        with SessionLocal() as db:
                            row = db.query(UserSession).filter_by(user_id=user_ids[index]).one()
                            if index == 0:
                                created = row.created_at.replace(tzinfo=timezone.utc)
                                elapsed = (datetime.now(timezone.utc) - created).total_seconds()
                                db.get(Workspace, workspace_ids[index]).session_max_age_seconds = (
                                    math.ceil(elapsed) + 5
                                )
                            else:
                                db.delete(row)
                            db.commit()
                        before = _snapshot()
                        finish.touch()
                        done = _checkpoint(checkpoints, "done", width, browser)
                        assert (
                            _snapshot() == before
                        ), "Deadline/revocation denial changed persisted rows"
                        assertions.append(
                            {
                                "remember": bool(index),
                                "real_cookie_and_current_policy": True,
                                "no_renewal_or_auth_mutation": True,
                                "all_rows_unchanged_after_reads": True,
                                "server_denial_redirect": True,
                            }
                        )
                        (output / "assertions.json").write_text(
                            json.dumps(assertions, indent=2) + "\n"
                        )
                        done.touch()
                    browser.wait(timeout=30)
        finally:
            try:
                _closed((api_port, web_port))
            finally:
                password = json.loads(credentials.read_text())["password"]
                _assert_credential_free_reports((output, html_report), password)
        attempts = (
            [json.loads(line) for line in network.read_text().splitlines()]
            if network.exists()
            else []
        )
        (output / "processes.json").write_text(
            json.dumps(
                {
                    "api_exit": api.returncode,
                    "web_exit": web.returncode,
                    "browser_exit": browser.returncode,
                    "attempts": attempts,
                },
                indent=2,
            )
            + "\n"
        )
        assert all(item == {"phase": "startup", "kind": "storage"} for item in attempts)
        assert browser.returncode == 0, "Real browser acceptance failed; inspect its report"
        report = json.loads((output / "report.json").read_text())
        assert report["stats"]["expected"] == 2
        assert all(report["stats"][key] == 0 for key in ("unexpected", "skipped", "flaky"))
        expected_axe = [("warning", width) for width in (360, 768, 1440)] + [("unavailable", 1440)]
        assert len(list(output.glob("axe-*.json"))) == len(expected_axe)
        for state, width in expected_axe:
            axe = json.loads((output / f"axe-{state}-{width}.json").read_text())
            assert axe["width"] == width and axe["state"] == state
            assert type(axe["violationCount"]) is int
            assert axe["violationCount"] == len(axe["violations"]) == 0
            assert (output / f"{state}-{width}.png").stat().st_size > 0
