"""TC-15-017a: real questionnaire acknowledgements through browser/API/migrated PostgreSQL."""

import hashlib
import json
import os
import secrets
import shutil
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import bindparam, text

from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import User, Workspace, WorkspaceMember
from app.models.questionnaire import Questionnaire
from app.models.tag import Tag
from app.services.tag_service import SYSTEM_TAGS
from tests import _safety
from tests.release.test_domain_in_app_notifications import _inbox_service, _inbox_wait_ready
from tests.release.test_logout_all_browser import _assert_credential_free_reports, _closed

TABLES = (
    "questionnaires",
    "audit_events",
    "user_sessions",
    "workspace_members",
    "users",
    "workspaces",
    "tags",
)
WIDTHS = (360, 768, 1440)


def _rows(table):
    assert table in TABLES
    with SessionLocal() as db:
        return list(db.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings())


def _digest(rows):
    return hashlib.sha256(
        json.dumps([dict(row) for row in rows], default=str, sort_keys=True).encode()
    ).hexdigest()


def _snapshot():
    return {table: _digest(_rows(table)) for table in TABLES}


def _delete(db, table, column, ids):
    assert table in TABLES
    if ids:
        db.execute(
            text(f"DELETE FROM {table} WHERE {column} IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        )


@pytest.fixture
def questionnaire_ack_rows(_ensure_test_data, tmp_path):
    assert _ensure_test_data, "Migrated PostgreSQL is required for questionnaire browser acceptance"
    baseline = _snapshot()
    token = secrets.token_hex(8)
    user_ids, workspace_ids, tag_ids, qnr_ids = [], [], [], []
    data = {"password": secrets.token_urlsafe(24), "questionnaires": {}}
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
            for name in ("own", "foreign"):
                while True:
                    wid = 100000 + secrets.randbelow(1000000000)
                    if wid not in workspace_ids and db.get(Workspace, wid) is None:
                        break
                workspace_ids.append(wid)
                db.add(
                    Workspace(
                        id=wid, name=f"Acknowledgement {name}", slug=f"qnr-ack-{name}-{token}"
                    )
                )
                user = User(
                    email=f"qnr-ack-{name}-{token}@test.local",
                    display_name=f"Synthetic {name}",
                    password_hash=hash_password(data["password"]),
                    email_verified=True,
                )
                db.add(user)
                db.flush()
                user_ids.append(user.id)
                db.add(
                    WorkspaceMember(
                        user_id=user.id, workspace_id=wid, role="editor", suspended=False
                    )
                )
                data[name] = user.email
                for width in WIDTHS if name == "own" else (0,):
                    qnr = Questionnaire(
                        workspace_id=wid,
                        filename=f"Acknowledgement-{width}.xlsx",
                        display_id=f"QNR-ACK-{width}",
                        status="parsed",
                        frameworks_json='["SOC 2"]',
                        subject_areas_json='["Other"]',
                        deleted_at=datetime.now(timezone.utc),
                        deleted_by=user.id,
                    )
                    db.add(qnr)
                    db.flush()
                    qnr_ids.append(qnr.id)
                    if name == "own":
                        data["questionnaires"][str(width)] = {
                            "id": qnr.id,
                            "display_id": qnr.display_id,
                            "filename": qnr.filename,
                        }
            db.commit()
        credentials = tmp_path / "credentials.json"
        credentials.write_text(json.dumps(data))
        credentials.chmod(0o600)
        yield credentials, user_ids, workspace_ids
    finally:
        with SessionLocal() as db:
            _delete(db, "questionnaires", "id", qnr_ids)
            _delete(db, "audit_events", "user_id", user_ids)
            _delete(db, "audit_events", "workspace_id", workspace_ids)
            _delete(db, "user_sessions", "user_id", user_ids)
            _delete(db, "workspace_members", "workspace_id", workspace_ids)
            _delete(db, "users", "id", user_ids)
            _delete(db, "workspaces", "id", workspace_ids)
            _delete(db, "tags", "id", tag_ids)
            db.commit()
        assert _snapshot() == baseline, "Exact-owned cleanup did not restore complete baseline rows"


# Existing guarded API bootstrap pattern: no route, auth, storage, or DB substitutes.
_BOOTSTRAP = """
import errno, json, os, socket
from pathlib import Path
from tests import _safety
_safety.scrub_provider_env()
_safety.validate_test_database_url(os.environ['DATABASE_URL'])
_safety.validate_test_s3_endpoint(os.environ['S3_ENDPOINT'])
_safety.install_network_guard()
port = int(os.environ['TC_QNR_ACK_STORAGE_PORT'])
marker = Path(os.environ['TC_QNR_ACK_READY_MARKER'])
log = Path(os.environ['TC_QNR_ACK_STORAGE_LOG'])
connect, connect_ex, getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

def record_attempt(kind):
    with log.open('a') as stream:
        stream.write(json.dumps({'phase': 'requests' if marker.exists() else 'startup', 'kind': kind}) + '\\n')

def record(sock, address):
    if isinstance(address, tuple) and address[:2] == ('127.0.0.1', port):
        record_attempt('storage')
        return True
    return False

def guarded_connect(sock, address):
    if record(sock, address):
        raise ConnectionRefusedError(errno.ECONNREFUSED, 'Synthetic storage is unavailable')
    try:
        return connect(sock, address)
    except _safety.NetworkAccessBlocked:
        record_attempt('outbound')
        raise

def guarded_connect_ex(sock, address):
    if record(sock, address):
        return errno.ECONNREFUSED
    try:
        return connect_ex(sock, address)
    except _safety.NetworkAccessBlocked:
        record_attempt('outbound')
        raise

def guarded_getaddrinfo(*args, **kwargs):
    try:
        return getaddrinfo(*args, **kwargs)
    except _safety.NetworkAccessBlocked:
        record_attempt('outbound')
        raise

socket.socket.connect, socket.socket.connect_ex = guarded_connect, guarded_connect_ex
socket.getaddrinfo = guarded_getaddrinfo
import uvicorn
uvicorn.run('app.main:app', host='127.0.0.1', port=int(os.environ['TC_QNR_ACK_API_PORT']))
"""


def _checkpoint(directory, phase, width, browser):
    marker = directory / f"{phase}-{width}"
    deadline = time.monotonic() + 180
    while not marker.with_suffix(".json").is_file():
        assert browser.poll() is None, "Browser failed before DB checkpoint; inspect its report"
        assert time.monotonic() < deadline, "Browser did not reach DB checkpoint"
        time.sleep(0.1)
    assert json.loads(marker.with_suffix(".json").read_text()) == {"phase": phase, "width": width}
    return marker.with_suffix(".ack")


def _role(user_id, workspace_id, role):
    with SessionLocal() as db:
        member = (
            db.query(WorkspaceMember).filter_by(user_id=user_id, workspace_id=workspace_id).one()
        )
        member.role = role
        db.commit()


@pytest.mark.integration
def test_questionnaire_ack_real_browser_and_database(questionnaire_ack_rows, tmp_path):
    credentials, user_ids, workspace_ids = questionnaire_ack_rows
    data = json.loads(credentials.read_text())
    api_root = Path(__file__).resolve().parents[2]
    web_root = api_root.parent / "web"
    node = shutil.which("node")
    next_cli = web_root / "node_modules/next/dist/bin/next"
    playwright = web_root / "node_modules/@playwright/test/cli.js"
    assert node and next_cli.is_file() and playwright.is_file(), "Locked web toolchain is required"
    _safety.validate_test_database_url(os.environ["DATABASE_URL"])
    output = web_root / "test-results/questionnaire-ack"
    html_report = web_root / "playwright-report/questionnaire-ack"
    for directory in (output, html_report):
        shutil.rmtree(directory, ignore_errors=True)
    output.mkdir(parents=True)
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    ready, network = tmp_path / "ready", output / "network.jsonl"
    assertions = []
    with socket.socket() as api_socket, socket.socket() as web_socket, socket.socket() as storage:
        for listener in (api_socket, web_socket, storage):
            listener.bind(("127.0.0.1", 0))
        api_port, web_port, storage_port = [
            s.getsockname()[1] for s in (api_socket, web_socket, storage)
        ]
        api_socket.close()
        web_socket.close()
        api_url, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
        env = {
            **os.environ,
            "APP_ENV": "test",
            "TRUST_COPILOT_TESTING": "1",
            "TC_ALLOW_PROVIDER_TESTS": "0",
            "TC_QNR_ACK_API_PORT": str(api_port),
            "TC_QNR_ACK_BASE_URL": web_url,
            "API_UPSTREAM": api_url,
            "FRONTEND_URL": web_url,
            "APP_BASE_URL": web_url,
            "TRUSTED_ORIGINS": web_url,
            "S3_ENDPOINT": f"http://127.0.0.1:{storage_port}",
            "S3_ACCESS_KEY": "test-key",
            "S3_SECRET_KEY": "test-secret",
            "S3_USE_SSL": "false",
            "S3_BUCKET_RAW": "test-qnr-ack-raw",
            "S3_BUCKET_EXPORTS": "test-qnr-ack-exports",
            "TC_QNR_ACK_STORAGE_PORT": str(storage_port),
            "AWS_MAX_ATTEMPTS": "1",
            "AWS_RETRY_MODE": "standard",
            "NO_PROXY": "127.0.0.1,localhost",
            "NEXT_DIST_DIR": ".next",
            "NEXT_TELEMETRY_DISABLED": "1",
            "TC_QNR_ACK_READY_MARKER": str(ready),
            "TC_QNR_ACK_STORAGE_LOG": str(network),
            "TC_QNR_ACK_CHECKPOINT_DIR": str(checkpoints),
            "TC_QNR_ACK_FIXTURE": str(credentials),
            "PLAYWRIGHT_JSON_OUTPUT_FILE": str(output / "report.json"),
            "PLAYWRIGHT_HTML_OUTPUT_DIR": str(html_report),
            "PLAYWRIGHT_HTML_OPEN": "never",
        }
        _safety.scrub_provider_env(env)
        assert env.get("SESSION_SECRET"), "Stable signing secret required"
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
                    [
                        node,
                        str(playwright),
                        "test",
                        "--config=playwright.questionnaire-ack.config.ts",
                        "--max-failures=1",
                    ],
                    web_root,
                    env,
                    tmp_path / "browser.log",
                ) as browser:
                    for width in WIDTHS:
                        qid = data["questionnaires"][str(width)]["id"]
                        ack = _checkpoint(checkpoints, "ready", width, browser)
                        before = _rows("questionnaires")
                        audit_before = _digest(_rows("audit_events"))
                        _role(user_ids[0], workspace_ids[0], "viewer")
                        ack.touch()
                        ack = _checkpoint(checkpoints, "metadata-denied", width, browser)
                        assert _rows("questionnaires") == before
                        assert _digest(_rows("audit_events")) == audit_before
                        _role(user_ids[0], workspace_ids[0], "editor")
                        ack.touch()
                        ack = _checkpoint(checkpoints, "metadata-saved", width, browser)
                        saved = _rows("questionnaires")
                        own = next(row for row in saved if row["id"] == qid)
                        assert json.loads(own["frameworks_json"]) == ["SOC 2", "ISO 27001"]
                        assert json.loads(own["subject_areas_json"]) == ["Other"]
                        assert own["deleted_at"] is not None
                        assert [row for row in saved if row["id"] != qid] == [
                            row for row in before if row["id"] != qid
                        ]
                        original = next(row for row in before if row["id"] == qid)
                        assert {
                            k: v
                            for k, v in own.items()
                            if k not in {"frameworks_json", "updated_at"}
                        } == {
                            k: v
                            for k, v in original.items()
                            if k not in {"frameworks_json", "updated_at"}
                        }
                        _role(user_ids[0], workspace_ids[0], "viewer")
                        ack.touch()
                        ack = _checkpoint(checkpoints, "restore-denied", width, browser)
                        assert _rows("questionnaires") == saved
                        assert _digest(_rows("audit_events")) == audit_before
                        _role(user_ids[0], workspace_ids[0], "editor")
                        ack.touch()
                        ack = _checkpoint(checkpoints, "restored", width, browser)
                        after = _rows("questionnaires")
                        restored = next(row for row in after if row["id"] == qid)
                        assert restored["deleted_at"] is None and restored["deleted_by"] is None
                        assert {
                            k: v
                            for k, v in restored.items()
                            if k not in {"deleted_at", "deleted_by", "updated_at"}
                        } == {
                            k: v
                            for k, v in own.items()
                            if k not in {"deleted_at", "deleted_by", "updated_at"}
                        }
                        assert [row for row in after if row["id"] != qid] == [
                            row for row in before if row["id"] != qid
                        ]
                        assertions.append(
                            {
                                "width": width,
                                "real_403_no_questionnaire_or_audit_write": True,
                                "metadata_200_persisted": True,
                                "restore_200_persisted": True,
                                "all_other_questionnaires_unchanged": True,
                            }
                        )
                        (output / "assertions.json").write_text(
                            json.dumps(assertions, indent=2) + "\n"
                        )
                        ack.touch()
                    browser.wait(timeout=30)
        finally:
            try:
                _closed((api_port, web_port))
            finally:
                _assert_credential_free_reports((output, html_report), data["password"])
        attempts = (
            [json.loads(line) for line in network.read_text().splitlines()]
            if network.exists()
            else []
        )
        assert all(
            item == {"phase": "startup", "kind": "storage"} for item in attempts
        ), "Unexpected outbound or request-time storage call"
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
        assert browser.returncode == 0, "Real browser acceptance failed; inspect report"
        report = json.loads((output / "report.json").read_text())
        assert report["stats"]["expected"] == 3
        assert all(report["stats"][key] == 0 for key in ("unexpected", "skipped", "flaky"))
        assert len(list(output.glob("axe-*.json"))) == 6
        for width in WIDTHS:
            for state in ("metadata-error", "restore-error"):
                axe = json.loads((output / f"axe-{state}-{width}.json").read_text())
                assert axe["width"] == width and axe["state"] == state
                assert axe["violationCount"] == len(axe["violations"]) == 0
                assert (output / f"{state}-{width}.png").stat().st_size > 0
