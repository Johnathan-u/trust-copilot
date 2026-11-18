# CI for TC-04-002

The runs in the table are head `1229fb37f32b2bbd7bc188b1435b279199331de9`.
That commit still calls the reset provider on the request path. They do not cover the
background send, the slow-provider timing tests, or the verification and invite scope.
`build` and `web-release-e2e` for the follow-up head are recorded here after both events
are green. No migration.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [44223591524](https://github.com/Johnathan-u/trust-copilot/actions/runs/44223591524) | build `134531225982` | success |
| push | 44223591524 | web-release-e2e `134531226329` | success |
| pull_request | [44223629332](https://github.com/Johnathan-u/trust-copilot/actions/runs/44223629332) | build `134531345432` | success |
| pull_request | 44223629332 | web-release-e2e `134531345670` | success |
