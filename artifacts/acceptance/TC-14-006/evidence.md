# TC-14-006 acceptance evidence

Synthetic data only. The shell, login, and these artifacts contain no credentials or customer content. The signed-in fixture is `synthetic.reviewer@example.com` in Synthetic Workspace.

This file records a screenshot and axe refresh. It does not accept the ticket.

## Current CI

Tested commit `de5d7c11d9f545525994ab3029dd1edb200ff40e` on branch `tc/TC-14-006-fresh-evidence`.

That commit attaches each screenshot to the Playwright report and uploads the PNGs. This evidence note and the refreshed PNGs were added in the following commit and do not change the suite or the shell.

Committed PNGs were downloaded from the push run's `responsive-shell-screenshots` artifact. They were not rendered locally. The pull_request run of the same commit also uploaded that artifact.

### Runs

Both conclusions are success.

- push: https://github.com/Johnathan-u/trust-copilot/actions/runs/42922310461
  - `build` job 130199945865
  - `web-release-e2e` job 130199946227
- pull_request: https://github.com/Johnathan-u/trust-copilot/actions/runs/42922327515
  - `build` job 130200003074
  - `web-release-e2e` job 130200002731

### Environment

Printed by the `Frontend tool versions` step on both `web-release-e2e` jobs:

- Node: v24.22.1
- npm: 11.19.1
- Playwright: 1.64.1
- Chromium: Playwright build chromium-1248 (Chrome for Testing 156.0.8078.4), the browser pinned by Playwright 1.64.1. The install step restored the browser cache and did not print a version line.
- Runner: GitHub-hosted `ubuntu-latest`
- Working directory: `apps/web`

### `responsive-shell.spec.ts`

Both `web-release-e2e` jobs printed:

```text
responsive-shell.spec.ts: 8 passed, 0 failed, 0 skipped, 0 flaky
```

### Axe

The checker deleted the committed `axe-*.json` files and read the copies the spec wrote. Both jobs printed 0 violations for all 14 files, then `axe violations: 0` and `playwright exit 0; axe check exit 0`.

- `TC-14-006/axe-auth-dark-1440.json`: 0 violations
- `TC-14-006/axe-auth-dark-360-closed.json`: 0 violations
- `TC-14-006/axe-auth-dark-360-open.json`: 0 violations
- `TC-14-006/axe-auth-dark-768.json`: 0 violations
- `TC-14-006/axe-auth-light-1440.json`: 0 violations
- `TC-14-006/axe-auth-light-360-closed.json`: 0 violations
- `TC-14-006/axe-auth-light-360-open.json`: 0 violations
- `TC-14-006/axe-auth-light-768.json`: 0 violations
- `TC-14-006/axe-public-login-dark-1440.json`: 0 violations
- `TC-14-006/axe-public-login-dark-360.json`: 0 violations
- `TC-14-006/axe-public-login-dark-768.json`: 0 violations
- `TC-14-006/axe-public-login-light-1440.json`: 0 violations
- `TC-14-006/axe-public-login-light-360.json`: 0 violations
- `TC-14-006/axe-public-login-light-768.json`: 0 violations

Screenshots: `artifacts/acceptance/TC-14-006/screenshots/`. Shell captures are 360 closed, 360 open, 768, and 1440 in dark and light. Public login captures are dark and light at 360, 768, and 1440. The same artifact also replaced the public home and onboarding 360px captures.

## Historical record (2026-10-29)

The section below is the previous evidence, kept unchanged. Its screenshots were last regenerated in `5ec7bbe`. Its tested commit is not the current shell.

## Tested commit

`abafb2990351ebcfb50c9b9e3d6108cf03cd25f7` on branch `tc/web/TC-14-006`.

That commit is the tree the checks ran against. This evidence note was added in the following commit and does not change the suite. The branch contains merge commit `abafb29`, which brings in master `58b8c87` (TC-14-003).

## Environment

- OS: Linux 6.12.94+ x86_64
- Node: v24.22.1 (`apps/web/.nvmrc`, engines `>=24.11.0 <25`)
- npm: 11.19.1
- Next.js: 16.4.3
- Vitest: 5.0.5
- Playwright: 1.64.1 (`apps/web/node_modules`)
- Chromium: Playwright build chromium-1248
- @axe-core/playwright: 4.14.0
- Working directory: `apps/web`
- Dev server: `next dev` on 127.0.0.1:3000, API upstream not running
- Auth: synthetic `tc_session` cookie; `/api/**` fulfilled in the browser

## Commands and results

### Unit

```bash
cd apps/web
npm run test:unit
```

- Exit status: 0
- Test files: 14 passed
- Tests: 102 passed, 0 failed, 0 skipped

### Playwright and axe

```bash
cd apps/web
npx playwright test e2e/release/responsive-shell.spec.ts --retries=0
```

- Exit status: 0
- Tests: 8 passed, 0 failed, 0 skipped
- Viewports: 360, 768, and 1440 CSS px, plus 720×450 as 200% of 1440
- Axe: 0 violations on the authenticated shell (dark and light, including the mobile drawer open and closed) and on `/login` (dark and light at 360, 768, and 1440)
- Keyboard: skip link, docked link activation, drawer Tab wrap, section `aria-expanded`, Escape, and focus return to Open navigation
- `aria-current="page"` on the active sidebar and primary links
- No page-level horizontal overflow. At 360px the main region stays wider than 300px with the drawer open or closed
- Marketing home and onboarding: no page-level horizontal overflow at 360px

Screenshots: `artifacts/acceptance/TC-14-006/screenshots/`.

No required test was skipped.

## Other gates

Run on Node 24 against the same tree, all exit 0:

- `python scripts/security/secret_inventory.py tree --root .` (0 block findings)
- `npm run lint`
- `npm run format:check`
- `npm run typecheck`
- `npm run build`
- `npm audit --omit=dev --audit-level=high` (0 vulnerabilities)
- `pre-commit run --all-files`
- `TC_REQUIRE_WEB_TOOLCHAIN=1 python3 -m pytest tests/release/test_web_quality.py tests/release/test_web_lock.py --noconftest` (44 passed)
