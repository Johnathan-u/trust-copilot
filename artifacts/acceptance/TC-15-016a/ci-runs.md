# TC-15-016a CI runs

Product head: `3b33c7aa4a2ffebe2a759ed557224df0bfcbe657`

`build` and `web-release-e2e` both succeeded on `push` and `pull_request` for that commit. This note is a later commit, so its own runs are separate.

| Event | Run | Job | Conclusion |
| --- | --- | --- | --- |
| push | [44242025927](https://github.com/Johnathan-u/trust-copilot/actions/runs/44242025927) | [build 134591963958](https://github.com/Johnathan-u/trust-copilot/actions/runs/44242025927/job/134591963958) | success |
| push | [44242025927](https://github.com/Johnathan-u/trust-copilot/actions/runs/44242025927) | [web-release-e2e 134591963570](https://github.com/Johnathan-u/trust-copilot/actions/runs/44242025927/job/134591963570) | success |
| pull_request | [44242032593](https://github.com/Johnathan-u/trust-copilot/actions/runs/44242032593) | [build 134591983741](https://github.com/Johnathan-u/trust-copilot/actions/runs/44242032593/job/134591983741) | success |
| pull_request | [44242032593](https://github.com/Johnathan-u/trust-copilot/actions/runs/44242032593) | [web-release-e2e 134591984491](https://github.com/Johnathan-u/trust-copilot/actions/runs/44242032593/job/134591984491) | success |

## Earlier head

`3d7bac593c568678e75ab8e39a8f9ab5d3d24986` failed `build` on both events. The secret inventory blocked `apps/api/tests/release/test_tc_15_016a_documents_list.py` because a storage path was assigned to a name the scan treats as a credential. `3b33c7aa` renames that fixture. `web-release-e2e` on the earlier head is not the head recorded above.

| Event | Run | Job | Conclusion |
| --- | --- | --- | --- |
| push | [44241479676](https://github.com/Johnathan-u/trust-copilot/actions/runs/44241479676) | [build 134590172895](https://github.com/Johnathan-u/trust-copilot/actions/runs/44241479676/job/134590172895) | failure |
| pull_request | [44241496236](https://github.com/Johnathan-u/trust-copilot/actions/runs/44241496236) | [build 134590224212](https://github.com/Johnathan-u/trust-copilot/actions/runs/44241496236/job/134590224212) | failure |
