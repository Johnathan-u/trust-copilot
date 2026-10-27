# TC-14-001 acceptance evidence

Synthetic data only. The showcase and these artifacts contain no credentials or customer content.

## Tested commit

`ba53f8f0e7e6e46714493d89c1afd755117e3873` on branch `tc/web/TC-14-001`.

That commit is the tree the checks ran against, including the token showcase. This evidence note was added in the following commit and does not change the suite.

## Environment

- OS: Linux 6.12.94+ x86_64
- Node: v22.23.4
- npm: 10.9.9
- Next.js: 14.2.15
- Vitest: 2.1.9
- Playwright: 1.58.2 (`apps/web/node_modules`)
- Chromium: Playwright build chromium-1208
- @axe-core/playwright: 4.14.0
- Working directory: `apps/web`

## Commands and results

### Unit

```bash
cd apps/web
npm run test:unit
```

- Exit status: 0
- Test files: 1 passed
- Tests: 13 passed, 0 failed, 0 skipped

### Playwright and axe

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

Screenshots: `artifacts/acceptance/TC-14-001/screenshots/theme-{dark,light}-{360,768,1440}.png`.

No required test was skipped.
