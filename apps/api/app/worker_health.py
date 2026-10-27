"""Worker liveness/heartbeat (TC-03-003).

The worker is not an HTTP server, so it must never be probed over HTTP. Instead:

* ``HeartbeatState`` tracks loop progress and the currently running job.
* ``HeartbeatThread`` runs beside the claim loop and, every
  ``WORKER_HEARTBEAT_INTERVAL_SEC``, refreshes the DB heartbeat row (read by ``/workerz``)
  and touches a local heartbeat file (read by the container healthcheck, ``python -m app.probe``).
  It keeps beating while a job runs, so long-running healthy jobs do not look like a dead worker,
  but it stops once the loop stalls (idle loop not ticking) or a single job exceeds
  ``WORKER_JOB_MAX_RUNTIME_SEC`` — so a wedged worker still goes stale.

This module only depends on the standard library so the probe stays cheap.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger("trustcopilot.worker.heartbeat")

DEFAULT_HEARTBEAT_INTERVAL_SEC = 15
DEFAULT_HEARTBEAT_STALE_SEC = 120
DEFAULT_JOB_MAX_RUNTIME_SEC = 3600
DEFAULT_LOOP_STALL_SEC = 120
DEFAULT_HEARTBEAT_FILE = "/tmp/trustcopilot-worker.heartbeat"


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def heartbeat_interval_sec() -> int:
    return _int_env("WORKER_HEARTBEAT_INTERVAL_SEC", DEFAULT_HEARTBEAT_INTERVAL_SEC)


def heartbeat_stale_sec() -> int:
    return _int_env("WORKER_HEARTBEAT_STALE_SEC", DEFAULT_HEARTBEAT_STALE_SEC)


def job_max_runtime_sec() -> int:
    return _int_env("WORKER_JOB_MAX_RUNTIME_SEC", DEFAULT_JOB_MAX_RUNTIME_SEC)


def loop_stall_sec() -> int:
    return _int_env("WORKER_LOOP_STALL_SEC", DEFAULT_LOOP_STALL_SEC)


def heartbeat_file() -> Path:
    return Path(os.environ.get("WORKER_HEARTBEAT_FILE") or DEFAULT_HEARTBEAT_FILE)


class HeartbeatState:
    """Thread-safe record of worker progress. Clock is injectable for tests."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._last_tick = clock()
        self._job_id: int | None = None
        self._job_started: float | None = None

    def loop_tick(self) -> None:
        with self._lock:
            self._last_tick = self._clock()

    def job_started(self, job_id: int | None) -> None:
        with self._lock:
            self._job_id = job_id
            self._job_started = self._clock()
            self._last_tick = self._job_started

    def job_finished(self) -> None:
        with self._lock:
            self._job_id = None
            self._job_started = None
            self._last_tick = self._clock()

    def assess(self, *, max_job_sec: int, stall_sec: int) -> tuple[bool, str]:
        """Return (healthy, reason)."""
        with self._lock:
            now = self._clock()
            if self._job_started is not None:
                running = now - self._job_started
                if running > max_job_sec:
                    return False, f"job {self._job_id} running {int(running)}s > {max_job_sec}s"
                return True, f"job {self._job_id} running {int(running)}s"
            idle = now - self._last_tick
            if idle > stall_sec:
                return False, f"claim loop stalled {int(idle)}s > {stall_sec}s"
            return True, "idle"


def touch_heartbeat_file(path: Path | None = None) -> None:
    p = path or heartbeat_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(int(time.time())), encoding="ascii")


def heartbeat_file_age_sec(path: Path | None = None, now: float | None = None) -> float | None:
    p = path or heartbeat_file()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    return max(0.0, (now if now is not None else time.time()) - mtime)


class HeartbeatThread(threading.Thread):
    """Daemon thread that beats while ``state`` is healthy.

    ``write_db`` refreshes the shared DB heartbeat; failures are logged (redacted) and do not
    stop the local file heartbeat — DB loss is a readiness problem, not a worker-process liveness one.
    """

    def __init__(
        self,
        state: HeartbeatState,
        write_db: Callable[[], None],
        *,
        interval_sec: float | None = None,
        max_job_sec: int | None = None,
        stall_sec: int | None = None,
        file_path: Path | None = None,
    ):
        super().__init__(name="worker-heartbeat", daemon=True)
        self.state = state
        self.write_db = write_db
        self.interval_sec = interval_sec if interval_sec is not None else heartbeat_interval_sec()
        self.max_job_sec = max_job_sec if max_job_sec is not None else job_max_runtime_sec()
        self.stall_sec = stall_sec if stall_sec is not None else loop_stall_sec()
        self.file_path = file_path
        self._stop_event = threading.Event()
        self.beats = 0
        self.skipped = 0
        self.db_failures = 0

    def beat_once(self) -> bool:
        healthy, reason = self.state.assess(max_job_sec=self.max_job_sec, stall_sec=self.stall_sec)
        if not healthy:
            self.skipped += 1
            logger.warning("ALERT_WORKER_UNHEALTHY heartbeat withheld: %s", reason)
            return False
        try:
            touch_heartbeat_file(self.file_path)
        except OSError as e:
            logger.warning("worker heartbeat file write failed: %s", type(e).__name__)
        try:
            self.write_db()
        except Exception as e:  # noqa: BLE001 - never let the heartbeat thread die
            self.db_failures += 1
            logger.warning("worker heartbeat DB write failed: %s", type(e).__name__)
        self.beats += 1
        return True

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.beat_once()
            self._stop_event.wait(self.interval_sec)

    def stop(self) -> None:
        self._stop_event.set()
