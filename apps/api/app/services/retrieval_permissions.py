"""Caller permission policy for retrieval.

The flags are the existing built-in map and, for any other role name, the
custom-role lookup routes already use. This module does not add a role.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.roles import get_builtin_permissions

_NAMES = ("can_edit", "can_review", "can_export", "can_admin")


@dataclass(frozen=True)
class RetrievalPermissionPolicy:
    """Permissions that decide which documents in a workspace a caller may read."""

    can_edit: bool = False
    can_review: bool = False
    can_export: bool = False
    can_admin: bool = False
    document_ids: frozenset[int] | None = None

    def fingerprint(self) -> str:
        """Stable cache-key fragment. Different policies do not share a row."""
        flags = "".join("1" if getattr(self, name) else "0" for name in _NAMES)
        if self.document_ids is None:
            scope = "*"
        else:
            scope = ",".join(str(item) for item in sorted(self.document_ids))
        return f"{flags}:{scope}"


def policy_for_role(
    role: str | None,
    *,
    db: Session | None = None,
    workspace_id: int | None = None,
    document_ids: frozenset[int] | None = None,
) -> RetrievalPermissionPolicy:
    """Resolve ``role`` with the existing helpers.

    A built-in role uses ``get_builtin_permissions``. Any other name is a
    custom role in ``workspace_id`` when a session is provided. An unknown
    role cannot read documents. ``document_ids``, when set, is the only set
    this caller may read inside the workspace.
    """
    perms = get_builtin_permissions(role)
    if perms is None and role and db is not None and workspace_id is not None:
        from app.core.auth_deps import _resolve_permission

        perms = {name: bool(_resolve_permission(role, name, workspace_id, db)) for name in _NAMES}
    if perms is None:
        perms = {name: False for name in _NAMES}
    granted = None
    if document_ids is not None:
        granted = frozenset(int(item) for item in document_ids)
    return RetrievalPermissionPolicy(
        can_edit=bool(perms.get("can_edit")),
        can_review=bool(perms.get("can_review")),
        can_export=bool(perms.get("can_export")),
        can_admin=bool(perms.get("can_admin")),
        document_ids=granted,
    )
