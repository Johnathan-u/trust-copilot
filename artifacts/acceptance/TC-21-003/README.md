# TC-21-003: remediation evidence links follow the qualification rule

This run closes the two gaps found at `55d7deece26ebcf52634f95a4554a31121c3a849`. Framework catalogs stay blocked pending TC-01-007. No framework control text was added.

The stale pointer in the previous README, which sent readers to `artifacts/acceptance/TC-21-003a/`, is replaced by this run.

| Gap | Result |
|---|---|
| Remediation evidence links are verified only when the evidence qualifies | Met by `test_remediation_evidence_does_not_verify_unqualified_links` and `test_remediation_evidence_verifies_only_a_qualifying_link` |
| Compliance create and patch refuse a foreign, suspended, or removed owner | Met by `test_compliance_owner_must_be_an_active_workspace_member`. These three cases already passed on the parent. They add coverage of existing behaviour. No product change was required. |

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. `TC_REQUIRE_DB=1`. Node `v24.22.1` first on `PATH` for the full suite. `TC_REQUIRE_WEB_TOOLCHAIN=1` and `TC_REQUIRE_API_QUALITY=1` on the full suite, as CI sets them.

```text
python -m pytest tests/release/test_domain_compliance_controls.py -q --tb=line
python -m pytest -q --tb=line -rs
```

## SHA

Parent `62afe126fdb0c69fe73537c29ee54c8a6869a1e6` (`tc/TC-21-002-control-contract`, PR #197). Branch `tc/TC-21-003-evidence-gate`. This evidence is in the same commit as the fix, so the commit SHA is the child of that parent. CI run IDs are not in this file. They are reported with the pull request after `build` and `web-release-e2e` finish on that commit.

## Tests without the fix

The five new tests were run against the parent product code, with only the new tests present. Command and output are in `pytest-q-without-fix.txt`. Exit 1. 2 failed, 3 passed, 13 deselected, 75 warnings, 2.61s.

- Pending, expired, and deleted-document evidence attached through remediation was stored with `verified` true.
- An existing unverified link for qualifying evidence stayed unverified.
- `POST /api/compliance/controls` and `PATCH /api/compliance/controls/{id}` already returned 404 `owner_not_in_workspace` for a user from another workspace, a suspended member, and a removed member, and the stored row was unchanged. Those three tests passed on the parent.

## Environment

- Python 3.12.3
- PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1), database `trustcopilot_test` at `127.0.0.1:5432`, user `postgres`
- pgvector extension 0.6.0. CI's image is PostgreSQL 16.15 with pgvector 0.8.7. Migrations and this suite completed on 0.6.0.
- SQLAlchemy 2.0.55
- Alembic 1.20.1
- Node 24.22.1
- Playwright Chromium (browser tests)
- `alembic heads`: `tc17003_security_claims (head)`
- `ruff check .` and `ruff format --check .` from `apps/api`: exit 0, ruff 0.5.6

The full-suite database was dropped and recreated before that run. An earlier full run failed three browser tests because Chromium was not installed. That run is not the record below. The recorded run is after `npx playwright install --with-deps chromium`.

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_controls.py -q --tb=line` | 0 | 18 passed, 0 skipped, 368 warnings, 10.32s |
| `python -m pytest -q --tb=line -rs` | 0 | 6328 passed, 1 skipped, 34868 warnings, 573.43s |

No test in `tests/release/test_domain_compliance_controls.py` was skipped. The one full-suite skip is `tests/test_trust_scoring_blind.py`: `external_data: blind test pack not checked in; set TC_TRUST_SCORING_BLIND_PACK to run`. It did not trip the `TC_REQUIRE_DB=1` failure hook. Output for the domain file is `pytest-q.txt`. The full-suite summary is `pytest-full.txt`.
