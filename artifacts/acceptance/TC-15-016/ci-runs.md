# TC-15-016 CI runs

Product head: `9c31a7c232a1f1d3922ec8908376cbf72916cc66`

`build` and `web-release-e2e` both succeeded on `push` and `pull_request` for that commit. It includes the merge of master `960fe4f97772ac72ba6f726d24e49b0ef57f2eb1`. This note is a later commit, so its own runs are separate.

| Event | Run | Job | Conclusion |
| --- | --- | --- | --- |
| push | [43744818466](https://github.com/Johnathan-u/trust-copilot/actions/runs/43744818466) | [build 132905678587](https://github.com/Johnathan-u/trust-copilot/actions/runs/43744818466/job/132905678587) | success |
| push | [43744818466](https://github.com/Johnathan-u/trust-copilot/actions/runs/43744818466) | [web-release-e2e 132905678758](https://github.com/Johnathan-u/trust-copilot/actions/runs/43744818466/job/132905678758) | success |
| pull_request | [43744822901](https://github.com/Johnathan-u/trust-copilot/actions/runs/43744822901) | [build 132905691817](https://github.com/Johnathan-u/trust-copilot/actions/runs/43744822901/job/132905691817) | success |
| pull_request | [43744822901](https://github.com/Johnathan-u/trust-copilot/actions/runs/43744822901) | [web-release-e2e 132905691944](https://github.com/Johnathan-u/trust-copilot/actions/runs/43744822901/job/132905691944) | success |

## Earlier head

`fa78758c4329ed689608ef3b4fbe7453d433ea6b` failed `build` on both events because pre-commit trailing-whitespace and end-of-file-fixer rewrote the Playwright logs and axe JSON. `web-release-e2e` succeeded on both. `889dee3` is that formatting fix, then master was merged.

| Event | Run | Job | Conclusion |
| --- | --- | --- | --- |
| push | [43743886233](https://github.com/Johnathan-u/trust-copilot/actions/runs/43743886233) | [build 132902813893](https://github.com/Johnathan-u/trust-copilot/actions/runs/43743886233/job/132902813893) | failure |
| push | [43743886233](https://github.com/Johnathan-u/trust-copilot/actions/runs/43743886233) | [web-release-e2e 132902814112](https://github.com/Johnathan-u/trust-copilot/actions/runs/43743886233/job/132902814112) | success |
| pull_request | [43743904271](https://github.com/Johnathan-u/trust-copilot/actions/runs/43743904271) | [build 132902872212](https://github.com/Johnathan-u/trust-copilot/actions/runs/43743904271/job/132902872212) | failure |
| pull_request | [43743904271](https://github.com/Johnathan-u/trust-copilot/actions/runs/43743904271) | [web-release-e2e 132902872444](https://github.com/Johnathan-u/trust-copilot/actions/runs/43743904271/job/132902872444) | success |
