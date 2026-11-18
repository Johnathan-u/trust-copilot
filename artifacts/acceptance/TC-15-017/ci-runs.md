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

Product head: `937e075def7ea9cabca089e03ad3a9c1e5e13fe4`

Read against master `74b8ae62a5271990fcacf6bbd00717f2f8aff6ec`. Local `ui-16` is 14 passed and `test_tc15017b_questionnaire_list.py` is 5 passed. Logs: `reverify-2026-11-18-playwright.txt`, `reverify-2026-11-18-pytest.txt`.

`build` and `web-release-e2e` both succeeded on `push` and `pull_request` for `937e075d`. This note is a later commit, so its own runs are separate.

| Event | Run | Job | Conclusion |
| --- | --- | --- | --- |
| push | [44288698746](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288698746) | [build 134747957177](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288698746/job/134747957177) | success |
| push | [44288698746](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288698746) | [web-release-e2e 134747957393](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288698746/job/134747957393) | success |
| pull_request | [44288728985](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288728985) | [build 134748062611](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288728985/job/134748062611) | success |
| pull_request | [44288728985](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288728985) | [web-release-e2e 134748062095](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288728985/job/134748062095) | success |
