"""Append one NDJSON line for debug sessions (Cursor). Do not log secrets or PII."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def append_session_debug(payload: dict[str, Any]) -> None:
    # #region agent log
    if os.environ.get("TRUST_COPILOT_TESTING") == "1":
        return
    raw_path = os.environ.get("TRUST_COPILOT_DEBUG_NDJSON", "").strip()
    paths: list[Path] = []
    if raw_path:
        paths.append(Path(raw_path))
    else:
        # trust-copilot/apps/api/app/core/debug_session_log.py -> parents[4] = repo root
        _here = Path(__file__).resolve()
        if len(_here.parents) >= 5:
            tc_root = _here.parents[4]
            paths.append(tc_root.parent / "debug-d109ae.log")
            paths.append(tc_root / "debug-d109ae.log")
    out = {
        **payload,
        "sessionId": "d109ae",
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(out, default=str) + "\n"
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
            return
        except OSError:
            continue
    # #endregion
