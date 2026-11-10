# TC-21-002: remediation status and evidence follow the control contract

This run closes the two AC1 gaps found at `55d7deece26ebcf52634f95a4554a31121c3a849`. Framework catalogs stay blocked pending TC-01-007. No framework control text was added.

| Gap | Result |
|---|---|
| Remediation evidence writes status through the contract and cannot set `verified` | Met by `test_remediation_evidence_bump_follows_the_control_contract`, `test_remediation_evidence_rejects_unknown_status`, and `test_remediation_evidence_rejects_verified_status` |
| Compliance link, unlink, and remediation evidence agree with the legacy evidence list | Met by `test_compliance_evidence_link_and_unlink_match_legacy` and `test_remediation_evidence_matches_legacy_and_compliance_lists` |

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. `TC_REQUIRE_DB=1`. Node `v24.22.1` first on `PATH`.

```text
python -m pytest tests/release/test_domain_controls.py -q --tb=line
python -m pytest -q --tb=line
```

## SHA

Parent `02e833c78aa362d78c366a2187dcbd040b9838e1` (`origin/master` at the time of the run). Branch `tc/TC-21-002-control-contract`. This evidence is in the same commit as the fix, so the commit SHA is the child of that parent. CI run IDs are not in this file. They are reported with the pull request after `build` and `web-release-e2e` finish on that commit.

## Tests without the fix

The five new tests were run against the parent product code, with the fix stashed and only the new tests present. Command and output are in `pytest-q-without-fix.txt`. Exit 1. 5 failed, 6 deselected, 77 warnings, 3.50s.

- A remediation bump to `implemented` left compliance `status` at `implemented` and canonical lifecycle at `in_progress`.
- `bump_control_to` `enabled` and `verified` both returned 200.
- A compliance evidence link and a remediation evidence link each left `GET /api/controls/{id}/evidence` empty.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `127.0.0.1:5432`, user `postgres`
- SQLAlchemy 2.0.55
- Alembic 1.20.1
- Node 24.22.1
- `alembic heads`: `tc17003_security_claims (head)`
- `ruff check .` from `apps/api`: exit 0

The full-suite database was dropped and recreated before that run. Web unit tests were not run. This change does not touch `apps/web`.

## Totals

The first implementation, parent `62afe126fdb0c69fe73537c29ee54c8a6869a1e6`, recorded 11 passed in this file and 6316 passed in the full suite. The review fixes below are the current run.

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_controls.py -q --tb=line` | 0 | 15 passed, 0 skipped, 205 warnings, 7.33s |
| `python -m pytest -q --tb=line` | 0 | 6320 passed, 8 skipped, 34815 warnings, 580.77s |

No test in `tests/release/test_domain_controls.py` was skipped. The full-suite skips did not trip the `TC_REQUIRE_DB=1` failure hook. One collected external-data skip is `tests/test_trust_scoring_blind.py`. Output for the domain file is `pytest-q.txt`.

## Review fixes

Parent for the fail-without-fix run is `62afe126fdb0c69fe73537c29ee54c8a6869a1e6`. Product code was that parent. The new assertions were on the working tree. Output is `pytest-q-review-without-fix.txt`: exit 1, 6 failed, 9 deselected, 3.45s. The same file then passed on a fresh database: 15 passed, exit 0.

| Test | Without the fix | With the fix |
|---|---|---|
| `test_remediation_evidence_bump_follows_the_control_contract` | `verified_at` was a timestamp | `verified_at` is null |
| `test_remediation_default_bump_keeps_a_verified_control` | status became `implemented` | status stayed `verified` |
| `test_remediation_leaving_verified_clears_verification_stamps` | `verified_at` was stamped again | `verified_at` and `verified_by_user_id` are null |
| `test_remediation_evidence_failure_persists_nothing` | status was committed as `implemented` before the evidence write failed | status, ticket, and links stayed unchanged |
| `test_create_after_rename_keeps_the_existing_identity` | create returned 200 | create returned 409 `control_identity_conflict` and the renamed row stayed `implemented` |
| `test_routes_agree_on_canonical_contract_and_retry` | a second create returned 200 | a second create with a different status returned 409 |

A repeat with the same lifecycle, owner, and name still returns the existing row and does not change it. That is the contract-event retry. A create that would change any of those is the 409.
