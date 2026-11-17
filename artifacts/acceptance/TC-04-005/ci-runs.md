# CI for TC-04-005

Qualifying head: `d397e8e8259037a510efa678a3c320708c8e55db`

That head is the branch tip that was squash-merged as `480b4ae19d14fc46b3638b341dad8d90f2fcec2f` (#271). `build` and `web-release-e2e` are green on both `push` and `pull_request` for `d397e8e8`. Production auth is unchanged. The merge commit does not change the test, the ticket note, or this evidence except by squashing it onto master.

| Event | Run | build | web-release-e2e |
|---|---|---|---|
| push | [44184737539](https://github.com/Johnathan-u/trust-copilot/actions/runs/44184737539) | [134398110417](https://github.com/Johnathan-u/trust-copilot/actions/runs/44184737539/job/134398110417) success | [134398110818](https://github.com/Johnathan-u/trust-copilot/actions/runs/44184737539/job/134398110818) success |
| pull_request | [44184748040](https://github.com/Johnathan-u/trust-copilot/actions/runs/44184748040) | [134398148144](https://github.com/Johnathan-u/trust-copilot/actions/runs/44184748040/job/134398148144) success | [134398147861](https://github.com/Johnathan-u/trust-copilot/actions/runs/44184748040/job/134398147861) success |

An earlier head, `6abd49ef257259e124ecfeab21fc174defa25ca4`, failed `build` on the trailing-whitespace hook in `failing-before.txt`. `364d06d6` removed those spaces. That head is not the qualifying head.
