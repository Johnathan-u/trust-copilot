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

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_controls.py -q --tb=line` | 0 | 11 passed, 0 skipped, 140 warnings, 7.29s |
| `python -m pytest -q --tb=line` | 0 | 6316 passed, 8 skipped, 34757 warnings, 664.30s |

No test in `tests/release/test_domain_controls.py` was skipped. The full-suite skips did not trip the `TC_REQUIRE_DB=1` failure hook. One collected external-data skip is `tests/test_trust_scoring_blind.py`. Output for the domain file is `pytest-q.txt`.
