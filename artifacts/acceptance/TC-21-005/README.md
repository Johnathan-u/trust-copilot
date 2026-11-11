# TC-21-005: Versioned human-reviewed control mapping overrides

Framework catalogs stay **BLOCKED** pending **TC-01-007**. This run did not add framework requirement text.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_compliance_mappings.py -q
```

## SHA

Tests ran on `080f0752c232de04a020df2916a23bfdfbb3d804`. This evidence file was added after that commit and does not change the code under test.

## Environment

- Python 3.12.3
- PostgreSQL 16.15, database `trustcopilot_test` at `localhost:5432`, user `postgres`
- SQLAlchemy 2.0.55
- Alembic head after the test: `tc21005_mapping_version (head)`
- Migration parent: `bug018a_gap_closed_at_reason`

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_mappings.py -q` | 0 | 10 passed, 185 warnings, 8.08s |

Pytest printed `10 passed, 185 warnings in 8.08s` and did not report a skipped test. The quiet progress line was `..........`.

## Web consumer

Before this change, on `5aa3b438f6b19283d6cd5f1557293f62eacce9e6`, nothing under `apps/web` called `/api/compliance/control-mappings`. A search for `control-mappings` in `apps/web` returned no matches, so the versioned decision had no UI consumer apart from `GET /suggest`.

After this change the coverage page loads that decision when a recommended question is opened. `apps/web/lib/controlMappingClient.ts` calls suggest, confirm, override, and rollback. `apps/web/lib/controlMappingConsumer.ts` rejects a payload whose state, precedence, or fields do not match. Reviewers see the decision. Only an administrator is offered confirm, override, and rollback. Override stays disabled until a rationale is entered. Rollback is offered only when a saved version exists.

Local checks, Python 3.12.3, Node 24.22.1, PostgreSQL 16.15 database `trustcopilot_test` at `127.0.0.1:5432`:

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_domain_compliance_mappings.py -q` from `apps/api` | 0 | 11 passed, 209 warnings, 10.62s |
| `npx vitest run` from `apps/web` | 0 | 52 files, 467 passed |

The new API test captures suggest, confirm, override, and rollback payloads from PostgreSQL. A confirm after an override stays `overridden` with `precedence_held`. A new client, after `engine.dispose()`, reads that same suggestion. The web reader accepts those payloads and rejects a malformed one. The vitest remounts the mapping panel and still shows Overridden. No test was skipped.

Local Playwright Chromium against the coverage page, with the API mocked, passed 10 tests in `e2e/release/ui-23.spec.ts`: question disclosure, source retry, workspace change, and the 360/768/1440 accessibility checks. CI workflow files were not changed.
