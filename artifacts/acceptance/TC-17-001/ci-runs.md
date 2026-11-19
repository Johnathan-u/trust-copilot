# CI for TC-17-001 gap 1

Head `c893fa27937ed851f9ba3af87148d26b757af946`. Squash-merged as `08443a6922ac8d62756b72459ad9e595da8a9366` (#301).

`build` and `web-release-e2e` are green on both `push` and `pull_request` for that commit. No migration. This records gap 1 only. The parent is not accepted.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [44353190364](https://github.com/Johnathan-u/trust-copilot/actions/runs/44353190364) | build `134974141355` | success |
| push | 44353190364 | web-release-e2e `134974141845` | success |
| pull_request | [44353324788](https://github.com/Johnathan-u/trust-copilot/actions/runs/44353324788) | build `134974627167` | success |
| pull_request | 44353324788 | web-release-e2e `134974628955` | success |

## Review fixes on #307

Green head `559bd9d7f3c921a0400929d411770bfb4292d28c`. That commit records the behavior commit `383467b54170b143eccd738d61956548d1b87880` (first-upgrade bind and the 409 acknowledge check) and does not change the route, migration, or tests. `build` and `web-release-e2e` are green on both events for `559bd9d7`. The commit that adds this section does not change them.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [44453392420](https://github.com/Johnathan-u/trust-copilot/actions/runs/44453392420) | build `135322525892` | success |
| push | 44453392420 | web-release-e2e `135322525648` | success |
| pull_request | [44453400342](https://github.com/Johnathan-u/trust-copilot/actions/runs/44453400342) | build `135322551015` | success |
| pull_request | 44453400342 | web-release-e2e `135322551503` | success |

## Accepted head #307

Head `07cbc176531edb9d5e58878a5574e43d4c4a4d91`. That commit records the review-fix tree and does not change the route, migration, or tests. Squash-merged as `7fea456dde7a8ed3148e11045d5488a77004aff4` (#307). Claude accepted the parent on [#307 comment 7008980985](https://github.com/Johnathan-u/trust-copilot/pull/307#issuecomment-7008980985) at 2026-11-19T12:22:50Z. He is the independent reviewer for DoD5. `build` and `web-release-e2e` are green on both events for `07cbc176`. The `IS DISTINCT FROM` change is not in this squash. It is open child TC-17-001h. Records revision 35 marks the parent DONE.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [44455944772](https://github.com/Johnathan-u/trust-copilot/actions/runs/44455944772) | build `135330849141` | success |
| push | 44455944772 | web-release-e2e `135330848742` | success |
| pull_request | [44455950570](https://github.com/Johnathan-u/trust-copilot/actions/runs/44455950570) | build `135330868430` | success |
| pull_request | 44455950570 | web-release-e2e `135330868166` | success |
