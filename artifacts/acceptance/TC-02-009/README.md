# TC-02-009 CI evidence

Not accepted. Not counted toward DONE. The behaviour note is `docs/release/tickets/TC-02-009.md`. The runbook is `docs/ops/ci-evidence.md`. This folder does not edit the tracker and does not record CI run ids.

The earlier `pytest.txt` and `ci-runs.md` are the PARTIAL verification logs. They are unchanged. This folder does not add a run id.

## Command

From `apps/api`:

```sh
python -m pytest tests/release/test_ci_evidence.py -q
```

The tests parse the workflow files. They do not start Postgres, the object store, or a browser.

## Failing before

Product code was master `1593c5b821c140232ae9b867ada936c88d4f3cee`. The test ran against that workflow. Log: `failing-before.txt`.

Exit 1. 3 failed, 8 passed, 0 skipped. Master does not print the evidence block.

## Passing after

Same command on product code `f5ea66eed73be8b0aead933b14d2d20c648e0132`. Log: `passing-after.txt`.

11 passed, 0 failed, 0 skipped, exit 0. Both jobs print the commit SHA, the image digest or `image: none`, the test command, and passed/failed/skipped totals. The e2e block also prints Playwright and axe totals. Every upload keeps `retention-days: 14`. A missing SHA line, a missing retention day, an unmasked password echo, and a Pages deploy that ignores a failed CI conclusion each fail the checker. The redactor removes a synthetic connection URL, a bearer value, and a cookie from a report and a trace zip. PNG bytes stay.

## Environment

`environment.txt`. Python 3.12.3, pytest 9.1.1, PyYAML 6.0.3. No database. No migration. Fixtures are synthetic. No customer document.
