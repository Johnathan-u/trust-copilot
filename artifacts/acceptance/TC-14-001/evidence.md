# TC-14-001 acceptance evidence

Synthetic data only. The showcase and these artifacts contain no credentials or customer content.

## Latest run (2026-11-06)

Product commit: `2cfe041682ed1636bb4ac9a0c5dc53980b21de3f` (`origin/master`).

The token sources, showcase, shared controls, screenshots, and axe JSON on that commit were re-run in place. `git diff` for the screenshots and axe JSON was empty after the spec. The transcript for this run is `artifacts/acceptance/TC-14-001/verify-2026-11-06/`. This note does not change the suite.

### Environment

- OS: Linux 6.12.113+ x86_64
- Node: v24.22.1 (`apps/web/.nvmrc`)
- npm: 11.19.1
- Next.js: 16.4.3
- TypeScript: 6.0.3
- ESLint: 10.13.0
- Prettier: 3.9.10
- Vitest: 5.0.5
- Playwright: 1.64.1
- Chromium: Playwright build chromium-1248
- @axe-core/playwright: 4.14.0
- Working directory: `apps/web`
- Observation time: 2026-11-06T19:01:25Z

### Commands and results

```bash
cd apps/web
npm ci --ignore-scripts --no-audit --no-fund
npm run test:unit
npx playwright test e2e/release/design-tokens.spec.ts --retries=0
```

| Command | Exit | Totals |
| --- | --- | --- |
| `npm ci --ignore-scripts --no-audit --no-fund` | 0 | 399 packages |
| `npm run test:unit` | 0 | 47 files, 441 passed, 0 failed |
| `npx playwright test e2e/release/design-tokens.spec.ts --retries=0` | 0 | 4 passed, 0 failed, 0 skipped |

Playwright covered dark and light at 360, 768 and 1440. Axe on `#token-showcase` reported 0 violations at each theme and viewport, so no critical or serious violation remains. The spec tabs to the primary action and checks a 2px focus outline at 3:1 against the page surface and the primary glow. Reduced motion still computes to 0s. An unknown `theme` query keeps the default dark tokens. Font files stay on the page origin.

The dev server printed a hydration warning because `data-theme` is applied on `<html>` before hydration. The assertions passed.

No required test was skipped. Source hashes are `verify-2026-11-06/tested-inputs.sha256`. Those hashes are the re-check of `2cfe041` before the review follow-up.

The review follow-up moves `RegistryListPrimitives.tsx`, `RegistryRowActionsMenu.tsx`, and `Skeleton.tsx` onto existing tokens. `tests/unit/ui-raw-palette.test.ts` keeps raw palette classes and rgba colours out of `components/ui`. `apps/web/app/dashboard` is still in the TC-14-001 spec and still has about 320 raw palette classes across 22 files. Those dashboard classes must move to tokens in follow-up PRs, with a test that keeps them out. AC2 is not narrowed. This PR is progress toward AC2. The ticket stays open until a test shows no raw palette classes in both `components/ui` and `app/dashboard`. This evidence does not migrate `apps/web/app/dashboard`.

## Earlier run (implementation branch)

Tested commit: `556c7a3c9a8f86d464af545d4399f585d138e475` on branch `tc/web/TC-14-001`.

That commit merges `origin/master` at `a64db44c2e467f6f92f62eef1e80f926f5b66dbf` (TC-02-006 lockfile #9 and web-quality gates #10). This evidence note was added in the following commit and does not change the suite.

### Environment

- OS: Linux 6.12.94+ x86_64
- Node: v24.22.1 (`apps/web/.nvmrc`)
- npm: 11.19.1
- Next.js: 16.4.3
- TypeScript: 6.0.3
- ESLint: 10.13.0
- Prettier: 3.9.10
- Vitest: 5.0.5
- Playwright: 1.64.1
- Chromium: Playwright build chromium-1248
- @axe-core/playwright: 4.14.0
- Working directory: `apps/web` for the web gates, repo root for pytest

### Commands and results

```bash
cd apps/web
npm run lint
npm run format:check
npm run typecheck
npm run test:unit
npm run build
npm audit --omit=dev --audit-level=high
npx playwright test e2e/release/design-tokens.spec.ts
```

```bash
TC_REQUIRE_WEB_TOOLCHAIN=1 python3 -m pytest --noconftest \
  apps/api/tests/release/test_web_quality.py \
  apps/api/tests/release/test_web_lock.py -q
```

| Command | Exit | Totals |
| --- | --- | --- |
| `npm run lint` | 0 | eslint `.` with `--max-warnings=0` |
| `npm run format:check` | 0 | all matched files formatted |
| `npm run typecheck` | 0 | `next typegen` and `tsc --noEmit` |
| `npm run test:unit` | 0 | 10 files, 91 passed, 0 failed, 0 skipped |
| `npm run build` | 0 | Next.js 16.4.3 production build |
| `npm audit --omit=dev --audit-level=high` | 0 | 0 vulnerabilities |
| `npx playwright test e2e/release/design-tokens.spec.ts` | 0 | 4 passed, 0 failed, 0 skipped |
| pytest web quality and lockfile release tests | 0 | 44 passed |

Playwright covered dark and light at 360, 768 and 1440. Axe on `#token-showcase` reported 0 violations at each theme and viewport. Font files were requested from the page origin only. Reduced motion still computes to 0s. An unknown `theme` query keeps the default dark tokens.

Screenshots were refreshed on this run: `artifacts/acceptance/TC-14-001/screenshots/theme-{dark,light}-{360,768,1440}.png`.

No required test was skipped. The pytest release files above do not use the API conftest, database, or network.

## Earlier runs

- `ba53f8f`: unit 13 passed, Playwright 4 passed, on Node 22 before TC-02-006.
- `a12d1aa`: same totals after the earlier master merge (`f72def3`).
- `75e565a`: unit 15 passed and Playwright 4 passed after self-hosting Inter, still on Node 22.
