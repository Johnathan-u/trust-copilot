# CI for TC-04-002

Follow-up head: `5ec47c0f9a7db9cd75da2cc45e220db5d4157bcd`

`build` and `web-release-e2e` are green on both `push` and `pull_request` for that commit.
It is the background send, the slow-provider timing tests, and the verification and invite
scope. No migration. Master `af478a601a5df6ac49410711c77a14b014c70bf4` was merged first.
The commit that adds this record is evidence only and is polled separately. It does not
change auth behavior.

An earlier head, `1229fb37f32b2bbd7bc188b1435b279199331de9`, was also green
(push 44223591524, pull_request 44223629332). That commit still called the provider on
the request path, so those runs do not cover this follow-up.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [44283854887](https://github.com/Johnathan-u/trust-copilot/actions/runs/44283854887) | build `134731283711` | success |
| push | 44283854887 | web-release-e2e `134731284349` | success |
| pull_request | [44283860049](https://github.com/Johnathan-u/trust-copilot/actions/runs/44283860049) | build `134731306041` | success |
| pull_request | 44283860049 | web-release-e2e `134731305529` | success |
