# TC-13-005 CI runs

Verified heads, each with `build` and `web-release-e2e` succeeded on `push` and `pull_request`. Not merged.

## Stale-mapping head

`d97b5386b6ce3aae7b4d5f525a95da6a6de8361d`. This is the product head that fails a stale workbook fingerprint or mapped cell as `export_mapping_stale` and writes a current version-1 answer only into the stored answer cell. Master `71e4a7c` and `960fe4f` are ancestors.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [43742714941](https://github.com/Johnathan-u/trust-copilot/actions/runs/43742714941) | [build 132899183550](https://github.com/Johnathan-u/trust-copilot/actions/runs/43742714941/job/132899183550) | success |
| push | [43742714941](https://github.com/Johnathan-u/trust-copilot/actions/runs/43742714941) | [web-release-e2e 132899183886](https://github.com/Johnathan-u/trust-copilot/actions/runs/43742714941/job/132899183886) | success |
| pull_request | [43742719776](https://github.com/Johnathan-u/trust-copilot/actions/runs/43742719776) | [build 132899199125](https://github.com/Johnathan-u/trust-copilot/actions/runs/43742719776/job/132899199125) | success |
| pull_request | [43742719776](https://github.com/Johnathan-u/trust-copilot/actions/runs/43742719776) | [web-release-e2e 132899198823](https://github.com/Johnathan-u/trust-copilot/actions/runs/43742719776/job/132899198823) | success |

## Implementation head

`c059b9df3da86c2610795d63080681526f324c27` on `tc/TC-13-005-export-failures`, parent `4272dff`.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [43738568133](https://github.com/Johnathan-u/trust-copilot/actions/runs/43738568133) | [build 132886516332](https://github.com/Johnathan-u/trust-copilot/actions/runs/43738568133/job/132886516332) | success |
| push | [43738568133](https://github.com/Johnathan-u/trust-copilot/actions/runs/43738568133) | [web-release-e2e 132886515978](https://github.com/Johnathan-u/trust-copilot/actions/runs/43738568133/job/132886515978) | success |
| pull_request | [43738579307](https://github.com/Johnathan-u/trust-copilot/actions/runs/43738579307) | [build 132886550965](https://github.com/Johnathan-u/trust-copilot/actions/runs/43738579307/job/132886550965) | success |
| pull_request | [43738579307](https://github.com/Johnathan-u/trust-copilot/actions/runs/43738579307) | [web-release-e2e 132886551276](https://github.com/Johnathan-u/trust-copilot/actions/runs/43738579307/job/132886551276) | success |

## After merging master

`04a6dab8da1e95476563c3cb181e67b3ac95cc4d` merges master `71e4a7c` (TC-09-002, PR #239) into the implementation head. The export-failure behavior was re-tested locally (`test_export_failure.py` and `test_export_fidelity.py`, 76 passed) before this CI.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [43740260122](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740260122) | [build 132891644518](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740260122/job/132891644518) | success |
| push | [43740260122](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740260122) | [web-release-e2e 132891644277](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740260122/job/132891644277) | success |
| pull_request | [43740266701](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740266701) | [build 132891664844](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740266701/job/132891664844) | success |
| pull_request | [43740266701](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740266701) | [web-release-e2e 132891665148](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740266701/job/132891665148) | success |

Master `960fe4f` (TC-09-002 CI record only) is an ancestor of the stale-mapping head above.
