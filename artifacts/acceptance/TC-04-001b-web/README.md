# TC-04-001b-web — Anonymous checkout correction

Assignment and technical ruling:
[#85 comment6511823848](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6511823848),
continuing [PR #77](https://github.com/Johnathan-u/trust-copilot/pull/77).
Base: pure master merge `cf1189990ff0ca57f5477258db7cbb3b261de46a`.
The correction is a separate child commit; the prior history remains intact.

## Reproduced problem and correction

Checkout is public, but `WorkspaceCreationEntry` always reads the authenticated
creation-policy endpoint. A real rendered `CheckoutPage`, with the network
boundary returning anonymous HTTP 401, showed the unavailable/Try again state
instead of the invitation and configured contact. All three new component cases
failed before the correction: email contact, HTTPS contact and absent contact.

Checkout now directly renders the existing `WorkspaceInvitation`, retaining
its heading, pricing back link and validated sales-contact value. It offers no
workspace, account or billing form and performs no policy read. Shared UI/auth,
backend, settings/onboarding creation gates and owner decisions are unchanged.

## Why browser cases changed

| Previous checkout case | Corrected public behavior | Reason |
| --- | --- | --- |
| Anonymous checkout mocked policy `true` with HTTP 200 | Anonymous visitor clicks Get Started on pricing; policy fixture would return 401; invitation renders with zero policy reads and no forms | The endpoint requires authentication, while this route is public and performs no creation |
| Anonymous checkout mocked policy `false` with HTTP 200 | Configured sales contact remains visible to an anonymous visitor; policy fixture would return 401 and is never requested | Preserves the public contact path that the prior failure hid |
| Policy outage replaced checkout with unavailable/Try again | Public invitation and pricing back navigation remain available during a policy outage; zero policy reads and no forms | Public invitation content does not depend on creation eligibility |

The 11 settings/onboarding policy and submission cases are unchanged. The policy
spec still has **14 cases**, including pending/denied/unavailable/malformed policy,
retry, command-palette gating and submit-time 403/409/429 handling. Checkout
screenshots/axe now cover anonymous invitation and configured contact, replacing
the inapplicable allowed-policy and unavailable-policy checkout states.

The earlier `workspace-create-denied.spec.ts` still has all **8 cases**. Its shared
invitation fixture now returns 401 for anonymous checkout policy requests and
asserts that checkout makes none; signed-in onboarding still receives the same
denied boolean. Existing contact, focus, back-navigation and no-create checks
remain in place. No release gate or test minimum was lowered.

## Local verification

Node `v24.22.1`, npm `11.9.0`; dependencies copied from an existing checkout with
an identical `package-lock.json`. Commands ran from `apps/web`.

| Command | Result |
| --- | --- |
| `npx --no-install vitest run tests/unit/checkout-invitation.test.ts` before the fix | 3 failed; actual component DOM showed unavailable/Try again, with invitation/contact absent |
| `npx --no-install vitest run tests/unit/checkout-invitation.test.ts tests/unit/workspace-creation-policy.test.ts tests/unit/sales-contact.test.ts tests/unit/workspace-create-response.test.ts` after the fix | 24 passed |
| `npm run test:unit` | 34 files, 229 passed |
| `npm run typecheck` | Passed, route types generated and TypeScript exit 0 |
| Scoped ESLint with `--max-warnings=0` for the four changed TS/TSX files | Passed |
| Scoped Prettier check for the four changed TS/TSX files | Passed |
| `npx --no-install playwright test e2e/release/workspace-creation-policy.spec.ts e2e/release/workspace-create-denied.spec.ts --project=chromium --list` | 22 cases collected: 14 policy + 8 invitation/refusal |
| `git diff --check` | Passed |

The browser run was attempted with `E2E_WEB_PORT=3217`,
`E2E_SALES_WEB_PORT=3218`, `NEXT_TELEMETRY_DISABLED=1`, both specs, and
`--project=chromium --workers=1 --retries=0 --max-failures=1`. Next's development
server could not start: `uv_interface_addresses` returned system error 1; the run
exited 1 after its configured 120-second server timeout, before browser tests ran.
The configured Playwright Chromium executable is also absent. No local browser,
axe or screenshot pass is claimed. Existing `result.json`, axe JSON and screenshots
in this directory are historical artifacts, not evidence for this correction.

Exact final commit/tree mapping is returned to the coordinator. Independent
review and fresh push/pull-request build plus web-release-e2e on that final head
remain required before merge.
