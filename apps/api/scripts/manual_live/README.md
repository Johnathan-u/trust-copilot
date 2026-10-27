# Manual live-stack scripts (not pytest)

Moved out of `apps/api/tests/` by TC-02-001 so that importing or collecting the test
suite can never open a network connection or use a checked-in credential.

* They are **not** collected by pytest (`testpaths = ["tests"]`).
* They only run against a **local** stack (`TC_API`, default `http://localhost:8000`;
  loopback or compose service names only — see `_live_guard.py`). There is no override.
* Scripts that forge a session cookie require `TC_SESSION_SECRET` (your local stack's
  `SESSION_SECRET`) in the environment and use a synthetic `*@trust.local` identity.
* Blind-pack scripts read their dataset from `TC_TRUST_SCORING_BLIND_PACK`.

| Script | Former path | Needs |
|---|---|---|
| `probe_alerts_api.py` | `tests/test_alerts_api.py` | running API, `TC_SESSION_SECRET` |
| `probe_coverage_api.py` | `tests/test_coverage_api.py` | running API, `TC_SESSION_SECRET` |
| `fetch_ds5.py`, `fetch_full_qa.py` | `tests/fetch_ds5.py`, `tests/fetch_full_qa.py` | running API, `TC_SESSION_SECRET` |
| `run_3dataset_check.py`, `run_10dataset_check.py` | `tests/run_3dataset_test.py`, `tests/run_10dataset_test.py` | running API + worker, `TC_SESSION_SECRET` |
| `e2e_pipeline_check.py` | `tests/e2e_pipeline_test.py` | running API + worker (demo login) |
| `full_ui_backend_check.py` | `tests/full_ui_backend_test.py` | running API + Caddy (demo login) |
| `pipeline_data_audit.py`, `pipeline_deep_audit.py` | `tests/pipeline_data_audit.py`, `tests/pipeline_deep_audit.py` | running API (demo login) |
| `verify_mapping_counter.py` | `tests/verify_mapping_counter.py` | local DB (in-process TestClient) |
| `inspect_blind.py`, `run_blind_full.py` | `tests/_inspect_blind.py`, `tests/_run_blind_full.py` | `TC_TRUST_SCORING_BLIND_PACK` |

Run from `apps/api`, e.g. `TC_SESSION_SECRET=... python scripts/manual_live/probe_coverage_api.py`.
