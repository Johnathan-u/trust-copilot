# CI for TC-27-001

Qualifying implementation head: `bc5df226853edfe55336caacdd12080394387fac`

`build` and `web-release-e2e` are green on both `push` and `pull_request` for that commit.
It adds the review fix: a configured `BACKUP_S3_BUCKET` with no `aws` on `PATH` exits 127
at stage `upload` and leaves the local archive. Master `960fe4f97772ac72ba6f726d24e49b0ef57f2eb1`
was already contained. No migration, auth, admin, or CI-gate change.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [43744870807](https://github.com/Johnathan-u/trust-copilot/actions/runs/43744870807) | build | success |
| push | 43744870807 | web-release-e2e | success |
| pull_request | [43744875686](https://github.com/Johnathan-u/trust-copilot/actions/runs/43744875686) | build | success |
| pull_request | 43744875686 | web-release-e2e | success |

Earlier qualifying head `e9ed816d2f12003905778ff0a6fb83503c863b82` was also green on both events, before the missing-`aws` fix. Master at that time was `71e4a7cb32f338324acb991dbb7a700ddb8134e1`.

The first head `95b43d5140eb83360180a7c5ec238f05cd221130` is not qualifying. `build` failed the secret-inventory scan on the backup fixture. `web-release-e2e` succeeded. The fixture was renamed and pointed at a reserved example host in `e9ed816`.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [43740634781](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740634781) | build | success |
| push | 43740634781 | web-release-e2e | success |
| pull_request | [43740642085](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740642085) | build | success |
| pull_request | 43740642085 | web-release-e2e | success |

Failed runs at `95b43d5`, not used:

| Event | Run | build | web-release-e2e |
|---|---|---|---|
| push | [43740206287](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740206287) | failure | success |
| pull_request | [43740221908](https://github.com/Johnathan-u/trust-copilot/actions/runs/43740221908) | failure | success |
