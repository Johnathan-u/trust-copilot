# TC-17-005 CI runs

Evidence head: `adc516624590050b07025f7b4afd3d869d37ee22`

`build` and `web-release-e2e` both succeeded on `push` and `pull_request` for that commit. The local pytest log in this directory was already on that head. This note is a later commit, so its own runs are separate.

| Event | Run | Job | Conclusion |
| --- | --- | --- | --- |
| push | [44298805422](https://github.com/Johnathan-u/trust-copilot/actions/runs/44298805422) | [build 134782763806](https://github.com/Johnathan-u/trust-copilot/actions/runs/44298805422/job/134782763806) | success |
| push | [44298805422](https://github.com/Johnathan-u/trust-copilot/actions/runs/44298805422) | [web-release-e2e 134782764175](https://github.com/Johnathan-u/trust-copilot/actions/runs/44298805422/job/134782764175) | success |
| pull_request | [44298843407](https://github.com/Johnathan-u/trust-copilot/actions/runs/44298843407) | [build 134782898102](https://github.com/Johnathan-u/trust-copilot/actions/runs/44298843407/job/134782898102) | success |
| pull_request | [44298843407](https://github.com/Johnathan-u/trust-copilot/actions/runs/44298843407) | [web-release-e2e 134782898550](https://github.com/Johnathan-u/trust-copilot/actions/runs/44298843407/job/134782898550) | success |
