# TC-14-006 acceptance evidence

Synthetic data only. The shell, login, and these artifacts contain no credentials or customer content. The signed-in fixture is `synthetic.reviewer@example.com` in Synthetic Workspace.

## Tested commit

`49a2f065f401c8d0d55d1c8938b2a03a93723f15` on branch `tc/web/TC-14-006`.

That commit is the tree the checks ran against. This evidence note was added in the following commit and does not change the suite.

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
- Dev server: `next dev` on 127.0.0.1:3000, API upstream not running
- Auth: synthetic `tc_session` cookie; `/api/**` fulfilled in the browser

## Commands and results

### Unit

```bash
cd apps/web
npm run test:unit
```

- Exit status: 0
- Test files: 2 passed (`lib/app-navigation.test.ts`, `lib/design-tokens.test.ts`)
- Tests: 16 passed, 0 failed, 0 skipped

### Playwright and axe

```bash
cd apps/web
npx playwright test e2e/release/responsive-shell.spec.ts
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
