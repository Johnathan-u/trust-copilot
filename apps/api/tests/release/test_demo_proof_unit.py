"""Pure checks for demonstration proof summaries.

This module does not open a database connection or an application client.
Keep it that way so collection can mark it as a unit test.
"""

import ast
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = Path(__file__).resolve().parents[2]
PRESENTER = REPO_ROOT / "apps" / "web" / "lib" / "demoProofSummary.mjs"
PAGE = REPO_ROOT / "apps" / "web" / "app" / "dashboard" / "demo-proof" / "page.tsx"
MIGRATION = API_ROOT / "alembic" / "versions" / "tc25011_demo_proof_summaries.py"


def _present(payload: dict) -> dict:
    script = (
        "import { presentDemoProof } from './apps/web/lib/demoProofSummary.mjs';"
        "import { readFileSync } from 'node:fs';"
        "const payload = JSON.parse(readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(presentDemoProof(payload)));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _imported_modules(source: str) -> list[str]:
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_ui_page_uses_the_presenter():
    source = PAGE.read_text()
    presenter = PRESENTER.read_text()
    assert "presentDemoProof" in source
    assert "requestSummary('GET')" in source
    assert source.count("requestSummary('POST')") == 1
    assert "void load()" in source
    assert "permissions.can_edit" in source
    assert "canEdit &&" in source
    assert "Not commercial traction" in source
    assert "Synthetic placeholder" in source
    assert "No data" in source
    assert "row.displayValue" in source
    assert "row.origin" in source
    assert "row.basis" in source
    assert "row.tractionLabel" in source
    assert "commercial_traction === false" in presenter
    assert "TC-" not in source
    assert "TC-" not in presenter
    assert PRESENTER.is_file()


def test_presenter_rejects_commercial_traction():
    leaked = {
        "schema_version": "1",
        "commercial_traction": True,
        "status": "complete",
        "metrics": [
            {"name": "customers", "value": 12, "commercial_traction": True, "state": "measured"}
        ],
        "synthetic_placeholders": [],
        "unsupported": [],
        "partial_failures": [],
    }
    rejected = _present(leaked)
    assert rejected["state"] == "rejected"
    assert rejected["rows"] == []


def test_migration_module_has_no_app_imports():
    source = MIGRATION.read_text()
    modules = _imported_modules(source)
    assert modules
    assert all(name.split(".")[0] != "app" for name in modules)
    assert 'revision = "tc25011_demo_proof_summaries"' in source
    assert 'down_revision = "tc10003_job_idempotency"' in source
    assert "NOT IN" not in source.upper()
    assert source.count("op.drop_table") == 1
    assert 'op.drop_table("demo_proof_summaries")' in source
    assert "op.rename_table" not in source
    assert "op.bulk_insert" not in source
    assert "op.execute" not in source
    assert "UPDATE " not in source.upper()
    assert "DELETE FROM" not in source.upper()
