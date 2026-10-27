# TC-13-003 acceptance evidence

All data is synthetic. No LLM or model calls were made, no external services were used, and no
credentials were touched. pytest ran in a container on an `--internal` Docker network (no egress)
with `OPENAI_API_KEY` empty. The probe and generator containers ran with `--network none`.

## Environment
- Implementation SHA: the PR head commit (branch `tc/core/TC-13-003`). Baseline and origin/master
  are `c20f949161ac12a619b396d30904448ffd74d532`.
- Test image: `apps/api/Dockerfile` target `base` (python 3.11, openpyxl 3.1.5) plus
  `sqlalchemy<2.1`. This is the same pre-existing psycopg2 versus SQLAlchemy 2.1 environment
  finding documented for TC-08-005. It was worked around in the image only and the repo is not
  changed.
- DB for the full suite: `pgvector/pgvector:pg16`, migrated by conftest to alembic head `075`.
  The new tests do not use the DB.
- Real viewer: LibreOffice headless (`soffice --convert-to csv`) on the box.

## Command (from `apps/api`)
```
python -m pytest -p no:cacheprovider tests/test_export_literal_text.py -v
```
The ticket proposes `tests/release/test_export_literal_text.py`. Under Coordinator ruling Q3 the
file lives in `tests/` instead, because `tests/release/` is owned by TC-02-001.

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
