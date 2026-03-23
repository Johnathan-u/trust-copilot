"""Unit tests for compliance_gaps scan-and-notify cooldown behaviour (bug fix)."""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.api.routes import compliance_gaps as gaps_mod


@pytest.fixture(autouse=True)
def _reset_cooldown():
    """Clear the in-memory cooldown dict between tests."""
    gaps_mod._last_gap_notify.clear()
    yield
    gaps_mod._last_gap_notify.clear()


def _fake_session(ws: int = 1) -> dict:
    return {"workspace_id": ws, "user_id": 99, "role": "admin"}


def _fake_gaps(*_args, **_kwargs):
    """Simulate two gaps."""
    return [
        {"control_id": 1, "gap_reason": "no_evidence"},
        {"control_id": 2, "gap_reason": "low_confidence"},
    ]


def _fake_no_gaps(*_args, **_kwargs):
    return []


class TestScanAndNotifyCooldown:
    """Verify that during cooldown, the real gap count is still returned."""

    def test_first_call_notifies(self):
        db = MagicMock()
        session = _fake_session()

        with patch.object(gaps_mod, "global_gaps_list", side_effect=_fake_gaps), \
             patch.object(gaps_mod, "notify_admins"):
            result = gaps_mod.scan_and_notify_gaps(
                low_confidence_threshold=0.5, session=session, db=db,
            )
        assert result["notified"] is True
        assert result["gaps"] == 2

    def test_cooldown_returns_real_gap_count(self):
        """Previously returned 0 during cooldown due to __wrapped__ bug."""
        db = MagicMock()
        session = _fake_session()

        gaps_mod._last_gap_notify[1] = time.monotonic()

        with patch.object(gaps_mod, "global_gaps_list", side_effect=_fake_gaps):
            result = gaps_mod.scan_and_notify_gaps(
                low_confidence_threshold=0.5, session=session, db=db,
            )
        assert result["reason"] == "cooldown"
        assert result["notified"] is False
        assert result["gaps"] == 2, "Bug: cooldown path must return actual gap count, not 0"

    def test_cooldown_zero_gaps(self):
        db = MagicMock()
        session = _fake_session()

        gaps_mod._last_gap_notify[1] = time.monotonic()

        with patch.object(gaps_mod, "global_gaps_list", side_effect=_fake_no_gaps):
            result = gaps_mod.scan_and_notify_gaps(
                low_confidence_threshold=0.5, session=session, db=db,
            )
        assert result["gaps"] == 0
        assert result["reason"] == "cooldown"

    def test_no_workspace_returns_zero(self):
        db = MagicMock()
        result = gaps_mod.scan_and_notify_gaps(
            low_confidence_threshold=0.5, session={}, db=db,
        )
        assert result == {"gaps": 0, "notified": False}
