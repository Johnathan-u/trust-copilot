# TC-21-007b: Provenance ids on coverage recommendations

Framework catalogs stay **BLOCKED** pending **TC-01-007**. No migration. Schema stays `compliance-coverage-controls/v1`.

A recommendation with no live source stays in the response with empty id lists, so `title` and `improves_questions` do not disappear.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/test_compliance_coverage_unit.py tests/release/test_domain_coverage_recommendations.py tests/release/test_domain_compliance_coverage.py -q
```

Web, from `apps/web`:

```text
npx vitest run lib/coverageConsumer.test.ts
```

## SHA

Tests ran on `395221f78fcd744d862a5795c76c10da25adb16c`. That commit is the parent of this evidence commit. It keeps the recommendation id lists and points the coverage page at the shared recommendation type so the existing cast typechecks.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| The three pytest files above | 0 | 47 passed, 94 warnings, 2.74s |
| `coverageConsumer.test.ts` | 0 | 5 passed |
| `npm run typecheck` in `apps/web` | 0 | `tsc --noEmit` completed |
