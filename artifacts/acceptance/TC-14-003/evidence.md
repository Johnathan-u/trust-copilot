# TC-14-003 acceptance evidence

Synthetic data only. Screenshots and axe output contain no credentials, customer documents or personal data.

## Completed CI at `92b0c3e`

Head `92b0c3ec40b887859eca74b1a6c7bf480c0d3f27` completed CI on both events:

- push: https://github.com/Johnathan-u/trust-copilot/actions/runs/42362793798
- pull_request: https://github.com/Johnathan-u/trust-copilot/actions/runs/42362798123

Both conclusions are success. `web-release-e2e` on each run reported:

- `e2e/release/screen-trust-requests.spec.ts`: 30 passed, 0 failed, 0 skipped
- `e2e/release/dialog-toast.spec.ts`: 8 passed, 0 failed, 0 skipped
- `e2e/release/ui-22.spec.ts`: 23 passed, 0 failed, 0 skipped

An earlier note on this branch said a filtered local `ui-22` command passed 5 tests. That was a subset (`-g "delayed create|rejected create|long content, keyboard"`). It is not the CI total. The CI total for `ui-22` at `92b0c3e` is 23 passed, 0 skipped.

Head `7bbfb7c` had failed `build` on push run 42324149162 and pull_request run 42324166892. That failure is not the state of `92b0c3e`.

## This commit

This commit is the product fix and this evidence together. It adds live regions for the Slack test result, Slack and Gmail ingest results, questionnaire answer-evidence "Saved", and the demo-proof summary "Saved". Its push and pull_request runs do not exist until after the commit is pushed. CI is left to run. This note does not invent those run IDs. The parent sitrep after CI will name the new head and those runs.

No new Playwright command was required for the markup change. The shared dialog and toast spec was not re-run.

## Local checks for this commit

```bash
cd apps/web
npx eslint app/dashboard/slack/page.tsx app/dashboard/gmail/page.tsx app/dashboard/questionnaires/\[id\]/page.tsx app/dashboard/demo-proof/page.tsx --max-warnings=0
```

- Exit status: 0
- Node: v24.22.1
- No Playwright spec was re-run for this markup change.

## Not claimed

This note does not say the new head is green. Modifier-clicks and `beforeunload` are unchanged. Non-blocking follow-ups from the review (unset MFA and Gmail errors that are never shown, disconnect/remove without `res.ok`, other status regions, Topbar Saved, extra security-page tests) are not in this commit.

Grok (worker). The implementer does not accept this result.
