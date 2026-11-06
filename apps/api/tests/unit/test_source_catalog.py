"""Known evidence-source catalog. No database session is opened."""

from __future__ import annotations

import pytest

from app.services.source_registry_service import KNOWN_SOURCES

pytestmark = pytest.mark.unit

_REQUIRED = {
    "source_type",
    "display_name",
    "auth_method",
    "sync_cadence",
    "object_types",
    "failure_modes",
}


def test_source_types_are_unique_and_complete():
    types = [row["source_type"] for row in KNOWN_SOURCES]
    assert len(types) == len(set(types))
    assert len(types) >= 8
    for row in KNOWN_SOURCES:
        assert _REQUIRED <= set(row)
        assert row["source_type"]
        assert row["display_name"]


def test_manual_and_azure_auth_methods_stay_pinned():
    by_type = {row["source_type"]: row for row in KNOWN_SOURCES}
    assert by_type["manual"]["auth_method"] == "none"
    assert by_type["azure"]["auth_method"] == "service_principal"
    assert "token_expired" in by_type["github"]["failure_modes"]
