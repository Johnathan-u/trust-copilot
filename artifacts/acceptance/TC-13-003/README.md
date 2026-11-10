# TC-13-003 acceptance evidence

All data is synthetic. No LLM or model calls were made, no external services were used, and no
credentials were touched. pytest ran in a container on an `--internal` Docker network (no egress)
with `OPENAI_API_KEY` empty. The probe and generator containers ran with `--network none`.

## Environment
- Implementation SHA: PR #7 head `f708a046f0ce7eb93561c19f3ef96541ebfc7d8b`, merge
  `5c8f1dce33ed568ad35c0904824699211628ae6e`. The implementation branch was
  `tc/core/TC-13-003`. Baseline and origin/master at that time were
  `c20f949161ac12a619b396d30904448ffd74d532`.
- Test image: `apps/api/Dockerfile` target `base` (python 3.11, openpyxl 3.1.5) plus
  `sqlalchemy<2.1`. This is the same pre-existing psycopg2 versus SQLAlchemy 2.1 environment
  finding documented for TC-08-005. It was worked around in the image only and the repo is not
  changed.
- DB for the full suite: `pgvector/pgvector:pg16`, migrated by conftest to alembic head `075`.
  The new tests do not use the DB.
- Real viewer: LibreOffice headless (`soffice --convert-to csv`) on the box.

## Command (from `apps/api`)

The file is `apps/api/tests/release/test_export_literal_text.py`. The ticket command is:

```
python -m pytest tests/release/test_export_literal_text.py -q
```

Original local runs, before the file moved, used:

```
python -m pytest -p no:cacheprovider tests/test_export_literal_text.py -v
```

## Results
| Run | Exit | Totals |
|---|---|---|
| New tests, branch (`new_tests_branch.txt`) | 0 | 33 passed, 0 skipped |
| New tests vs **baseline** | 2 | collection ImportError. The behavioural probe (`baseline_probe.txt`) shows the defects |
| Export related (`test_export_literal_text`, `test_export_golden`, `test_smoke`) | 0 | 38 passed |
| Full `tests/` baseline c20f949 | 1 | 2 failed, 1285 passed, 2 skipped, 2 errors |
| Full `tests/` branch, run 1 | 1 | 3 failed, 1317 passed, 2 skipped, 2 errors (see note) |
| Full `tests/` branch, run 2 | 1 | 2 failed, 1318 passed, 2 skipped, 2 errors |

The failures and errors that appear on both baseline and branch are pre-existing:
- `test_answer_pipeline.py::test_partial_completion_progress`
- `test_p1_multi_tenant_hardening.py::...::test_generate_answers_blocked_at_quota` (503 vs 429)
- 2 collection errors in `test_alerts_api.py` and `test_coverage_api.py`. These ad-hoc scripts
  call `localhost:8000` when imported.

Note on branch run 1: `test_questionnaire_answer_evidence.py::test_generate_answers_passes_document_ids_to_retrieval`
failed once. That test picks "the first questionnaire in workspace 1" from a shared DB and
swallows exceptions, so its result depends on state left by earlier runs. It does not touch export
code, it passed 3 out of 3 times in isolation, and it passed in full-suite run 2. It is flaky and
unrelated to this change.

## Real-viewer check (`libreoffice_viewer_check.txt`)
The same synthetic export was generated on baseline and on the branch, then opened in LibreOffice.
- Baseline: `=1+1` evaluates to `2`, and `=HYPERLINK(...)` becomes a live link that shows `x`.
- Branch: every answer is shown literally.
- On both, the template's original formula `C1 = =10*10` still evaluates to `100`.
- The branch file opened without any repair prompt.

## Moved file at `4edcdc6`

The file is `apps/api/tests/release/test_export_literal_text.py`. This section records
the CI runs of commit `4edcdc66fbb1730704a112f07aa1d4c1d036f357`. The commit that
adds this section is a later SHA, so it is not the SHA under test.

Both `build` and `web-release-e2e` succeeded on the push and on the pull request.

| Event | Run | Build job | web-release-e2e job |
|---|---|---|---|
| push | [42862249561](https://github.com/Johnathan-u/trust-copilot/actions/runs/42862249561) | 129991173325 | 129991172834 |
| pull_request | [42862276141](https://github.com/Johnathan-u/trust-copilot/actions/runs/42862276141) | 129991263776 | 129991262898 |

- Command: from `apps/api`, `pytest -rs`, with `SESSION_SECRET=test-secret`,
  `TC_REQUIRE_DB=1`, `TC_REQUIRE_WEB_TOOLCHAIN=1` and `TC_REQUIRE_API_QUALITY=1`.
  That is the suite that runs the ticket command
  `python -m pytest tests/release/test_export_literal_text.py -q`.
- Environment: GitHub-hosted `ubuntu-26.04` image `20261101.186.1`; Python 3.11.18;
  pytest 9.1.1; SQLAlchemy 2.0.55; psycopg2-binary 2.9.13; pgvector 0.5.1.
  PostgreSQL image `pgvector/pgvector:pg16` (16.15, vector 0.8.7), digest
  `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`.
  Push database `tc_ci_42862249561_1_test`. Pull-request database
  `tc_ci_42862276141_1_test`. Both on `127.0.0.1:5432`.
- Exit status: 0 on both build jobs.
- Totals for this file: 33 passed, 0 skipped. Pytest wraps the progress line.
  Push build log:

```
tests/release/test_export_literal_text.py .............................. [ 51%]
...                                                                      [ 51%]
```

  The first line has 30 progress dots and the next line has 3. Together that is
  33 passed and 0 skipped. The pull-request build log has the same two lines.
- Full suite, both runs: 6419 passed, 1 skipped, 51 warnings. Push duration
  710.49s. Pull-request duration 605.74s. The skip is
  `tests/test_trust_scoring_blind.py:33` (external data) and is unrelated.

`result.json` in this directory is the same record. Reviewer signoff is still pending.
