# TC-14-001 acceptance evidence

Synthetic data only. The showcase and these artifacts contain no credentials or customer content.

## Latest run

Tested commit: `75e565a702f60f7ec838bae451cadf0839ddc032` on branch `tc/web/TC-14-001`.

That commit includes the master merge (`a12d1aae18bfcdf15066c906ed4dc5cc923f9605`, master `f72def39245abf5cb46c7b3693f687114fa4b1b5`) and the coordinator follow-up: dark stays the default, and Inter 4.1 is self-hosted. This evidence note was added in the following commit and does not change the suite.

### Environment

- OS: Linux 6.12.94+ x86_64
- Node: v22.23.4
- npm: 10.9.9
- Next.js: 14.2.15
- Vitest: 2.1.9
- Playwright: 1.58.2 (`apps/web/node_modules`)
- Chromium: Playwright build chromium-1208
- @axe-core/playwright: 4.14.0
- Working directory: `apps/web`

### Commands and results

```bash
cd apps/web
npm run test:unit
```

- Exit status: 0
- Test files: 2 passed
- Tests: 15 passed, 0 failed, 0 skipped
- Includes `lib/font-host.test.ts` (bundled OFL files, no third-party font host in shipped source, system fallback stack)

```bash
cd apps/web
npx playwright test e2e/release/design-tokens.spec.ts
```

- Exit status: 0
- Tests: 4 passed, 0 failed, 0 skipped
- Themes: dark and light
- Viewports: 360, 768 and 1440 CSS px
- Axe (`#token-showcase`): 0 violations at each theme and viewport (`axe-*.json`)
- Focus: keyboard Tab reaches the primary action; 2px focus ring; contrast at least 3:1 against the page surface and the primary glow
- Reduced motion: interaction duration computes to 0s
- Unknown `theme` query: default dark tokens remain
- Fonts: each navigation requested only same-origin `.woff2` files. No request to a third-party font host. Computed body font-family includes Inter, and `--tc-font-sans` keeps the system fallback stack.

Screenshots were refreshed after Inter started loading from the bundle: `artifacts/acceptance/TC-14-001/screenshots/theme-{dark,light}-{360,768,1440}.png`.

No required test was skipped.

## Earlier runs

- Implementation commit `ba53f8f0e7e6e46714493d89c1afd755117e3873`: unit 13 passed, Playwright 4 passed.
- Merge commit `a12d1aae18bfcdf15066c906ed4dc5cc923f9605`: the same two commands were re-run and passed with those totals. Screenshot bytes were unchanged on that run.
