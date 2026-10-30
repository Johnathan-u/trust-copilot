"""TC-15-039b: actual browser/API/PostgreSQL reply persistence and denied attachments."""

import hashlib
import json
import os
import secrets
import shutil
import socket
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import bindparam, inspect, text

from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import TrustRequest, TrustRequestNote, User, Workspace, WorkspaceMember
from app.models.tag import Tag
from app.models.trust_request_note import NOTE_TYPE_INTERNAL
from app.services.tag_service import SYSTEM_TAGS
from tests import _safety
from tests.release.test_domain_in_app_notifications import _inbox_service, _inbox_wait_ready

pytestmark = pytest.mark.integration

# Explicit cleanup scopes; never delete another test's key-set difference.
WORKSPACE_TABLES = (
    "in_app_notification_receipts_archive",
    "in_app_notification_receipts",
    "notification_delivery_attempts",
    "notification_log",
    "notification_channel_preferences",
    "notification_unsubscribes",
    "notification_policies",
    "in_app_notifications",
)
SNAPSHOT_TABLES = (
    *WORKSPACE_TABLES,
    "notification_dedupe_claims",
    "trust_request_notes",
    "trust_requests",
    "audit_events",
    "idempotency_keys",
    "user_sessions",
    "workspace_members",
    "users",
    "workspaces",
    "tags",
)


def _snapshots():
    """Hash complete rows, retaining equality evidence without exposing credentials."""
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


@pytest.fixture
def trust_browser_rows(_ensure_test_data):
    assert _ensure_test_data, "PostgreSQL is required for incoming Trust browser acceptance"
    baseline = _snapshots()
    token = secrets.token_hex(8)
    ws_ids, user_ids, request_ids, tag_ids = [], [], [], set()
    data = {"created_tag_ids": tag_ids}
    try:
        with SessionLocal() as db:
            # Seed any absent startup catalog rows ourselves and retain only the
            # IDs we inserted. Cleanup must never infer ownership from a global diff.
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
                    tag_ids.add(tag.id)
            # Explicit unused IDs avoid resetting a global serial sequence to seeded IDs.
            for suffix in ("own", "foreign"):
                while True:
                    wid = 100000 + secrets.randbelow(1000000000)
                    if wid not in ws_ids and db.get(Workspace, wid) is None:
                        break
                ws_ids.append(wid)
                db.add(
                    Workspace(
                        id=wid, name=f"Trust browser {suffix}", slug=f"trust-ui-{suffix}-{token}"
                    )
                )
            db.flush()
            data["workspaceId"] = ws_ids[0]
            for role in ("reviewer", "admin"):
                user = User(
                    email=f"trust-browser-{role}-{token}@test.local",
                    display_name=f"Synthetic {role}",
                    password_hash=hash_password("test-password"),
                    email_verified=True,
                )
                db.add(user)
                db.flush()
                user_ids.append(user.id)
                member = WorkspaceMember(
                    workspace_id=ws_ids[0], user_id=user.id, role=role, suspended=False
                )
                db.add(member)
                db.flush()
                data[role] = {"id": user.id, "email": user.email, "memberId": member.id}
            for name, wid, filename, key in (
                ("main", ws_ids[0], None, None),
                # Deliberate missing attachment metadata: no object or upload is claimed.
                ("attachment", ws_ids[0], "synthetic-missing.txt", None),
                ("foreign", ws_ids[1], "synthetic-foreign.txt", f"never-read/{token}"),
            ):
                row = TrustRequest(
                    workspace_id=wid,
                    requester_email=f"synthetic-buyer-{token}@example.com",
                    subject=f"Synthetic {name} request",
                    message="Synthetic incoming request for browser acceptance.",
                    status="new",
                    attachment_filename=filename,
                    attachment_storage_key=key,
                    intake_version=1,
                )
                db.add(row)
                db.flush()
                request_ids.append(row.id)
                data[name] = {"id": row.id, "subject": row.subject}
            internal = TrustRequestNote(
                trust_request_id=data["main"]["id"],
                author_id=data["admin"]["id"],
                note_type=NOTE_TYPE_INTERNAL,
                body="Synthetic internal review note.",
                body_revision=1,
            )
            db.add(internal)
            db.flush()
            data["internalId"] = internal.id
            assert db.get(TrustRequest, 2147483647) is None
            data.update(missingId=2147483647, password="test-password")
            db.commit()
        yield data
    finally:
        with SessionLocal() as db:
            tables = set(inspect(db.connection()).get_table_names())
            claims = set()
            for name in ("notification_delivery_attempts", "notification_log"):
                if name in tables:
                    result = _in_ids(
                        db, f"SELECT dedupe_key FROM {name} WHERE workspace_id IN :ids", ws_ids
                    )
                    if result is not None:
                        claims.update(key for key in result.scalars() if key)
            for name in WORKSPACE_TABLES:
                if name in tables:
                    _in_ids(db, f"DELETE FROM {name} WHERE workspace_id IN :ids", ws_ids)
            _in_ids(
                db, "DELETE FROM notification_dedupe_claims WHERE dedupe_key IN :ids", list(claims)
            )
            _in_ids(db, "DELETE FROM audit_events WHERE workspace_id IN :ids", ws_ids)
            _in_ids(db, "DELETE FROM audit_events WHERE user_id IN :ids", user_ids)
            _in_ids(
                db, "DELETE FROM trust_request_notes WHERE trust_request_id IN :ids", request_ids
            )
            _in_ids(db, "DELETE FROM trust_requests WHERE id IN :ids", request_ids)
            _in_ids(db, "DELETE FROM user_sessions WHERE user_id IN :ids", user_ids)
            _in_ids(db, "DELETE FROM workspace_members WHERE workspace_id IN :ids", ws_ids)
            _in_ids(db, "DELETE FROM users WHERE id IN :ids", user_ids)
            _in_ids(db, "DELETE FROM workspaces WHERE id IN :ids", ws_ids)
            _in_ids(db, "DELETE FROM tags WHERE id IN :ids", list(tag_ids))
            db.commit()
        after = _snapshots()
        assert after == baseline, "Owned cleanup did not restore complete baseline table hashes"


# No route/dependency/storage-method replacement. Deny the reserved synthetic
# storage endpoint at the socket boundary, after installing the existing guard.
# Startup attempts are expected and explicit; every post-readiness attempt fails acceptance.
_BOOTSTRAP = """
import errno, json, os, socket
from pathlib import Path
from tests import _safety
_safety.scrub_provider_env()
_safety.validate_test_database_url(os.environ['DATABASE_URL'])
_safety.validate_test_s3_endpoint(os.environ['S3_ENDPOINT'])
_safety.install_network_guard()
port = int(os.environ['TC_TRUST_STORAGE_PORT'])
marker = Path(os.environ['TC_TRUST_READY_MARKER'])
log = Path(os.environ['TC_TRUST_STORAGE_LOG'])
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
uvicorn.run('app.main:app', host='127.0.0.1', port=int(os.environ['TC_TRUST_API_PORT']))
"""


def _rows(table, ids, column="id"):
    with SessionLocal() as db:
        return [
            dict(row)
            for row in _in_ids(
                db, f"SELECT * FROM {table} WHERE {column} IN :ids ORDER BY id", ids
            ).mappings()
        ]


def _json_row(row):
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in row.items()
    }


def _closed(ports):
    for port in ports:
        deadline = time.monotonic() + 10
        while True:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) != 0:
                    break
            assert time.monotonic() < deadline, "An owned service still listens after cleanup"
            time.sleep(0.1)


def test_trust_reply_persistence_and_denials_after_process_restart(trust_browser_rows, tmp_path):
    data = trust_browser_rows
    api_root = Path(__file__).resolve().parents[2]
    web_root = api_root.parent / "web"
    node = shutil.which("node")
    next_cli = web_root / "node_modules/next/dist/bin/next"
    playwright = web_root / "node_modules/@playwright/test/cli.js"
    assert node and next_cli.is_file() and playwright.is_file(), "Locked web toolchain is required"
    _safety.validate_test_database_url(os.environ["DATABASE_URL"])
    request_ids = [data[name]["id"] for name in ("main", "attachment", "foreign")]
    seeded_requests = _rows("trust_requests", request_ids)
    seeded_internal = _rows("trust_request_notes", [data["internalId"]])
    output = web_root / "test-results/trust-requests-restart"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("before.json", "after.json", "processes.json", "assertions.json"):
        (output / name).unlink(missing_ok=True)
    checkpoints = []
    before_replies = None
    # Reserve three distinct ports together. Keep storage bound but not listening:
    # it belongs to this test and cannot accidentally name another local service.
    with (
        socket.socket() as api_socket,
        socket.socket() as web_socket,
        socket.socket() as storage_socket,
    ):
        for listener in (api_socket, web_socket, storage_socket):
            listener.bind(("127.0.0.1", 0))
        api_port, web_port, storage_port = [
            listener.getsockname()[1] for listener in (api_socket, web_socket, storage_socket)
        ]
        api_socket.close()
        web_socket.close()
        api_url, web_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
        env = {
            **os.environ,
            "APP_ENV": "test",
            "TRUST_COPILOT_TESTING": "1",
            "TC_ALLOW_PROVIDER_TESTS": "0",
            "TC_TRUST_API_PORT": str(api_port),
            "TC_TRUST_BASE_URL": web_url,
            "API_UPSTREAM": api_url,
            "FRONTEND_URL": web_url,
            "APP_BASE_URL": web_url,
            "TRUSTED_ORIGINS": web_url,
            "S3_ENDPOINT": f"http://127.0.0.1:{storage_port}",
            "S3_ACCESS_KEY": "test-key",
            "S3_SECRET_KEY": "test-secret",
            "S3_USE_SSL": "false",
            "S3_BUCKET_RAW": "test-trust-raw",
            "S3_BUCKET_EXPORTS": "test-trust-exports",
            "TC_TRUST_STORAGE_PORT": str(storage_port),
            "AWS_MAX_ATTEMPTS": "1",
            "AWS_RETRY_MODE": "standard",
            "NO_PROXY": "127.0.0.1,localhost",
            "NEXT_DIST_DIR": ".next",
            "NEXT_TELEMETRY_DISABLED": "1",
            "PLAYWRIGHT_HTML_OPEN": "never",
        }
        _safety.scrub_provider_env(env)
        assert env.get("SESSION_SECRET"), "Stable signing secret required across restarts"
        for phase in ("before", "after"):
            ready = tmp_path / f"ready-{phase}"
            storage_log = output / f"network-{phase}.jsonl"
            storage_log.unlink(missing_ok=True)
            phase_env = {
                **env,
                "TC_TRUST_PHASE": phase,
                "TC_TRUST_FIXTURE": json.dumps(
                    {k: v for k, v in data.items() if k != "created_tag_ids"}
                ),
                "TC_TRUST_READY_MARKER": str(ready),
                "TC_TRUST_STORAGE_LOG": str(storage_log),
                "PLAYWRIGHT_JSON_OUTPUT_FILE": str(output / f"{phase}.json"),
                "PLAYWRIGHT_HTML_OUTPUT_DIR": str(
                    web_root / "playwright-report/trust-requests-restart" / phase
                ),
            }
            with (
                _inbox_service(
                    [sys.executable, "-c", _BOOTSTRAP],
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
                ready.touch()
                if before_replies is not None:
                    assert (
                        _rows("trust_request_notes", [row["id"] for row in before_replies])
                        == before_replies
                    )
                with _inbox_service(
                    [
                        node,
                        str(playwright),
                        "test",
                        "--config=playwright.trust-requests.config.ts",
                        "--grep",
                        f"{phase} restart:",
                    ],
                    web_root,
                    phase_env,
                    tmp_path / f"browser-{phase}.log",
                ) as browser:
                    browser.wait(timeout=240)
            _closed((api_port, web_port))
            attempts = [json.loads(line) for line in storage_log.read_text().splitlines()]
            assert attempts and all(
                item == {"phase": "startup", "kind": "storage"} for item in attempts
            ), "Unexpected outbound attempt or storage access after readiness"
            checkpoints.append(
                {
                    "phase": phase,
                    "api_pid": api.pid,
                    "web_pid": web.pid,
                    "api_exit": api.returncode,
                    "web_exit": web.returncode,
                    "browser_exit": browser.returncode,
                    "startup_storage_denials": len(attempts),
                    "post_ready_storage_attempts": 0,
                    "external_attempts": 0,
                }
            )
            (output / "processes.json").write_text(json.dumps(checkpoints, indent=2) + "\n")
            assert (
                browser.returncode == 0
            ), "Real browser phase failed; inspect its sanitized report"
            report = json.loads((output / f"{phase}.json").read_text())
            assert report["stats"]["expected"] == 1
            assert all(report["stats"][key] == 0 for key in ("unexpected", "skipped", "flaky"))
            assert (
                _rows("trust_requests", request_ids) == seeded_requests
            ), "Read/denial paths changed request rows"
            assert (
                _rows("trust_request_notes", [data["internalId"]]) == seeded_internal
            ), "Internal note changed"
            assert not _rows(
                "trust_request_notes",
                [data["attachment"]["id"], data["foreign"]["id"]],
                "trust_request_id",
            ), "Attachment denial created an unexpected note"
            replies = [
                row
                for row in _rows("trust_request_notes", [data["main"]["id"]], "trust_request_id")
                if row["note_type"] == "reply"
            ]
            assert len(replies) == 3
            if phase == "before":
                for row in replies[:2]:
                    assert row["body_revision"] == row["approved_revision"] == 1
                    assert (
                        row["approved_by"] == data["reviewer"]["id"]
                        and row["approved_at"] is not None
                    )
                    assert (
                        row["approved_body_hash"]
                        == hashlib.sha256(row["body"].encode()).hexdigest()
                    )
                    assert row["delivery_status"] == "approved" and row["delivery_attempts"] == 0
                draft = replies[2]
                assert draft["body"] == "Persisted unapproved draft."
                assert draft["body_revision"] == 1 and draft["delivery_status"] == "draft"
                assert draft["delivery_attempts"] == 0
                assert all(
                    draft[key] is None
                    for key in (
                        "approved_revision",
                        "approved_by",
                        "approved_at",
                        "approved_body_hash",
                        "delivery_started_at",
                        "delivery_accepted_at",
                    )
                )
                before_replies = replies
                data["persisted"] = [_json_row(row) for row in replies]
            else:
                edited = next(row for row in replies if row["id"] == data["persisted"][0]["id"])
                delivery = next(row for row in replies if row["id"] == data["persisted"][1]["id"])
                assert replies[2] == before_replies[2], "Unapproved draft changed"
                assert (
                    edited["body"] == "Concurrent saved revision." and edited["body_revision"] == 3
                )
                assert all(
                    edited[key] is None
                    for key in (
                        "approved_revision",
                        "approved_by",
                        "approved_at",
                        "approved_body_hash",
                    )
                )
                assert edited["delivery_status"] == "draft" and edited["delivery_attempts"] == 0
                assert delivery == {
                    **before_replies[1],
                    "delivery_status": "unavailable",
                    "delivery_error": "delivery_unavailable",
                }
                assert (
                    delivery["delivery_started_at"] is None
                    and delivery["delivery_accepted_at"] is None
                )
        assert checkpoints[0]["api_pid"] != checkpoints[1]["api_pid"]
        assert checkpoints[0]["web_pid"] != checkpoints[1]["web_pid"]
        (output / "assertions.json").write_text(
            json.dumps(
                {
                    "restart_persisted": True,
                    "approval_invalidated": True,
                    "stale_save_rejected": True,
                    "delivery_unavailable_without_attempt": True,
                    "protected_rows_unchanged": True,
                    "post_ready_storage_attempts": 0,
                },
                indent=2,
            )
            + "\n"
        )
