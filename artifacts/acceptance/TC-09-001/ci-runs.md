# TC-09-001 CI runs

Product head: `c356da1812f8067ced7b0d5860bbb98e6caa2e35`

`build` and `web-release-e2e` both succeeded on `push` and `pull_request` for that commit. It includes the merge of master `71e4a7c` (TC-09-002, TC-13-003a, and the TC-14 reconciliation notes). The XLSX parser keeps the explicit answer-cell mapping from that merge and still raises on a workbook that cannot be opened.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [43739721275](https://github.com/Johnathan-u/trust-copilot/actions/runs/43739721275) | [build 132889974199](https://github.com/Johnathan-u/trust-copilot/actions/runs/43739721275/job/132889974199) | success |
| push | [43739721275](https://github.com/Johnathan-u/trust-copilot/actions/runs/43739721275) | [web-release-e2e 132889974426](https://github.com/Johnathan-u/trust-copilot/actions/runs/43739721275/job/132889974426) | success |
| pull_request | [43739725517](https://github.com/Johnathan-u/trust-copilot/actions/runs/43739725517) | [build 132889987896](https://github.com/Johnathan-u/trust-copilot/actions/runs/43739725517/job/132889987896) | success |
| pull_request | [43739725517](https://github.com/Johnathan-u/trust-copilot/actions/runs/43739725517) | [web-release-e2e 132889988054](https://github.com/Johnathan-u/trust-copilot/actions/runs/43739725517/job/132889988054) | success |

## Earlier heads, not final

`794f7ec` and `b1d5d3a` failed `build` on both events. The first was Prettier on the questionnaire page. The second was `ruff-format` on the new test module. `web-release-e2e` succeeded on both events for `794f7ec` and for `b1d5d3a`. `152a77c` was green on both events, then master `71e4a7c` was merged to produce the product head above.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [43736406116](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736406116) | [build 132879854839](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736406116/job/132879854839) | failure (Prettier) |
| push | [43736406116](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736406116) | [web-release-e2e 132879855140](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736406116/job/132879855140) | success |
| pull_request | [43736429074](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736429074) | [build 132879925985](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736429074/job/132879925985) | failure (Prettier) |
| pull_request | [43736429074](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736429074) | [web-release-e2e 132879926293](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736429074/job/132879926293) | success |
| push | [43736828821](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736828821) | [build 132881167396](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736828821/job/132881167396) | failure (`ruff-format`) |
| push | [43736828821](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736828821) | [web-release-e2e 132881167580](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736828821/job/132881167580) | success |
| pull_request | [43736831949](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736831949) | [build 132881176859](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736831949/job/132881176859) | failure (`ruff-format`) |
| pull_request | [43736831949](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736831949) | [web-release-e2e 132881176564](https://github.com/Johnathan-u/trust-copilot/actions/runs/43736831949/job/132881176564) | success |
| push | [43737596664](https://github.com/Johnathan-u/trust-copilot/actions/runs/43737596664) | [build 132883526096](https://github.com/Johnathan-u/trust-copilot/actions/runs/43737596664/job/132883526096) | success |
| push | [43737596664](https://github.com/Johnathan-u/trust-copilot/actions/runs/43737596664) | [web-release-e2e 132883526281](https://github.com/Johnathan-u/trust-copilot/actions/runs/43737596664/job/132883526281) | success |
| pull_request | [43737600997](https://github.com/Johnathan-u/trust-copilot/actions/runs/43737600997) | [build 132883539701](https://github.com/Johnathan-u/trust-copilot/actions/runs/43737600997/job/132883539701) | success |
| pull_request | [43737600997](https://github.com/Johnathan-u/trust-copilot/actions/runs/43737600997) | [web-release-e2e 132883539921](https://github.com/Johnathan-u/trust-copilot/actions/runs/43737600997/job/132883539921) | success |
