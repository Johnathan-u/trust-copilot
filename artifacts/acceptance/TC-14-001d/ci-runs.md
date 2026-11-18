# TC-14-001d CI

Workflow: CI (`.github/workflows/ci.yml`)
Head: `ec88e8e23c102f893e4fd692b5261d3e603650e3`
Required jobs: `build`, `web-release-e2e`

push run [44234541953](https://github.com/Johnathan-u/trust-copilot/actions/runs/44234541953) conclusion=success

- build success
- web-release-e2e success

pull_request run [44234561320](https://github.com/Johnathan-u/trust-copilot/actions/runs/44234561320) conclusion=success

- build success
- web-release-e2e success

`web-release-e2e` still runs `e2e/release/design-tokens.spec.ts`. That spec covers `/design-tokens`, not the public pages in this change. Both jobs were green on this head, so that spec still passed. No release-spec `--min-tests` floor was changed.

Master at the time of this note was `d69109e720df3a697ff4af9eb1b222ae1553a628`, the parent of this head.
