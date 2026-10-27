"""Container healthcheck entrypoint (TC-03-003): ``python -m app.probe``.

Role-aware so the worker never inherits the API's HTTP probe:

* ``TC_PROCESS_ROLE=api`` (default): GET http://127.0.0.1:${PORT:-8000}/healthz (liveness only,
  no dependency checks — dependency loss is reported by /readyz instead).
* ``TC_PROCESS_ROLE=worker``: no HTTP; healthy iff the worker heartbeat file was touched within
  ``WORKER_HEARTBEAT_STALE_SEC``. The file is only touched while the claim loop is progressing or a job
  is within ``WORKER_JOB_MAX_RUNTIME_SEC``.

Exit status 0 = healthy, 1 = unhealthy. Standard library only.
"""

from __future__ import annotations

import os
import sys
import urllib.request

from app.worker_health import heartbeat_file, heartbeat_file_age_sec, heartbeat_stale_sec


def check_api(timeout: float = 4.0) -> tuple[bool, str]:
    port = os.environ.get("PORT", "8000")
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return (200 <= r.status < 300), f"healthz {r.status}"
    except Exception as e:  # noqa: BLE001
        return False, f"healthz unreachable ({type(e).__name__})"


def check_worker() -> tuple[bool, str]:
    stale = heartbeat_stale_sec()
    age = heartbeat_file_age_sec()
    if age is None:
        return False, f"no heartbeat file at {heartbeat_file()}"
    if age > stale:
        return False, f"heartbeat stale {int(age)}s > {stale}s"
    return True, f"heartbeat age {int(age)}s"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    role = (args[0] if args else os.environ.get("TC_PROCESS_ROLE", "api")).strip().lower()
    if role == "worker":
        ok, detail = check_worker()
    elif role == "api":
        ok, detail = check_api()
    else:
        ok, detail = False, f"unknown TC_PROCESS_ROLE {role!r}"
    print(f"probe role={role} {'healthy' if ok else 'unhealthy'}: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
