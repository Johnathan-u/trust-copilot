# TC-09-002 CI runs

Product head: `a77923983a9bfefb78ef251ff23d99a05dc53151`

`build` and `web-release-e2e` both succeeded on `push` and `pull_request` for that commit. It includes the merge of master `4272dff`. The owner squash-merged that head as `71e4a7cb32f338324acb991dbb7a700ddb8134e1` (#239).

| Event | Run | Job | Conclusion |
| --- | --- | --- | --- |
| push | [43736937340](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736937340) | [build 132881504364](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736937340/job/132881504364) | success |
| push | [43736937340](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736937340) | [web-release-e2e 132881504041](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736937340/job/132881504041) | success |
| pull_request | [43736941560](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736941560) | [build 132881516187](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736941560/job/132881516187) | success |
| pull_request | [43736941560](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736941560) | [web-release-e2e 132881516364](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736941560/job/132881516364) | success |

## Earlier head

`6c9f8166861b99e05eba97fa95e92322fbe43a92` failed `build` on both events because pre-commit `ruff-format` and trailing-whitespace rewrote files. `web-release-e2e` succeeded on both. `a5c69ddf1d207e6320895717e13d65b9ae1ff828` is the formatting fix. Master then moved, so the green product head is `a779239` above.

| Event | Run | Job | Conclusion |
| --- | --- | --- | --- |
| push | [43734421424](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734421424) | [build 132873748642](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734421424/job/132873748642) | failure |
| push | [43734421424](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734421424) | [web-release-e2e 132873748977](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734421424/job/132873748977) | success |
| pull_request | [43734427926](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734427926) | [build 132873766320](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734427926/job/132873766320) | failure |
| pull_request | [43734427926](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734427926) | [web-release-e2e 132873766529](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734427926/job/132873766529) | success |
