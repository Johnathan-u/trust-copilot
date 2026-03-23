"""Role guards and permission helpers (AUTH-05, Phase B custom roles)."""

from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    REVIEWER = "reviewer"


BUILTIN_ROLES = {Role.ADMIN.value, Role.EDITOR.value, Role.REVIEWER.value}

BUILTIN_PERMISSIONS = {
    "admin":    {"can_edit": True, "can_review": True, "can_export": True, "can_admin": True},
    "editor":   {"can_edit": True, "can_review": True, "can_export": True, "can_admin": False},
    "reviewer": {"can_edit": False, "can_review": True, "can_export": False, "can_admin": False},
}


def is_builtin_role(role: str | None) -> bool:
    return role in BUILTIN_ROLES


def get_builtin_permissions(role: str | None) -> dict | None:
    """Return permission dict for a built-in role, or None if not built-in."""
    return BUILTIN_PERMISSIONS.get(role)


def can_edit(role: str | None) -> bool:
    return role in (Role.ADMIN.value, Role.EDITOR.value)


def can_review(role: str | None) -> bool:
    return role in (Role.ADMIN.value, Role.EDITOR.value, Role.REVIEWER.value)


def can_admin(role: str | None) -> bool:
    return role == Role.ADMIN.value


def can_export(role: str | None) -> bool:
    return role in (Role.ADMIN.value, Role.EDITOR.value)
