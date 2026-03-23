"""Active workspace resolution (AUTH-04)."""

from functools import lru_cache


@lru_cache(maxsize=1)
def _default_workspace() -> int:
    return 1


def get_active_workspace_id(session: dict | None) -> int | None:
    """Resolve workspace from session payload."""
    if not session:
        return None
    return session.get("workspace_id") or _default_workspace()
