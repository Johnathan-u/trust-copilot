# CI for TC-04-003

Implementation head: `7a9b0f8609a38ebd9128deeb2caa3504ef7e7706`

`build` and `web-release-e2e` are green on both `push` and `pull_request` for that commit.
It is the formatted reset-revocation change. No migration. Master `af6dca06` (tracker rev 27)
was merged after these runs. The commit that adds this file is the final head and is polled
separately. It does not change auth behavior.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [44204508255](https://github.com/Johnathan-u/trust-copilot/actions/runs/44204508255) | build `134466874758` | success |
| push | 44204508255 | web-release-e2e `134466874263` | success |
| pull_request | [44204517423](https://github.com/Johnathan-u/trust-copilot/actions/runs/44204517423) | build `134466905621` | success |
| pull_request | 44204517423 | web-release-e2e `134466905087` | success |

The first head `e17412f04b48106f264fdbcc7b55157f1f213418` is not qualifying. `build` failed
`ruff-format` on the new test. `web-release-e2e` succeeded. The test was reformatted in `7a9b0f86`.

| Event | Run | build | web-release-e2e |
|---|---|---|---|
| push | [44203335845](https://github.com/Johnathan-u/trust-copilot/actions/runs/44203335845) | failure | success |
| pull_request | [44203365733](https://github.com/Johnathan-u/trust-copilot/actions/runs/44203365733) | failure | success |
