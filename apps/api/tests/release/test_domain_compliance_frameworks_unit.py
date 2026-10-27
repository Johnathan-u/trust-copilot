"""Pure TC-21-001 checks. No database, so this module stays a unit test."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.services.framework_catalog_registry import ADVERTISED_CATALOGS

pytestmark = pytest.mark.unit

API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILE = API_ROOT / "alembic" / "versions" / "tc21001_framework_catalog_rights.py"
WEB_CONSUMER = API_ROOT.parent / "web" / "lib" / "frameworkCatalog.ts"


def test_advertised_alias_sets_are_disjoint():
    seen: dict[str, str] = {}
    for spec in ADVERTISED_CATALOGS:
        for norm in spec.match_norms():
            assert seen.get(norm) in (None, spec.catalog_key)
            seen[norm] = spec.catalog_key
    assert [spec.catalog_key for spec in ADVERTISED_CATALOGS] == [
        "SOC2",
        "HIPAA",
        "ISO27001",
        "NIST_CSF_2",
        "NIST_800_53_R5",
        "NIST_800_171_R3",
        "SIG",
        "CAIQ",
        "HITRUST",
    ]


def test_migration_module_does_not_import_app():
    """The revision is a frozen snapshot. Importing it must not load the application package."""
    source = MIGRATION_FILE.read_text(encoding="utf-8")
    assert "NOT EXISTS" in source
    assert "NOT IN" not in source
    assert "SET name" not in source
    assert 'ondelete="SET NULL"' in source
    script = r"""
import ast
import importlib.util
import sys

path = sys.argv[1]
tree = ast.parse(open(path, encoding="utf-8").read())
modules = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        modules.extend(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        modules.append(node.module)
banned = [name for name in modules if name == "app" or name.startswith("app.")]
if banned:
    raise SystemExit("migration imports app: " + ", ".join(banned))
spec = importlib.util.spec_from_file_location("tc21001_migration_under_test", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if module.revision != "tc21001_framework_catalog_rights":
    raise SystemExit("unexpected revision id: " + repr(module.revision))
if module.down_revision != "075":
    raise SystemExit("unexpected down_revision: " + repr(module.down_revision))
loaded = [name for name in sys.modules if name == "app" or name.startswith("app.")]
if loaded:
    raise SystemExit("importing the migration loaded app: " + ", ".join(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(MIGRATION_FILE)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_catalog_event_primary_key_is_not_indexed_twice():
    """index=True on the id would autogenerate ix_framework_catalog_events_id."""
    from app.models.framework_catalog_event import FrameworkCatalogEvent

    table = FrameworkCatalogEvent.__table__
    id_column = table.c.id
    assert id_column.primary_key
    assert id_column.index is not True
    extra = [
        index.name for index in table.indexes if [column.name for column in index.columns] == ["id"]
    ]
    assert extra == []


def test_ui_consumer_source_matches_blocked_contract():
    source = WEB_CONSUMER.read_text(encoding="utf-8")
    for needle in (
        "blocked_pending_rights",
        "dev_test_only",
        "production_catalog",
        "isProductionCatalogEnabled",
        "framework-catalog-error/v1",
        "Pending content licensing",
        "enableRequestBody",
        "content_version",
        "enablement_state",
        "rights_status",
    ):
        assert needle in source
    assert "enablementSucceeded" not in source
    page = (
        WEB_CONSUMER.parents[1] / "app" / "dashboard" / "compliance-frameworks" / "page.tsx"
    ).read_text(encoding="utf-8")
    assert "/api/compliance/frameworks" in page
    assert "parseEnableError" in page
    assert "isProductionCatalogEnabled" in page
    assert "Dev / test catalogs cannot be enabled." in page
    assert "TC-01-007" not in page
    assert "catalog_key: item.catalog_key" not in page
    assert "enableRequestBody" in page
    assert "catalogRightsLabel" in page
    assert "item.rights_status" not in page
    assert "hasLegacyListFields" not in source
