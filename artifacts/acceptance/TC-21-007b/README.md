# TC-21-007b: Provenance ids on coverage recommendations

Local only. This branch was not pushed. Framework catalogs stay **BLOCKED** pending **TC-01-007**. No migration. Schema stays `compliance-coverage-controls/v1`.

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

Tests ran on `da54ed83697302319ca1b78170248b0e0de1f5fc`. That commit is the parent of this evidence commit.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| The three pytest files above | 0 | 46 passed, 90 warnings, 3.40s |
| `coverageConsumer.test.ts` | 0 | 5 passed |
