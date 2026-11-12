# TC-15-049 browser evidence

Command, from `apps/web`:

```
npx playwright test e2e/release/screen-deals.spec.ts --retries=0
```

Tested product commit: `012d21eae3987589ed151ad54b8142082fa2f70a`.
Local environment: Linux, Node 24.22.1, npm 11.19.1, Playwright 1.64.1.
Local result: exit 0, **62 passed, 0 failed, 0 skipped, 0 flaky**.

Screenshots from that browser run:

- `screenshots/deals-list-360.png`
- `screenshots/deals-list-768.png`
- `screenshots/deals-list-1440.png`
- `screenshots/deals-links-360.png`
- `screenshots/deals-links-768.png`
- `screenshots/deals-links-1440.png`

Axe JSON in this directory:

- `axe-list-360.json`, `axe-list-768.json`, `axe-list-1440.json`
- `axe-links-360.json`, `axe-links-768.json`, `axe-links-1440.json`

Each report has `violationCount` 0 and ends with a newline.
The existing CI axe step still writes list and dialog reports under
`artifacts/acceptance/TC-15-049a`. This directory does not replace that path.

## CI for 012d21eae3987589ed151ad54b8142082fa2f70a

Push run [43143281028](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143281028):

| Job | ID | Conclusion |
| --- | --- | --- |
| build | [130935133389](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143281028/job/130935133389) | success |
| web-release-e2e | [130935132983](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143281028/job/130935132983) | success |

Pull request run [43143296465](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143296465):

| Job | ID | Conclusion |
| --- | --- | --- |
| build | [130935182454](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143296465/job/130935182454) | success |
| web-release-e2e | [130935181885](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143296465/job/130935181885) | success |

Pytest on both `build` jobs: **6450 passed, 1 skipped**. The only skip is
`tests/test_trust_scoring_blind.py:33`.
`screen-deals.spec.ts` on both `web-release-e2e` jobs: **62 passed, 0 failed, 0 skipped, 0 flaky**.
Playwright exit 0 and axe check exit 0 on both events.

This file records those runs. It does not change the deals page, the spec, or the screenshots.
