# TC-02-002 acceptance evidence: lock Python and PostgreSQL driver dependencies

All data is synthetic. No paid API, production host or external account was contacted. Network use was limited to
public PyPI and Docker Hub downloads. Each CI-mirror run used a fresh `pgvector/pgvector:pg16@sha256:7b822b0a…`
container with a generated throwaway password, which is shown as `<generated, not shown>` / `***` and appears in no file.

## Commit / baseline

| Item | Value |
|---|---|
| Baseline (origin/master when cut) | `1a0e6146` (TC-11-001 #16) |
| Code commits | `31589ce` (lock, CI, Dockerfile, release test, skip policy), `e5ff2c4` (drop duplicated PDF-library check) |
| Merge preview | `3ac2965` = local merge of `e5ff2c4` into origin/master `d527863` (TC-10-003 #28, TC-02-BUG-014 #31); clean, never pushed |
| Master merge | `520608f` = merge commit of origin/master `ec40823` into `35babd8` (pypdf bump); clean, no conflicts |
| Working dir | `apps/api` unless noted |

## Environment

| Item | Value |
|---|---|
| OS | Linux 6.12 (agent sandbox), x86_64 |
| CI-mirror Python | 3.11.17 (uv venv; `ci.yml` uses 3.11). Locks target `--python-version 3.11 --universal` |
| Lock tool | uv 0.13.4 (`scripts/lock-python-deps.sh`) |
| Installer | pip (`--require-hashes`), then `--no-deps -e .`, then `pip check` |
| Postgres | pgvector/pgvector:pg16 (digest-pinned, same as ci.yml), pgvector 0.8.7, `TC_REQUIRE_DB=1` |
| Docker base | `python:3.11-slim` (tag; resolved to `python@sha256:ae952e0a…` on this run) |
| Provider env | `OPENAI_API_KEY` unset; conftest scrubs provider keys |

## Results

| # | Command | Exit | Totals | File |
|---|---|---|---|---|
| 1 | CI mirror on branch `e5ff2c4`: install from `requirements-dev.lock`, migrations, ruff, safe collection, **`python -m pytest tests/release/test_python_lock.py -q`** (`TC_REQUIRE_DB=1`), `pytest -rs` (`TC_REQUIRE_DB=1`), web build | every step 0 | lock test **20 passed**; full suite **1557 passed, 1 skipped** (`external_data` blind pack, allowed), 0 failed | `ci_mirror_branch_e5ff2c4.txt` |
| 2 | Same CI mirror on merge preview `3ac2965` | every step 0 | lock test **20 passed**; full suite **1591 passed, 1 skipped** (same `external_data`) | `ci_mirror_merge_preview_3ac2965.txt` |
| 3 | First CI mirror on `31589ce` (kept as negative evidence) | backend tests 1 | 2 failed, 1556 passed, 1 skipped. (a) this test's synthetic case spelled the removed PDF package and tripped `test_pdf_text_locator_corpus` (fixed in `e5ff2c4`). (b) the new skip policy turned the order-dependent `test_questionnaire_answer_evidence` "no questions" skip into a failure (fixed on master by TC-02-BUG-014; passes in #1 and #2) | `ci_mirror_run1_31589ce.txt` |
| 4 | AC2: four clean venvs (`--no-cache-dir`), runtime ×2 from `requirements.lock`, dev ×2 from `requirements-dev.lock` | 0 ×4 | runtime a == b (61 pkgs), dev a == b (67 pkgs). Dev-only: pytest, ruff, pluggy, iniconfig, packaging, Pygments; 0 runtime versions differ; runtime build imports `app.main`, driver `psycopg2`, `pytest` not importable | `ac2_two_clean_builds.txt` |
| 5 | AC2: two `docker build --no-cache --target production` from `git archive e5ff2c4` | 0 / 0 | image a == image b (62 pkgs), equal to `requirements.lock` except marker-excluded entries and the base image's own `packaging`; `import app.main` ok, driver `psycopg2`, no pytest/ruff, `pip check` ok | `docker_two_builds.txt` |
| 6 | Lock regeneration ×2 from a clean checkout | 0 / 0 | both locks byte-identical (`git diff --quiet`) | `lock_regen_and_negative.txt` |
| 7 | Negatives: SQLAlchemy 2.1.0 in lock; pytest in runtime lock; hash removed; installed `idna` drift; all `idna` hashes tampered | 1 each | the release test fails with the specific problem; pip refuses the tampered lock (`THESE PACKAGES DO NOT MATCH THE HASHES`) | `lock_regen_and_negative.txt` |
| 8 | "Current set" check: unlocked install of master `1a0e614` (old CI step) vs `requirements-dev.lock` | 0 | identical except platform-marker entries; measured before the pypdf bump; the lock now pins pypdf 6.21.3 (security bump, see ticket doc and row 9) | `current_set_vs_master.txt` |
| 9 | pypdf 6.21.3 security bump: `lock-python-deps.sh --upgrade-package pypdf`, then CI mirror on the bumped tree (before the master merge) | lock test 0, PDF tests 0, backend 1 | only pypdf changes in both locks (hashes = PyPI); lock test **20 passed**; PDF tests **75 passed** at 6.21.3; backend 1556 passed, 1 skipped, 1 failed = the order-dependent `test_generate_answers_passes_document_ids_to_retrieval` "no questions" skip that TC-02-BUG-014 fixed on master (passes in row 10) | `pypdf_bump_6.21.3.txt` |
| 10 | Full CI mirror on `520608f` = merge of origin/master `ec40823` (TC-07-001 #13, TC-10-003a #34, TC-02-BUG-005 #32, TC-25-005 #25, TC-02-003 #9, …) into the pypdf bump: npm ci --ignore-scripts, pre-commit (0 modifications), typecheck, vitest, install from lock, migrations, ruff, safe collection, lock test, PDF tests, `pytest -rs` (`TC_REQUIRE_DB=1`), build, npm audit (Node 24.22.1) | every ci.yml step 0 | lock test **20 passed**; PDF tests **75 passed** (pypdf 6.21.3); full suite **1992 passed, 1 skipped** (`external_data`), 0 failed. Extra non-CI `format:check` exits 1 on `next-env.d.ts` only, same as master (pre-commit excludes it) | `ci_mirror_merge_master_ec40823.txt` |

AC1 is shown by `test_fresh_interpreter_imports_app_and_connects_with_psycopg2` passing in #1 and #2. That test starts a
fresh interpreter in the locked env, imports `app.main`, and runs `SELECT 1` against the CI DB with dialect
`postgresql`, driver/DBAPI `psycopg2`, and SQLAlchemy/psycopg2-binary at the locked versions. Without a DB it skips
locally, but fails under `TC_REQUIRE_DB=1`.

Reviewer sign-off: pending (PR review).
