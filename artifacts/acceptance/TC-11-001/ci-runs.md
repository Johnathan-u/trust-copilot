# TC-11-001 CI runs

The accepted evidence in `result.json` records push run [42879828829](https://github.com/Johnathan-u/trust-copilot/actions/runs/42879828829) and pull_request run [42879866297](https://github.com/Johnathan-u/trust-copilot/actions/runs/42879866297) for `b0f0b99eb3dd2d9f507709f4dd6af26653de20ab`, and master run [42886627596](https://github.com/Johnathan-u/trust-copilot/actions/runs/42886627596) for `edd332013d09af4222b9c700a489f9b4c7709091`. Those rows are unchanged.

## Re-verification 2026-11-18

Product head: `937e075def7ea9cabca089e03ad3a9c1e5e13fe4`

Read against master `74b8ae62a5271990fcacf6bbd00717f2f8aff6ec`. Local `test_provider_adapter.py` is 46 passed and `test_tc11001a_evidence_wording.py` is 3 passed (49 passed together). Log: `reverify-2026-11-18-pytest.txt`.

`build` and `web-release-e2e` both succeeded on `push` and `pull_request` for `937e075d`. This note is a later commit, so its own runs are separate.

| Event | Run | Job | Conclusion |
| --- | --- | --- | --- |
| push | [44288698746](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288698746) | [build 134747957177](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288698746/job/134747957177) | success |
| push | [44288698746](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288698746) | [web-release-e2e 134747957393](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288698746/job/134747957393) | success |
| pull_request | [44288728985](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288728985) | [build 134748062611](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288728985/job/134748062611) | success |
| pull_request | [44288728985](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288728985) | [web-release-e2e 134748062095](https://github.com/Johnathan-u/trust-copilot/actions/runs/44288728985/job/134748062095) | success |
