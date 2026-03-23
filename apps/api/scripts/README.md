# API scripts

- **Operational:**
  - `purge_audit_retention.py` — purge audit events older than `AUDIT_RETENTION_DAYS`. Run on a schedule (e.g. cron). See [docs/security/AUDIT_LOGGING.md](../../docs/security/AUDIT_LOGGING.md).
  - `detect_stuck_jobs.py` — detect (and optionally recover) jobs stuck in RUNNING status. Run periodically or on-demand. See [docs/STUCK_JOB_RECOVERY.md](../../docs/STUCK_JOB_RECOVERY.md).
  - `queue_index_uploaded_docs.py` — queue indexing jobs for uploaded documents that haven't been indexed yet.
- **Demo-only (do not run in production):**
  - `seed_demo_workspace.py` — seeds demo user (demo@trust.local), workspace, questionnaire, and sample data. For local/demo use only. Invoked via repo `scripts/seed-demo.ps1`.
  - `generate_mock_docs.py` — generates mock documents for demo uploads. For local/demo use only.
- **Test/QA helpers:**
  - `seed_e2e_registry.py` — seeds end-to-end registry test data.
  - `seed_qa_test_data.py` — seeds QA test data.
  - `ensure_ai_test_data.py` — ensures AI test data exists.
  - `benchmark_phase4_validation.py` — benchmark for phase 4 validation.
- **Fixture generation:** `generate-fixtures.py` — test fixture generation; dev/test only.
