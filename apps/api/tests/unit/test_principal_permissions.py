"""Built-in role permissions. These are the pure half of the principal contract."""

from __future__ import annotations

import pytest

from app.core.roles import (
    can_admin,
    can_edit,
    can_review,
    get_builtin_permissions,
    is_builtin_role,
)

pytestmark = pytest.mark.unit


def test_admin_editor_and_reviewer_permissions_stay_distinct():
    assert can_admin("admin") is True
    assert can_admin("editor") is False
    assert can_edit("editor") is True
    assert can_edit("reviewer") is False
    assert can_review("reviewer") is True
    assert can_review("stranger") is False


def test_unknown_and_missing_roles_are_not_built_in():
    assert is_builtin_role("admin") is True
    assert is_builtin_role(None) is False
    assert is_builtin_role("owner") is False
    assert get_builtin_permissions(None) is None
    assert get_builtin_permissions("owner") is None
    assert get_builtin_permissions("reviewer") == {
        "can_edit": False,
        "can_review": True,
        "can_export": False,
        "can_admin": False,
    }
