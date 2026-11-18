# TC-15-017 CI runs

Product head: `bbe4d22dae4000788b6ccbb69dc703bffa3fdc5b`

`build` and `web-release-e2e` both succeeded on `push` and `pull_request` for that commit. Base is master `960fe4f97772ac72ba6f726d24e49b0ef57f2eb1`. This note is a later commit, so its own runs are separate.

| Event | Run | Job | Conclusion |
| --- | --- | --- | --- |
| push | [43755580139](https://github.com/Johnathan-u/trust-copilot/actions/runs/43755580139) | [build 132938829027](https://github.com/Johnathan-u/trust-copilot/actions/runs/43755580139/job/132938829027) | success |
| push | [43755580139](https://github.com/Johnathan-u/trust-copilot/actions/runs/43755580139) | [web-release-e2e 132938828762](https://github.com/Johnathan-u/trust-copilot/actions/runs/43755580139/job/132938828762) | success |
| pull_request | [43755605221](https://github.com/Johnathan-u/trust-copilot/actions/runs/43755605221) | [build 132938903837](https://github.com/Johnathan-u/trust-copilot/actions/runs/43755605221/job/132938903837) | success |
| pull_request | [43755605221](https://github.com/Johnathan-u/trust-copilot/actions/runs/43755605221) | [web-release-e2e 132938903475](https://github.com/Johnathan-u/trust-copilot/actions/runs/43755605221/job/132938903475) | success |

## Re-verification 2026-11-18

Read at `74b8ae62a5271990fcacf6bbd00717f2f8aff6ec`. Local `ui-16` is 14 passed and `test_tc15017b_questionnaire_list.py` is 5 passed. Logs: `reverify-2026-11-18-playwright.txt`, `reverify-2026-11-18-pytest.txt`.

`build` and `web-release-e2e` run IDs for the re-verification head are not in this section yet. They are added in a later commit on this branch once that head is green. The commit that adds them is later than the head it records.
