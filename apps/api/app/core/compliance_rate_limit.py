"""Phase 6: Basic rate limiting for compliance audit/webhook writes (per workspace)."""

import threading
import time

# Max compliance writes (evidence verify, control verify, mapping confirm/override) per workspace per window
COMPLIANCE_WRITE_LIMIT = 60
COMPLIANCE_WRITE_WINDOW_SEC = 60

_lock = threading.Lock()
_workspace_timestamps: dict[int, list[float]] = {}


def _prune(ts_list: list[float], window_sec: float, now: float) -> None:
    cutoff = now - window_sec
    while ts_list and ts_list[0] < cutoff:
        ts_list.pop(0)


def check_compliance_write_allowed(workspace_id: int) -> bool:
    """
    Return True if the workspace is under the compliance write rate limit; otherwise False.
    Call before persist_audit/emit in compliance write endpoints.
    """
    if workspace_id is None:
        return True
    now = time.time()
    with _lock:
        if workspace_id not in _workspace_timestamps:
            _workspace_timestamps[workspace_id] = []
        lst = _workspace_timestamps[workspace_id]
        _prune(lst, COMPLIANCE_WRITE_WINDOW_SEC, now)
        if len(lst) >= COMPLIANCE_WRITE_LIMIT:
            return False
        lst.append(now)
        return True
