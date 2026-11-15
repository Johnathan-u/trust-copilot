# TC-13-003a CI runs

Product head: `9487c71e5fedf314b8d7df88fa59c3486e6a02c3`

`build` and `web-release-e2e` both succeeded on `push` and `pull_request` for that commit. It includes the merge of master `6af195d`.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [43734902107](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734902107) | [build 132875234555](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734902107/job/132875234555) | success |
| push | [43734902107](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734902107) | [web-release-e2e 132875234289](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734902107/job/132875234289) | success |
| pull_request | [43734907917](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734907917) | [build 132875250706](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734907917/job/132875250706) | success |
| pull_request | [43734907917](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734907917) | [web-release-e2e 132875250896](https://github.com/Johnathan-u/trust-copilot/actions/runs/43734907917/job/132875250896) | success |

## Earlier head, not final

`c6933d164834277538d5504ed9bdfa80826d2814` failed `ruff-format` on the new test module. `9e5874154ca76b6c329255fc8ad55c91740114b6` fixed the formatting and was green, then master `6af195d` was merged to produce the product head above.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [43731994125](https://github.com/Johnathan-u/trust-copilot/actions/runs/43731994125) | [build 132866264453](https://github.com/Johnathan-u/trust-copilot/actions/runs/43731994125/job/132866264453) | failure (`ruff-format`) |
| push | [43731994125](https://github.com/Johnathan-u/trust-copilot/actions/runs/43731994125) | [web-release-e2e 132866264164](https://github.com/Johnathan-u/trust-copilot/actions/runs/43731994125/job/132866264164) | success |
| pull_request | [43732015808](https://github.com/Johnathan-u/trust-copilot/actions/runs/43732015808) | [build 132866332317](https://github.com/Johnathan-u/trust-copilot/actions/runs/43732015808/job/132866332317) | failure (`ruff-format`) |
| pull_request | [43732015808](https://github.com/Johnathan-u/trust-copilot/actions/runs/43732015808) | [web-release-e2e 132866332074](https://github.com/Johnathan-u/trust-copilot/actions/runs/43732015808/job/132866332074) | success |
