# CI for the Slack all-opted-out skip

Qualifying head: `c1cd1dcf4fd3612d3b69786f6ddfeb2f1bcc8193`

`build` and `web-release-e2e` are green on both `push` and `pull_request`.
Master was `0e8cb32496a7847a727d89ed54753990b91a3127` and was already contained.
No migration. This file is the only later commit.

Earlier head `2b7c5da40d79c97ae1c555d593a0982e7d84d78e` is not qualifying.
`ruff-format` failed `build` on both events. `web-release-e2e` succeeded.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [43731649613](https://github.com/Johnathan-u/trust-copilot/actions/runs/43731649613) | build | success |
| push | 43731649613 | web-release-e2e | success |
| pull_request | [43731657072](https://github.com/Johnathan-u/trust-copilot/actions/runs/43731657072) | build | success |
| pull_request | 43731657072 | web-release-e2e | success |

Failed runs at `2b7c5da`, not used:

| Event | Run | build | web-release-e2e |
|---|---|---|---|
| push | [43730670175](https://github.com/Johnathan-u/trust-copilot/actions/runs/43730670175) | failure | success |
| pull_request | [43730689645](https://github.com/Johnathan-u/trust-copilot/actions/runs/43730689645) | failure | success |
