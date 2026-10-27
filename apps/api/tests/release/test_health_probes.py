"""TC-03-003 release test: separate readiness, liveness and worker health.

AC1  Dependency loss fails readiness without misreporting process liveness.
AC2  Long-running healthy jobs refresh heartbeat and the worker does not inherit a nonexistent
     HTTP probe.

Synthetic data only. Dependencies are simulated with mocks/fake clocks; the database used is the
local throwaway test database configured by tests/conftest.py. No network beyond that.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core import database
from app.core.config import get_settings
from app.main import app

API_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = API_DIR.parents[1]

# Synthetic "secrets" embedded in simulated driver errors; must never reach a probe response.
FAKE_DB_DSN = "postgresql://synthetic_user:synthetic-pw-7f3a@db.internal.example:5432/prod"
FAKE_S3_DETAIL = (
    "http://minio.internal.example:9000 AccessKey=AKIASYNTHETIC0000 secret=synthetic-s3-9c1e"
)
LEAK_MARKERS = (
    "synthetic-pw-7f3a",
    "db.internal.example",
    "synthetic_user",
    "AKIASYNTHETIC0000",
    "synthetic-s3-9c1e",
    "minio.internal.example",
)


@pytest.fixture
def api() -> TestClient:
    # No lifespan: probes must work without startup side effects.
    return TestClient(app)


@pytest.fixture
def storage_ok():
    with patch("app.main.StorageClient") as mock_storage:
        mock_storage.return_value.ping.return_value = None
        yield mock_storage


def _db_down():
    err = OperationalError("SELECT 1", {}, Exception(f"could not connect to server: {FAKE_DB_DSN}"))
    return patch.object(database.engine, "connect", side_effect=err)


def _assert_no_leak(body: str) -> None:
    for marker in LEAK_MARKERS:
        assert (
            marker not in body
        ), f"probe response leaked synthetic secret marker #{LEAK_MARKERS.index(marker)}"


# --------------------------------------------------------------------------------------------
# AC1: readiness vs liveness
# --------------------------------------------------------------------------------------------


def test_readyz_ready_reports_each_check(api, storage_ok):
    r = api.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "storage": "ok"}


def test_database_loss_fails_readiness_but_not_liveness(api, storage_ok):
    with _db_down():
        ready = api.get("/readyz")
        live = api.get("/healthz")
    assert ready.status_code == 503
    body = ready.json()
    assert body["status"] == "not ready"
    assert body["checks"]["database"] == "unavailable"
    assert body["checks"]["storage"] == "ok"
    assert any(e.startswith("database:") for e in body["errors"])
    _assert_no_leak(ready.text)
    assert live.status_code == 200
    assert live.json() == {"status": "ok"}


def test_storage_loss_fails_readiness_but_not_liveness(api):
    with patch("app.main.StorageClient") as mock_storage:
        mock_storage.return_value.ping.side_effect = ConnectionError(FAKE_S3_DETAIL)
        ready = api.get("/readyz")
        live = api.get("/healthz")
    assert ready.status_code == 503
    body = ready.json()
    assert body["checks"] == {"database": "ok", "storage": "unavailable"}
    assert any(e.startswith("s3:") for e in body["errors"])
    _assert_no_leak(ready.text)
    assert live.status_code == 200


def test_hanging_dependency_fails_readiness_within_timeout(api, monkeypatch):
    monkeypatch.setenv("READINESS_TIMEOUT_SEC", "0.3")
    get_settings.cache_clear()
    release = threading.Event()
    try:
        with patch("app.main.StorageClient") as mock_storage:
            mock_storage.return_value.ping.side_effect = lambda: release.wait(10)
            t0 = time.monotonic()
            ready = api.get("/readyz")
            elapsed = time.monotonic() - t0
    finally:
        release.set()
        get_settings.cache_clear()
    assert ready.status_code == 503
    assert ready.json()["checks"]["storage"] == "timeout"
    assert elapsed < 3.0, f"readyz blocked {elapsed:.2f}s on a hung dependency"


def test_liveness_never_touches_dependencies(api):
    connect = MagicMock(side_effect=AssertionError("healthz touched the database"))
    with (
        patch.object(database.engine, "connect", connect),
        patch("app.main.StorageClient") as mock_storage,
    ):
        r = api.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    connect.assert_not_called()
    mock_storage.assert_not_called()


# --------------------------------------------------------------------------------------------
# /workerz: configurable staleness, redacted failure
# --------------------------------------------------------------------------------------------


def _set_db_heartbeat(age_sec: float) -> None:
    ts = (datetime.now(UTC) - timedelta(seconds=age_sec)).replace(tzinfo=None)
    with database.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO worker_heartbeat (id, last_seen_utc) VALUES (1, :ts) "
                "ON CONFLICT (id) DO UPDATE SET last_seen_utc = EXCLUDED.last_seen_utc"
            ),
            {"ts": ts},
        )


def test_workerz_fresh_heartbeat_is_alive(api):
    _set_db_heartbeat(5)
    r = api.get("/workerz")
    assert r.status_code == 200
    body = r.json()
    assert body["worker_alive"] is True
    assert body["status"] == "ok"
    assert body["stale_after_sec"] == 120
    assert 0 <= body["last_seen_age_sec"] < 60


def test_workerz_stale_heartbeat_is_503(api):
    _set_db_heartbeat(600)
    r = api.get("/workerz")
    assert r.status_code == 503
    body = r.json()
    assert body["worker_alive"] is False
    assert body["status"] == "stale"


def test_workerz_staleness_threshold_is_configurable(api, monkeypatch):
    _set_db_heartbeat(600)
    monkeypatch.setenv("WORKER_HEARTBEAT_STALE_SEC", "900")
    r = api.get("/workerz")
    assert r.status_code == 200
    assert r.json()["stale_after_sec"] == 900


def test_workerz_store_unavailable_is_unknown_and_redacted(api):
    with _db_down():
        r = api.get("/workerz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unknown"
    assert body["worker_alive"] is False
    assert body["error"].startswith("heartbeat store unavailable")
    _assert_no_leak(r.text)


# --------------------------------------------------------------------------------------------
# AC2: heartbeat keeps beating through long healthy jobs, stops when unhealthy
# --------------------------------------------------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, sec: float) -> None:
        self.now += sec


def _thread(state, tmp_path, write_db=None, max_job=3600, stall=120):
    from app.worker_health import HeartbeatThread

    return HeartbeatThread(
        state,
        write_db or MagicMock(),
        interval_sec=15,
        max_job_sec=max_job,
        stall_sec=stall,
        file_path=tmp_path / "hb",
    )


def test_long_healthy_job_keeps_refreshing_heartbeat(tmp_path):
    from app.worker_health import HeartbeatState

    clock = FakeClock()
    state = HeartbeatState(clock)
    write_db = MagicMock()
    hb = _thread(state, tmp_path, write_db)
    state.job_started(42)
    # 50 minutes of a single job, beating every 15s: far beyond the 120s stale threshold.
    for _ in range(200):
        clock.advance(15)
        assert hb.beat_once() is True
    assert hb.beats == 200
    assert hb.skipped == 0
    assert write_db.call_count == 200
    assert (tmp_path / "hb").exists()


def test_job_over_max_runtime_withholds_heartbeat(tmp_path, caplog):
    from app.worker_health import HeartbeatState

    clock = FakeClock()
    state = HeartbeatState(clock)
    hb = _thread(state, tmp_path, max_job=600)
    state.job_started(7)
    clock.advance(601)
    with caplog.at_level(logging.WARNING):
        assert hb.beat_once() is False
    assert hb.skipped == 1
    assert "ALERT_WORKER_UNHEALTHY" in caplog.text
    state.job_finished()
    assert hb.beat_once() is True


def test_stalled_claim_loop_withholds_heartbeat(tmp_path):
    from app.worker_health import HeartbeatState

    clock = FakeClock()
    state = HeartbeatState(clock)
    hb = _thread(state, tmp_path, stall=120)
    clock.advance(60)
    assert hb.beat_once() is True
    clock.advance(200)
    assert hb.beat_once() is False
    state.loop_tick()
    assert hb.beat_once() is True


def test_db_write_failure_does_not_kill_heartbeat(tmp_path, caplog):
    from app.worker_health import HeartbeatState

    state = HeartbeatState(FakeClock())
    write_db = MagicMock(side_effect=OperationalError("UPDATE", {}, Exception(FAKE_DB_DSN)))
    hb = _thread(state, tmp_path, write_db)
    with caplog.at_level(logging.WARNING):
        assert hb.beat_once() is True
        assert hb.beat_once() is True
    assert hb.db_failures == 2
    assert (tmp_path / "hb").exists(), "local liveness file must still be refreshed"
    _assert_no_leak(caplog.text)


def test_heartbeat_thread_runs_in_background(tmp_path):
    from app.worker_health import HeartbeatState, HeartbeatThread

    state = HeartbeatState()
    beat = threading.Event()
    hb = HeartbeatThread(
        state,
        beat.set,
        interval_sec=0.05,
        max_job_sec=3600,
        stall_sec=120,
        file_path=tmp_path / "hb",
    )
    hb.start()
    try:
        assert beat.wait(2), "background heartbeat never wrote"
    finally:
        hb.stop()
        hb.join(2)
    assert not hb.is_alive()


def test_worker_job_execution_marks_job_running_for_heartbeat(monkeypatch, tmp_path):
    """While run_job executes for longer than the loop-stall threshold, the heartbeat still beats."""
    from app import worker
    from app.worker_health import HeartbeatThread

    monkeypatch.setattr(worker, "last_usage_cleanup_run", time.time())
    monkeypatch.setattr(worker, "last_compliance_webhook_run", time.time())
    fake_job = SimpleNamespace(
        id=990001,
        kind="synthetic_probe",
        workspace_id=1,
        payload=None,
        status="running",
        error=None,
        completed_at=None,
    )
    monkeypatch.setattr(worker, "claim_job", lambda session: fake_job)
    monkeypatch.setattr(worker, "_persist_job_audit", lambda *a, **k: None)
    observed: dict = {}

    def slow_job(job, session):
        hb = HeartbeatThread(
            worker.HEARTBEAT_STATE,
            MagicMock(),
            interval_sec=1,
            max_job_sec=3600,
            stall_sec=0.2,
            file_path=tmp_path / "hb",
        )
        time.sleep(0.4)  # longer than stall_sec with no loop tick
        observed["beat_during_job"] = hb.beat_once()
        observed["reason"] = worker.HEARTBEAT_STATE.assess(max_job_sec=3600, stall_sec=0.2)[1]

    monkeypatch.setattr(worker, "run_job", slow_job)
    assert worker._process_one_job() is True
    assert observed["beat_during_job"] is True
    assert observed["reason"].startswith("job 990001")
    assert fake_job.status == "completed"
    healthy, reason = worker.HEARTBEAT_STATE.assess(max_job_sec=3600, stall_sec=120)
    assert healthy and reason == "idle"


def test_worker_main_starts_background_heartbeat(monkeypatch):
    from app import worker

    class Stop(BaseException):
        pass

    started = []

    class FakeThread:
        def __init__(self, state, write_db, **kw):
            assert state is worker.HEARTBEAT_STATE
            assert write_db is worker.write_db_heartbeat
            started.append(self)

        def start(self):
            started.append("started")

    monkeypatch.setattr(worker, "HeartbeatThread", FakeThread)
    monkeypatch.setattr(worker, "enqueue_missing_index_jobs", lambda s: None)
    monkeypatch.setattr(worker, "_process_one_job", MagicMock(side_effect=Stop))
    with pytest.raises(Stop):
        worker.main()
    assert "started" in started


def test_worker_db_heartbeat_write_is_read_as_fresh(api):
    from app import worker

    _set_db_heartbeat(10_000)
    worker.write_db_heartbeat()
    r = api.get("/workerz")
    assert r.status_code == 200
    assert r.json()["last_seen_age_sec"] < 30


# --------------------------------------------------------------------------------------------
# AC2: worker container probe is role-aware and never uses HTTP
# --------------------------------------------------------------------------------------------


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("worker probe attempted network I/O")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr("urllib.request.urlopen", refuse)


def test_worker_probe_fresh_file_is_healthy_without_http(tmp_path, monkeypatch, no_network):
    from app import probe
    from app.worker_health import touch_heartbeat_file

    hb = tmp_path / "hb"
    monkeypatch.setenv("WORKER_HEARTBEAT_FILE", str(hb))
    touch_heartbeat_file(hb)
    assert probe.main(["worker"]) == 0
    monkeypatch.setenv("TC_PROCESS_ROLE", "worker")
    assert probe.main([]) == 0


def test_worker_probe_stale_or_missing_file_is_unhealthy(tmp_path, monkeypatch, no_network):
    from app import probe
    from app.worker_health import touch_heartbeat_file

    hb = tmp_path / "hb"
    monkeypatch.setenv("WORKER_HEARTBEAT_FILE", str(hb))
    assert probe.main(["worker"]) == 1
    touch_heartbeat_file(hb)
    old = time.time() - 600
    os.utime(hb, (old, old))
    assert probe.main(["worker"]) == 1


def test_api_probe_uses_loopback_healthz_and_unknown_role_fails(monkeypatch):
    from app import probe

    seen = {}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout):
        seen["url"] = url
        return Resp()

    monkeypatch.setattr(probe.urllib.request, "urlopen", fake_urlopen)
    assert probe.main(["api"]) == 0
    assert seen["url"] == "http://127.0.0.1:8000/healthz"
    assert probe.main(["mystery"]) == 1


def test_worker_probe_cli_end_to_end(tmp_path):
    """Real `python -S -m app.probe worker`: -S (no site-packages) proves the probe is stdlib-only."""
    from app.worker_health import touch_heartbeat_file

    hb = tmp_path / "hb"
    touch_heartbeat_file(hb)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "SYSTEMROOT")}
    env.update({"WORKER_HEARTBEAT_FILE": str(hb), "PYTHONPATH": str(API_DIR)})
    res = subprocess.run(
        check=False,
        args=[sys.executable, "-S", "-m", "app.probe", "worker"],
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "healthy" in res.stdout


# --------------------------------------------------------------------------------------------
# Deployment wiring (text-parsed; never print compose contents, which hold deploy config)
# --------------------------------------------------------------------------------------------


def _service_block(compose_text: str, name: str) -> str:
    lines = compose_text.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if re.match(rf"^  {re.escape(name)}:\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^  \S", line):
            break
        if inside and re.match(r"^\S", line):
            break
        if inside:
            out.append(line)
    return "\n".join(out)


def _healthcheck_test(block: str) -> str | None:
    m = re.search(
        r"^    healthcheck:\s*\n(?:      .*\n)*?      test:\s*(.+)$", block + "\n", re.MULTILINE
    )
    return m.group(1).strip() if m else None


@pytest.mark.parametrize("compose", ["docker-compose.prod.yml", "docker-compose.yml"])
def test_compose_worker_has_non_http_probe(compose):
    block = _service_block((REPO_ROOT / compose).read_text(encoding="utf-8"), "worker")
    assert "app.worker" in block, "worker service not found"
    probe_cmd = _healthcheck_test(block)
    assert (
        probe_cmd is not None
    ), f"{compose}: worker has no explicit healthcheck (would inherit image probe)"
    assert "app.probe" in probe_cmd and "worker" in probe_cmd
    assert "healthz" not in probe_cmd and "http" not in probe_cmd.lower()


def test_production_image_healthcheck_is_role_aware():
    dockerfile = (API_DIR / "Dockerfile").read_text(encoding="utf-8")
    prod = dockerfile.split("AS production", 1)[1].split("\nFROM ", 1)[0]
    hc = prod.split("HEALTHCHECK", 1)[1]
    assert "app.probe" in hc
    assert "urlopen" not in hc
