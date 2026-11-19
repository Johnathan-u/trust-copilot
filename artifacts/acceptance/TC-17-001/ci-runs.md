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
