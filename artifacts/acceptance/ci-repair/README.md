# ci-repair acceptance evidence

Branch `tc/platform/ci-repair` after merging `tc/platform/ci-mechanical` (42b394f)
with merge commit `ae2bf62` (tree `28291a9a`). The conflicts in
`apps/api/tests/conftest.py` and `apps/api/tests/test_notification_fire_points.py`
take ci-repair's side. The ruff recipe (`--fix --unfixable F401`, `format`, `--add-noqa`)
then runs on the touched files. The result is identical to
`ci-repair-after-mechanical.diff` and the validated trial tree.

This branch now contains everything from ci-mechanical (PR #17), so merging #18 alone lands both.

| Check | Result | Log |
|---|---|---|
| `pre-commit run --all-files` (ruff, ruff-format, prettier, whitespace, EOF, yaml) | all Passed, exit 0, 0 files modified | `precommit.txt` |
| `ruff check .` (ruff 0.5.6, apps/api) | All checks passed, exit 0 | `ci-local.txt` |
| `alembic upgrade head` on pinned pgvector (pg16, pgvector 0.8.7), per-run `*_test` DB, generated creds | exit 0 | `ci-local.txt` |
| `pytest -rs` with `TC_REQUIRE_DB=1`, `OPENAI_API_KEY` unset | **1287 passed, 3 skipped**, exit 0 | `ci-local.txt` |
| `npm run build` (apps/web) | Compiled successfully, exit 0 | `ci-local.txt` |

The 3 skips come from absent seed or local-only data: the blind test pack,
"No reviewed workspace controls" and "No questionnaires". None of them is about DB
availability: with `TC_REQUIRE_DB=1` an unreachable DB fails the session.

Environment: a local mirror of the CI `build` job (`ci_local2.sh`) with Python 3.11
(fresh uv venv) and SQLAlchemy 2.0.55. It uses the image
`pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`
in a fresh container on 127.0.0.1:55434. CI uses the service port 5432.
All data is synthetic and the password is generated per run and never printed.
