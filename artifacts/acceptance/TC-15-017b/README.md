# TC-15-017b evidence

Named release test: `apps/api/tests/release/test_tc15017b_questionnaire_list.py`.

Command, from `apps/api`:

```
TC_REQUIRE_DB=1 python -m pytest tests/release/test_tc15017b_questionnaire_list.py --tb=line -q
```

| Run | Result |
| --- | --- |
| Before the list contract | 5 failed, exit 1 (`failing-before.txt`) |
| After the list contract | 5 passed, exit 0 (`passing-after.txt`) |

The screen check is `npx playwright test e2e/release/ui-16.spec.ts --retries=0` from `apps/web`. `ui-16` was already a `web-release-e2e` candidate. This change does not edit the CI workflow.

`ci-runs.md` records `build` and `web-release-e2e` for the product head, then the documentation commit waits for the same two jobs on push and pull_request. This directory does not accept TC-15-017 or TC-15-017b.
