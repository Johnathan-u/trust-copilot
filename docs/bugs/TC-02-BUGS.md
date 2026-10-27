# TC-02 bugs list (from the ruff `--add-noqa` findings)

Source: `ci-mechanical` added `# noqa` to every pre-existing ruff finding so CI could go green without
behavior changes (431 non-E402/F401 findings at the time; the full list is in the PR #17 evidence,
`ci-mechanical-noqa-findings.tsv`). This file triages the ones that can hide a runtime bug:
every F821 (undefined name) and F811 (redefinition), plus the F841 (assigned but never used)
entries whose dead variable hides missing logic or a missing assertion. Every claim was checked by
reading the code at `3ee20da` (line numbers are valid there); where possible it was reproduced.
**Nothing here is fixed in this branch.** Synthetic data only.

Severity scale: **High** = request-path failure or data exposure; **Medium** = wrong behavior or
vacuous security/regression test; **Low** = test-only failure in an edge case or misleading
metric; **None** = lint-only, verified not to fail at runtime (kept because the triage asked for every
F821/F811).

Epic owners from `trustcopilot-package/epics`: E02–E07 and E27 = Platform & Security (this
agent); E08–E13 = Core; E17–E19, E23 = their full-stack and integration owners.

## Summary

| ID | file:line | Rule / name | Runtime effect | Path | Epic | Severity |
|---|---|---|---|---|---|---|
| TC-02-BUG-001 | `apps/api/app/api/routes/questionnaires.py:711` | F821 `Any` | **None.** Local-variable annotation, never evaluated | request: `POST /api/questionnaires/{qnr_id}/generate-mappings` | E09 | None (lint) |
| TC-02-BUG-002 | `apps/api/tests/test_questionnaire_parser.py:81` | F821 `pytest` | `NameError: name 'pytest' is not defined` when the fixture is missing | test-only | E09 | Low |
| TC-02-BUG-003 | `apps/api/tests/test_questionnaire_parser.py:91` | F821 `pytest` | Same as 002 | test-only | E09 | Low |
| TC-02-BUG-004 | `apps/api/tests/test_answer_pipeline.py:63` | F811 `text` | **None.** Parameter shadows an unused import inside `Q.__init__` | test-only | E11 | None (lint) |
| TC-02-BUG-005 | `apps/api/app/services/answer_generation.py:1223` | F841 `direct_ev_missing` | Documented rule (direct-evidence subjects) never applied in the draft sweep | worker job (answer generation), not a request | E11 | Medium |
| TC-02-BUG-006 | `apps/api/app/services/sli_service.py:25` | F841 `window_30d` | 30-day availability SLI is never computed; it always reports `100.0` / `met` | request: `GET /api/sli` | E27 | Medium |
| TC-02-BUG-007 | `apps/api/tests/test_phase_c_notifications.py:404` | F841 `entries` | Workspace-scoping test of the delivery log asserts nothing about scoping | test-only (covers `GET /api/notifications/log`) | E19 (E06 interest) | Medium |
| TC-02-BUG-008 | `apps/api/tests/test_answer_pipeline.py:157` | F841 `count` | Return value is unchecked and the assertions sit under `if job.result:`, so the test can pass vacuously | test-only | E11 | Low |
| TC-02-BUG-009 | `apps/api/tests/run_10dataset_test.py:665` | F841 `max_i` | The "max insufficient" expectation is never checked | manual script (not collected by pytest) | E11 | Low |

Related findings from the fixture investigation (not noqa entries; same branch, listed for the owner):

| ID | file:line | Kind | Runtime effect | Path | Epic | Severity |
|---|---|---|---|---|---|---|
| TC-02-BUG-010 | `apps/api/app/api/routes/vendor_requests.py:73-82` | missing validation | A nonexistent `questionnaire_id` gives an unhandled `sqlalchemy.exc.IntegrityError` (FK violation), so HTTP 500 | request: `POST /api/vendor-requests/` | E18 | Medium |
| TC-02-BUG-011 | `apps/api/app/api/routes/vendor_requests.py:73-82` + `vendor_response.py:29-40` | missing tenant check | `questionnaire_id` is not checked against the caller's workspace. The public link then shows another tenant's questionnaire filename and question count | request: `POST /api/vendor-requests/`, then public `GET /api/vendor-response?token=` | E06 | High |

Status since the triage: TC-02-BUG-010 and TC-02-BUG-011 are fixed in #26 (merged, 36712a5).

Platform & Security (E06) follow-ups. There is no separate E06 bug list, so they are listed here,
title only:

| ID | Title | Epic | Status |
|---|---|---|---|
| TC-06-BUG-012 | Deals: scope deal and linked-questionnaire lookups to the caller's workspace | E06 | Fixed in TC-06-BUG-012 PR (pending merge) |
| TC-06-BUG-013 | Shared same-workspace validation for ids referenced in request bodies | E06 | Tracked |

## Details

### TC-02-BUG-001: `questionnaires.py:711` F821 `Any` (request path, not a runtime bug)
- Code: `signal_by_qid: dict[int, Any] = {}` inside `generate_questionnaire_mappings`
  (`POST /api/questionnaires/{qnr_id}/generate-mappings`). `Any` is never imported.
- Runtime: Python does not evaluate annotations on local variables (PEP 526), so no `NameError`.
  The route is exercised by `tests/test_questionnaire_mappings.py`, which passes.
- Repro: `python -c "def f():\n    x: dict[int, Any] = {}\n    return x\nprint(f())"` prints `{}`.
- Risk: it becomes a real bug if the line moves to module or class scope, or if the annotation is
  evaluated (for example by `typing.get_type_hints` on a nested class). The fix is a one-line
  `from typing import Any`.

### TC-02-BUG-002 / 003: `test_questionnaire_parser.py:81` and `:91` F821 `pytest` (test-only)
- `test_parse_iso27001_xlsx` and `test_parse_vendor_dd_xlsx` call `pytest.skip(...)` when
  `tests/fixtures/questionnaires/{iso27001,vendor_dd}.xlsx` is missing, but the module never
  imports `pytest`.
- Runtime: the fixtures are committed today, so the line is not reached. Without them the test
  errors with `NameError: name 'pytest' is not defined` instead of skipping.
- Repro (verified): import the module, point `FIXTURES` at an empty temp dir, and call either test.
  Result: `NameError name 'pytest' is not defined`.

### TC-02-BUG-004: `test_answer_pipeline.py:63` F811 `text` (not a runtime bug)
- `class Q: def __init__(self, text)` shadows `from sqlalchemy import text` (line 7, itself unused,
  `# noqa: F401`). The shadowing is local to `__init__`, and the test passes. Lint-only. The fix is to
  drop the unused import.

### TC-02-BUG-005: `answer_generation.py:1223` F841 `direct_ev_missing` (worker path)
- `_sweep_draft_insufficient_narratives` documents that it reclassifies drafts "whose primary
  subject requires direct evidence that wasn't provided". It computes `direct_ev_missing` but never
  uses it: the reclassification condition is only `is_insufficient_answer_text(a.text) or no_citations`.
- Trigger: the answer-generation job (`app/worker.py:276` → `generate_answers_for_questionnaire`
  → sweep at lines 779/1117). This is not a request path.
- Effect: drafts in direct-evidence subjects that cite only indirect evidence stay `draft` instead of
  `insufficient_evidence`. Generation time (lines 873–885) only partly covers this, because it checks
  evidence presence, not directness.
- Note: the variable as written is `True` whenever the subject needs direct evidence, whatever the
  citations. Using it directly would over-flag, so the intended rule needs product input (E11).

### TC-02-BUG-006: `sli_service.py:25` F841 `window_30d` (request path, mine)
- `GET /api/sli` (admin) → `get_slis`. `window_30d` is computed and unused, and
  `api_availability` is hard-coded to `current: 100.0, status: "met"` against a 99.9 % / 30d target.
- Effect: the reliability page always reports availability as met, which is a misleading operational
  signal for E27 (capacity and SLOs). Also, the job counts are not filtered by `workspace_id`, so any
  workspace admin sees platform-wide job totals (cross-tenant aggregate).
- Repro: create failed jobs, then `GET /api/sli`. `api_availability.current` is still `100.0`.

### TC-02-BUG-007: `test_phase_c_notifications.py:404` F841 `entries`
- `test_delivery_log_scoped_to_workspace` reads `entries` and then asserts only `status_code == 200`.
  The comment admits there is no scoping check. A workspace-leak regression in
  `GET /api/notifications/log` would pass. This is a vacuous security test, to be fixed alongside
  E06 tenant-authorization tests.

### TC-02-BUG-008: `test_answer_pipeline.py:157` F841 `count`
- `generate_answers_for_questionnaire(...)` return value is discarded, and every assertion is
  inside `if job.result:`. If the job writes no result, the test asserts nothing.

### TC-02-BUG-009: `run_10dataset_test.py:665` F841 `max_i`
- The manual validation script reads `expect_max_insufficient` but never checks it. Only
  `drafted >= min` and `job completed` are validated.

### TC-02-BUG-010 / 011: vendor request `questionnaire_id` (found while fixing the fragile test)
- `create_vendor_request` stores `body.questionnaire_id` without checking existence or workspace.
- 010: a nonexistent id raises `IntegrityError: ForeignKeyViolation ... vendor_requests_questionnaire_id_fkey`
  at `db.commit()`. That is unhandled, so HTTP 500 (reproduced on a fresh DB with
  `test_create_with_questionnaire_id` before the fix).
- 011: an admin of workspace A can pass a questionnaire id from workspace B. The public, unauthenticated
  `GET /api/vendor-response?token=` then returns B's questionnaire `filename` and `question_count`.
  This is an object-authorization gap (E06). Repro: create a questionnaire in workspace 2, then
  as a workspace-1 admin POST `{"vendor_email": "x@example.com", "questionnaire_id": <ws2 id>}` and
  GET the `share_url` token. The response contains the workspace-2 filename.
- Verified on a fresh `*_test` DB with a throwaway test (not committed). Create returned `200`. The public GET, with no cookies, returned
  `200 {'questionnaire': {'name': '<ws2 filename>', 'question_count': 0}, ...}`. With `questionnaire_id: 999999`
  the TestClient raised `IntegrityError`.

## Test-suite isolation findings

| ID | file:line | Kind | Runtime effect | Path | Epic | Severity |
|---|---|---|---|---|---|---|
| TC-02-BUG-014 | `apps/api/tests/release/test_health_probes.py:155,167,178,187,386` | order-dependent test | The 4 DB-backed `/workerz` tests fail when the file runs alone on a fresh DB (`relation "worker_heartbeat" does not exist`) | test-only (covers `GET /workerz`) | E02 | Low |

### TC-02-BUG-014: `/workerz` release tests need migrations they never request
- `_set_db_heartbeat()` writes to `worker_heartbeat` (migration 026), but the four tests that call it
  (`test_workerz_fresh_heartbeat_is_alive`, `test_workerz_stale_heartbeat_is_503`,
  `test_workerz_staleness_threshold_is_configurable`, `test_worker_db_heartbeat_write_is_read_as_fresh`)
  only use a bare `TestClient`, so nothing in the file migrates the DB.
- They passed only because something else migrated first: an earlier test using `client`/`_ensure_test_data`
  in full-suite order, or the `pytest_sessionstart` hook, which migrates up front only when `TC_REQUIRE_DB=1`.
- Repro (fresh, never-migrated `*_test` DB, `TC_REQUIRE_DB` unset): `pytest tests/release/test_health_probes.py`
  gives `4 failed, 20 passed`.
- Fix: the tests request the shared `migrated_db` fixture (`tests/conftest.py`, built on `_ensure_test_data`).
  `tests/release/test_health_probes_isolation.py` reruns the file alone on a throwaway fresh DB in CI.

## Verified not bugs (no entry)
- F841 with no hidden logic: `tags.py:87` `dt`, `automation_service.py:161` `summary` (the
  notification builds its own text), `evidence_processor.py:39` `char_budget` (budget enforced in
  tokens), `gmail_ingest_service.py:93` `snippet`, `promise_service.py:173` `stale_evidence`,
  `security_page_service.py:11` `categories`, `slack_ingest_service.py:264` `ctrl_desc` (lower
  match quality only), test-side `ledger`, `ev`, `item2`, `si_id`, `r2`, `original_env`, `backend`,
  `r1`, `me`.
- E712 (20): `== True/False` inside SQLAlchemy filters is required there. Rewriting to `if x:` would break the query.
- E741 (4): naming only. E501 (1): length only.
