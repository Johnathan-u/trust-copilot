# Scripts

- **Operational:** `backup_db.sh`, `run-migrations.ps1` — see [docs/ops/BACKUP_RESTORE.md](../docs/ops/BACKUP_RESTORE.md) and [docs/ops/DATABASE_MIGRATIONS.md](../docs/ops/DATABASE_MIGRATIONS.md).
- **Demo-only (do not run in production):** `seed-demo.ps1` — seeds a demo workspace and demo user (e.g. demo@trust.local). Use for local demos only; see [docs/DEMO_SCRIPT.md](../docs/DEMO_SCRIPT.md).
- **Dev/local:** `start.ps1`, `start-docker-db.ps1`, `run-api-tests.ps1`, `check-port-*.js`, etc. — local development helpers.

**API scripts** (under `apps/api/scripts/`): `purge_audit_retention.py` (ops), `seed_demo_workspace.py` and `generate_mock_docs.py` (demo-only), `seed_qa_test_data.py` (QA test sheet — run via `.\scripts\seed-qa.ps1` or `python scripts/seed_qa_test_data.py` from `apps/api`; see [docs/QA_TEST_SHEET.md](../docs/QA_TEST_SHEET.md)).
