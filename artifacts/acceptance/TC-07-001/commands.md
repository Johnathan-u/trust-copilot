# Commands (run from repo root unless noted)
| # | Command | cwd | Exit | Totals |
|---|---|---|---|---|
| 1 | `python -m pytest tests/release/test_secret_inventory.py -q -p no:cacheprovider` | apps/api | 0 | 66 passed in 2.82s |
| 2 | `python -m pytest -q -p no:cacheprovider tests/test_security_remediation.py tests/test_csrf_origins.py tests/test_login_email_regression.py tests/test_auth.py tests/test_auth_flows.py tests/test_auth_sessions_api.py tests/test_auth_workspace.py tests/test_phase_d_slack.py tests/test_phase_e_slack_ingest.py tests/test_credential_store.py --deselect tests/test_credential_store.py::TestCredentialStoreService` | apps/api | 0 | 41 passed, 89 skipped, 7 deselected in 2.28s |
| 3 | `python scripts/security/secret_inventory.py tree --root . --json artifacts/acceptance/TC-07-001/scan_tree.json` | repo | 0 | {"block": 0, "by_source_severity": {"tree:review": 26}, "total": 26} |
| 4 | `python scripts/security/secret_inventory.py history --root . --fail-on never --json artifacts/acceptance/TC-07-001/scan_history.json` | repo | 0 | {"block": 142, "by_source_severity": {"history:block": 142, "history:review": 98}, "total": 240} |
