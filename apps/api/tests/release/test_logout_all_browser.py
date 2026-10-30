"""TC-04-006c: real three-context browser/API/PostgreSQL logout-all acceptance."""

import base64
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import time
import zipfile
import zlib
from pathlib import Path

import pytest
from sqlalchemy import bindparam, text

from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import User, Workspace, WorkspaceMember
from app.models.tag import Tag
from app.services.tag_service import SYSTEM_TAGS
from tests import _safety
from tests.release.test_domain_in_app_notifications import _inbox_service, _inbox_wait_ready

TABLES = ("audit_events", "user_sessions", "workspace_members", "users", "workspaces", "tags")
WIDTHS = (360, 768, 1440)


def _rows(table):
    assert table in TABLES
    with SessionLocal() as db:
        return list(db.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings())


def _digest(rows):
    # Complete-row hashes preserve equality evidence without publishing credentials.
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
def logout_browser_rows(_ensure_test_data, tmp_path):
    assert _ensure_test_data, "Migrated PostgreSQL is required for logout-all browser acceptance"
    baseline = _snapshot()
    token = secrets.token_hex(8)
    user_ids, workspace_ids, tag_ids = [], [], []
    data = {"password": secrets.token_urlsafe(24)}
    try:
        with SessionLocal() as db:
            # Startup catalog rows are owned explicitly, never inferred by key-set difference.
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
            for name, role in (("own", "reviewer"), ("foreign", "editor")):
                while True:
                    wid = 100000 + secrets.randbelow(1000000000)
                    if wid not in workspace_ids and db.get(Workspace, wid) is None:
                        break
                workspace_ids.append(wid)
                db.add(
                    Workspace(id=wid, name=f"Logout browser {name}", slug=f"logout-{name}-{token}")
                )
                user = User(
                    email=f"logout-{name}-{token}@test.local",
                    display_name=f"Synthetic {name}",
                    password_hash=hash_password(data["password"]),
                    email_verified=True,
                )
                db.add(user)
                db.flush()
                user_ids.append(user.id)
                db.add(
                    WorkspaceMember(user_id=user.id, workspace_id=wid, role=role, suspended=False)
                )
                data[name] = user.email
            db.commit()
        # Keep even synthetic passwords out of fixture reprs in failed pytest reports.
        credentials = tmp_path / "credentials.json"
        credentials.write_text(json.dumps(data))
        credentials.chmod(0o600)
        yield credentials, user_ids, workspace_ids
    finally:
        with SessionLocal() as db:
            _delete(db, "audit_events", "user_id", user_ids)
            _delete(db, "audit_events", "workspace_id", workspace_ids)
            _delete(db, "user_sessions", "user_id", user_ids)
            _delete(db, "workspace_members", "workspace_id", workspace_ids)
            _delete(db, "users", "id", user_ids)
            _delete(db, "workspaces", "id", workspace_ids)
            _delete(db, "tags", "id", tag_ids)
            db.commit()
        assert _snapshot() == baseline, "Exact-owned cleanup did not restore complete baseline rows"


# Same guarded subprocess pattern as integrated inbox/Trust acceptance. This API
# branch predates the Trust helper module, so no import of that absent module.
# No application route/dependency/storage method is replaced.
_BOOTSTRAP = """
import errno, json, os, socket
from pathlib import Path
from tests import _safety
_safety.scrub_provider_env()
_safety.validate_test_database_url(os.environ['DATABASE_URL'])
_safety.validate_test_s3_endpoint(os.environ['S3_ENDPOINT'])
_safety.install_network_guard()
port = int(os.environ['TC_LOGOUT_STORAGE_PORT'])
marker = Path(os.environ['TC_LOGOUT_READY_MARKER'])
log = Path(os.environ['TC_LOGOUT_STORAGE_LOG'])
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
uvicorn.run('app.main:app', host='127.0.0.1', port=int(os.environ['TC_LOGOUT_API_PORT']))
"""


def _checkpoint(directory, phase, width, browser):
    marker = directory / f"{phase}-{width}"
    deadline = time.monotonic() + 180
    while not marker.with_suffix(".json").is_file():
        assert browser.poll() is None, "Browser failed before DB checkpoint; inspect its report"
        assert time.monotonic() < deadline, "Browser did not reach the required DB checkpoint"
        time.sleep(0.1)
    assert json.loads(marker.with_suffix(".json").read_text()) == {"phase": phase, "width": width}
    return marker.with_suffix(".ack")


def _closed(ports):
    for port in ports:
        deadline = time.monotonic() + 10
        while True:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) != 0:
                    break
            assert time.monotonic() < deadline, "An owned service still listens after cleanup"
            time.sleep(0.1)


@pytest.mark.integration
def test_logout_all_real_browsers_and_exact_database_effects(logout_browser_rows, tmp_path):
    credentials, user_ids, workspace_ids = logout_browser_rows
    data = json.loads(credentials.read_text())
    api_root = Path(__file__).resolve().parents[2]
    web_root = api_root.parent / "web"
    node = shutil.which("node")
    next_cli = web_root / "node_modules/next/dist/bin/next"
    playwright = web_root / "node_modules/@playwright/test/cli.js"
    assert node and next_cli.is_file() and playwright.is_file(), "Locked web toolchain is required"
    _safety.validate_test_database_url(os.environ["DATABASE_URL"])
    output = web_root / "test-results/logout-all"
    html_report = web_root / "playwright-report/logout-all"
    shutil.rmtree(html_report, ignore_errors=True)
    # Only this acceptance test's artifact directory; old reports cannot count as fresh proof.
    shutil.rmtree(output, ignore_errors=True)
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
            "TC_LOGOUT_API_PORT": str(api_port),
            "TC_LOGOUT_BASE_URL": web_url,
            "API_UPSTREAM": api_url,
            "FRONTEND_URL": web_url,
            "APP_BASE_URL": web_url,
            "TRUSTED_ORIGINS": web_url,
            "S3_ENDPOINT": f"http://127.0.0.1:{storage_port}",
            "S3_ACCESS_KEY": "test-key",
            "S3_SECRET_KEY": "test-secret",
            "S3_USE_SSL": "false",
            "S3_BUCKET_RAW": "test-logout-raw",
            "S3_BUCKET_EXPORTS": "test-logout-exports",
            "TC_LOGOUT_STORAGE_PORT": str(storage_port),
            "AWS_MAX_ATTEMPTS": "1",
            "AWS_RETRY_MODE": "standard",
            "NO_PROXY": "127.0.0.1,localhost",
            "NEXT_DIST_DIR": ".next",
            "NEXT_TELEMETRY_DISABLED": "1",
            "TC_LOGOUT_READY_MARKER": str(ready),
            "TC_LOGOUT_STORAGE_LOG": str(network),
            "TC_LOGOUT_CHECKPOINT_DIR": str(checkpoints),
            "TC_LOGOUT_FIXTURE": json.dumps(data),
            "PLAYWRIGHT_JSON_OUTPUT_FILE": str(output / "report.json"),
            "PLAYWRIGHT_HTML_OUTPUT_DIR": str(web_root / "playwright-report/logout-all"),
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
                    [
                        node,
                        str(playwright),
                        "test",
                        "--config=playwright.logout-all.config.ts",
                        "--max-failures=1",
                    ],
                    web_root,
                    env,
                    tmp_path / "browser.log",
                ) as browser:
                    for index, width in enumerate(WIDTHS):
                        before_ack = _checkpoint(checkpoints, "before", width, browser)
                        before = {table: _rows(table) for table in TABLES}
                        own = [r for r in before["user_sessions"] if r["user_id"] == user_ids[0]]
                        foreign = [
                            r for r in before["user_sessions"] if r["user_id"] == user_ids[1]
                        ]
                        assert len(own) == 2 and len({r["session_id"] for r in own}) == 2
                        assert len(foreign) == index + 1
                        before_ack.touch()
                        after_ack = _checkpoint(checkpoints, "after", width, browser)
                        after = {table: _rows(table) for table in TABLES}
                        assert _digest(after["user_sessions"]) == _digest(
                            [r for r in before["user_sessions"] if r["user_id"] != user_ids[0]]
                        )
                        assert _digest(
                            [r for r in after["user_sessions"] if r["user_id"] == user_ids[1]]
                        ) == _digest(foreign)
                        for table in set(TABLES) - {"user_sessions", "audit_events"}:
                            assert _digest(after[table]) == _digest(
                                before[table]
                            ), f"Unexpected {table} mutation"
                        audit_ids = {r["id"] for r in before["audit_events"]}
                        assert [r for r in after["audit_events"] if r["id"] in audit_ids] == before[
                            "audit_events"
                        ]
                        new_audit = [r for r in after["audit_events"] if r["id"] not in audit_ids]
                        assert len(new_audit) == 1
                        audit = new_audit[0]
                        assert audit["action"] == "auth.sessions_revoked_all"
                        assert (
                            audit["user_id"] == user_ids[0]
                            and audit["workspace_id"] == workspace_ids[0]
                        )
                        assert json.loads(audit["details"]) == {"count": 2}
                        assertions.append(
                            {
                                "width": width,
                                "two_independent_logins": True,
                                "all_own_sessions_removed": True,
                                "foreign_full_rows_unchanged": True,
                                "other_rows_unchanged": True,
                                "one_correct_audit": True,
                            }
                        )
                        (output / "assertions.json").write_text(
                            json.dumps(assertions, indent=2) + "\n"
                        )
                        after_ack.touch()
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
        assert all(
            item == {"phase": "startup", "kind": "storage"} for item in attempts
        ), "Unexpected outbound or post-readiness storage attempt"
        assert browser.returncode == 0, "Real browser acceptance failed; inspect its report"
        report = json.loads((output / "report.json").read_text())
        assert report["stats"]["expected"] == 3
        assert all(report["stats"][key] == 0 for key in ("unexpected", "skipped", "flaky"))
        reports = list(output.glob("axe-*.json"))
        assert len(reports) == 6
        for width in WIDTHS:
            for state in ("page", "dialog"):
                axe = json.loads((output / f"axe-{state}-{width}.json").read_text())
                assert axe["width"] == width and axe["state"] == state
                assert type(axe["violationCount"]) is int
                assert axe["violationCount"] == len(axe["violations"]) == 0
                assert (output / f"{state}-{width}.png").stat().st_size > 0


def _report_payloads(path):
    """Inspect report bytes and the HTML reporter's embedded ZIP, not just its shell."""
    raw = path.read_bytes()
    payloads = [raw]
    embedded = re.search(
        rb'<template id="playwrightReportBase64">data:application/zip;base64,([^<]+)</template>',
        raw,
    )
    if embedded:
        packed = base64.b64decode(embedded[1], validate=True)
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            payloads.extend(archive.read(name) for name in archive.namelist())
    elif b'<template id="playwrightReportBase64">' in raw:
        raise ValueError("Incomplete embedded report payload")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            payloads.extend(archive.read(name) for name in archive.namelist())
    return payloads


def _assert_credential_free_reports(roots, credential):
    """Fail closed and withhold offending files before the always-run CI upload."""
    needle = credential.encode()
    assert needle, "A nonempty private credential is required for the artifact gate"
    rejected = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                unsafe = any(needle in payload for payload in _report_payloads(path))
            except (ValueError, zipfile.BadZipFile, zlib.error):
                unsafe = True
            if unsafe:
                rejected.append(path.relative_to(root).as_posix())
                path.unlink()
    assert not rejected, "Credential-bearing or unreadable report files were withheld from upload"


@pytest.mark.unit
def test_corrupt_embedded_report_is_withheld_without_removing_safe_diagnostics(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    marker = "SYNTHETIC_CORRUPT_REPORT_CREDENTIAL"
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", json.dumps({"title": marker}))
    corrupt = bytearray(packed.getvalue())
    name_length, extra_length = struct.unpack_from("<HH", corrupt, 26)
    # A reserved DEFLATE block type makes the real member decoder reject this ZIP.
    corrupt[30 + name_length + extra_length] = 7
    unsafe = reports / "index.html"
    unsafe.write_bytes(
        b"<p>"
        + marker.encode()
        + b'</p><template id="playwrightReportBase64">data:application/zip;base64,'
        + base64.b64encode(corrupt)
        + b"</template>"
    )
    safe = reports / "safe.json"
    safe.write_text('{"failure":"Safe failure diagnostics"}')

    with pytest.raises(AssertionError, match="withheld from upload"):
        _assert_credential_free_reports((reports,), marker)

    assert not unsafe.exists()
    assert safe.read_text() == '{"failure":"Safe failure diagnostics"}'


@pytest.mark.unit
def test_password_helper_keeps_generated_success_and_failure_reports_credential_free(tmp_path):
    """Browserless installed-renderer/report proof; real login remains a separate PG gate."""
    web_root = Path(__file__).resolve().parents[2].parent / "web"
    node = shutil.which("node")
    cli = web_root / "node_modules/@playwright/test/cli.js"
    assert node and cli.is_file(), "Locked Playwright is required for credential-report regression"
    marker = "SYNTHETIC_REPORT_CREDENTIAL_" + secrets.token_hex(12)
    report = tmp_path / "report.json"
    html = tmp_path / "html"
    spec = tmp_path / "credential-report.spec.cjs"
    spec.write_text(
        r"""
const { test, expect } = require('@playwright/test');
const { iso } = require('playwright-core/lib/coreBundle');
const ts = require('typescript');
const fs = require('node:fs');
const source = fs.readFileSync(process.env.TC_LOGOUT_BROWSER_SOURCE, 'utf8');
const tree = ts.createSourceFile('acceptance.ts', source, ts.ScriptTarget.Latest, true);
const helper = tree.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'enterPassword');
if (!helper) throw new Error('Actual password-entry helper is missing');
const js = ts.transpile(helper.getText(tree), { target: ts.ScriptTarget.ES2022 });
const enterPassword = new Function(`${js}; return enterPassword;`)();
for (const fail of [false, true]) {
  test(fail ? 'synthetic reported failure' : 'synthetic reported success', async () => {
    const { Window } = await import(require.resolve('happy-dom'));
    const window = new Window();
    global.HTMLInputElement = window.HTMLInputElement;
    global.Event = window.Event;
    const input = window.document.createElement('input');
    input.type = 'password';
    window.document.body.append(input);
    let observed = false;
    const marker = process.env.TC_LOGOUT_REPORT_MARKER;
    input.addEventListener('input', () => { observed = input.value === marker; });
    async function call(metadata, action) {
      // Same installed metadata renderer/_addStep path as onApiCallBegin in lib/index.js.
      const step = test.info()._addStep({category:'pw:api', title:iso.renderTitleForCall(metadata),
        subtitle:iso.renderSubtitleForCall(metadata), params:iso.renderParamsForCall(metadata)});
      try {
        const result = await action();
        if (fail) throw new Error('Synthetic credential-entry failure retained');
        step.complete({});
        return result;
      } catch (error) { step.complete({error}); throw error; }
    }
    const page = { getByLabel(name) {
      expect(name).toBe('Password');
      return {
        evaluate(fn, value) { return call({type:'ElementHandle', method:'evaluateExpression',
          params:{expression:String(fn), isFunction:true, arg:{value:{s:value}, handles:[]}}}, () => fn(input, value)); },
        // Negative-control methods use the installed unsafe metadata as well.
        pressSequentially(value) { return call({type:'Frame', method:'type',
          params:{selector:'input[type=password]', text:value}}, () => { input.value=value; observed=true; }); },
        fill(value) { return call({type:'Frame', method:'fill',
          params:{selector:'input[type=password]', value}}, () => { input.value=value; observed=true; }); },
      };
    }};
    try {
      await enterPassword(page, marker);
      expect(observed).toBe(true);
    } finally { await window.happyDOM.close(); }
  });
}
"""
    )
    config = tmp_path / "report.config.cjs"
    config.write_text(
        "module.exports = "
        + json.dumps(
            {
                "testDir": str(tmp_path),
                "testMatch": spec.name,
                "workers": 1,
                "retries": 0,
                "reporter": [
                    ["json", {"outputFile": str(report)}],
                    ["html", {"outputFolder": str(html), "open": "never"}],
                ],
                "outputDir": str(tmp_path / "results"),
                "use": {"trace": "off", "screenshot": "off", "video": "off"},
            }
        )
    )
    env = {
        **os.environ,
        "NODE_PATH": str(web_root / "node_modules"),
        "TC_LOGOUT_REPORT_MARKER": marker,
        "TC_LOGOUT_BROWSER_SOURCE": str(web_root / "e2e/integration/logout-all.acceptance.ts"),
    }
    # Existing reporter env overrides must not redirect this proof into uploaded acceptance files.
    for name in ("PLAYWRIGHT_JSON_OUTPUT_FILE", "PLAYWRIGHT_HTML_OUTPUT_DIR"):
        env.pop(name, None)
    result = subprocess.run(
        [node, str(cli), "test", f"--config={config}"],
        cwd=web_root,
        env=env,
        capture_output=True,
        timeout=90,
    )
    assert result.returncode == 1, "The synthetic failure must remain a reported failure"
    data = json.loads(report.read_text())
    assert data["stats"]["expected"] == 1 and data["stats"]["unexpected"] == 1
    assert data["stats"]["skipped"] == data["stats"]["flaky"] == 0
    payloads = _report_payloads(report) + _report_payloads(html / "index.html")
    assert all(marker.encode() not in payload for payload in payloads)
    assert b"Synthetic credential-entry failure retained" in report.read_bytes()
    assert any(
        b"Synthetic credential-entry failure retained" in item
        for item in _report_payloads(html / "index.html")[1:]
    )
    _assert_credential_free_reports((html, tmp_path / "results"), marker)
    assert report.is_file() and (html / "index.html").is_file()
    assert any(
        b"Synthetic credential-entry failure retained" in item
        for item in _report_payloads(html / "index.html")[1:]
    ), "Safe failure diagnostics must survive the artifact gate"

    # A regression must fail acceptance and withhold both plain and compressed leaks.
    leaked = tmp_path / "leak-control"
    leaked.mkdir()
    (leaked / "plain.json").write_text(json.dumps({"title": marker}))
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.json", json.dumps({"params": {"text": marker}}))
    (leaked / "index.html").write_bytes(
        b'<template id="playwrightReportBase64">data:application/zip;base64,'
        + base64.b64encode(packed.getvalue())
        + b"</template>"
    )
    with pytest.raises(AssertionError, match="withheld from upload"):
        _assert_credential_free_reports((leaked,), marker)
    assert list(leaked.iterdir()) == []
