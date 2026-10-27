# TC-01-003a evidence: PyMuPDF -> pypdf

Everything here uses synthetic data only. There were no model calls, and every PDF run used
`--network none`. Base is `f72def3`.

## Environment
| Item | Value |
|---|---|
| Python | 3.11.18, test image `tc-core-api-test:c20f949-sa20-pdf` (project deps plus `sqlalchemy<2.1`) |
| Comparison libraries | pymupdf 2.0 (baseline, AGPL-3.0 / Artifex commercial), pypdf 6.21.2 (BSD-3-Clause), pdfplumber 0.11.10 (MIT) on pdfminer.six 20260107 (MIT), pypdfium2 5.14.0 (Apache-2.0/BSD-3-Clause, bundles a PDFium binary), Pillow 13.0.0 (MIT-CMU) |
| Branch run image | `tc-core-api-test:c20f949-sa20-nopymupdf`, the image above with pymupdf, pymupdf_layout, pymupdf4llm, pdfplumber, pdfminer.six and pypdfium2 **uninstalled**. This proves the branch needs none of them |
| DB | Postgres 16 + pgvector on an internal docker network (full suite only) |

## Corpus
No locator corpus existed in the package or repo, so a synthetic one is built in
`apps/api/tests/pdf_locator_corpus.py` with the pure-Python `app/services/synthetic_pdf.py`. It
has 17 cases:
- page numbering with a blank page;
- 20 span markers on one page, checking order and offsets;
- two-column layouts, with left-first and right-first content streams;
- a ruled table grid;
- questionnaires: sectioned, numbered, and table-cell;
- Latin-1 and typographic punctuation;
- PDFs with no text: image-only, vector-only, whitespace-only;
- corrupt and truncated files;
- the repo fixture `security_policy.pdf`;
- RC4 encryption: owner password only, and user password required.

## Commands and results
| Step | Command (from `apps/api`) | Result |
|---|---|---|
| Candidate comparison | `python ../../artifacts/acceptance/TC-01-003a/compare_backends.py` | `backend_comparison.md`: **pypdf 149/149**, pymupdf baseline 145/149 (fails only the "table row on one line" checks), pdfplumber 125/149 (merges left and right columns onto one line) |
| Baseline capture | `python ../../artifacts/acceptance/TC-01-003a/record_baseline.py <f72def3 sources>` | `tests/fixtures/pdf_locator/baseline_pymupdf.json` |
| New tests (no pymupdf installed) | `python -m pytest -q tests/test_pdf_text_locator_corpus.py` | 61 passed (`new_tests_branch.txt`) |
| Full suite, base f72def3 (with pymupdf) | `python -m pytest tests -q -rf -p no:randomly --continue-on-collection-errors` | 2 failed, 1285 passed, 2 skipped, 2 errors (`full_base_summary.txt`) |
| Full suite, branch (no pymupdf) | same | 2 failed, 1346 passed, 2 skipped, 2 errors (`full_branch_summary.txt`). The same 2 failures and 2 errors exist on master; there are 61 new passes |
| Lint | `ruff check .` (ruff 0.5.6, the pre-commit pin) | 479 errors on base and 479 on branch. The new and changed files are clean, and the new files are `ruff format`-clean |

## Review follow-up (Coordinator review of PR #11)
Run with the same `nopymupdf` image against an isolated Postgres on its own internal network.
| Step | Command (from `apps/api`) | Result |
|---|---|---|
| New + corpus + related ingest/parse/job tests | `python -m pytest -v -rs -p no:randomly tests/test_pdf_failure_surfacing.py tests/test_pdf_text_locator_corpus.py tests/test_upload_parse_review.py tests/test_indexing_enterprise_fixes.py tests/test_generate_export.py tests/test_jobs_api.py tests/test_questionnaire_parser.py tests/test_ingestion_pipeline.py` | 98 passed, 0 skipped (`followup_tests_branch.txt`) |
| Full suite, branch + follow-up | `python -m pytest tests -q -rfs -p no:randomly --continue-on-collection-errors` | 2 failed, 1359 passed, 3 skipped, 2 errors (`full_followup_summary.txt`). These are the same 2 failures and 2 collection errors as on master. The extra skip is `test_feedback_capture` "No questionnaires", which depends on data in a fresh DB |
| Lint | ruff 0.5.6 | The new and changed PDF files are clean and `ruff format`-clean. `index_service.py` has one more E402, matching that file's existing import style |
