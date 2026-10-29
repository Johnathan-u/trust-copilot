# TC-14-006a acceptance evidence

Synthetic data only. The shell, login, dialog sample, and these artifacts contain no credentials or customer content. The signed-in fixture is `synthetic.reviewer@example.com` in Synthetic Workspace.

## Tested commit

`530b28d6219c171b4d9ac332c95e09f658ec3c95` on branch `tc/web/TC-14-006a`.

That commit is the tree the checks ran against. This evidence note was added in the following commit and does not change the suite. The branch starts from master `a516c77`.

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

## Commands and results

### Unit

```bash
cd apps/web
npm run test:unit
```

- Exit status: 0
- Test files: 14 passed
- Tests: 103 passed, 0 failed, 0 skipped

### Playwright and axe

```bash
cd apps/web
npx playwright test e2e/release/responsive-shell.spec.ts e2e/release/dialog-toast.spec.ts --retries=0
```

- Exit status: 0
- Tests: 15 passed, 0 failed, 0 skipped
- Responsive shell: 8 passed
- Dialog and toast: 7 passed
- Axe: 0 violations

## Other gates

Run on Node 24 against the same tree, all exit 0:

- `python3 scripts/security/secret_inventory.py tree --root .` (0 block findings)
- `npm run lint`
- `npm run format:check`
- `npm run typecheck`
- `npm run build`
- `npm audit --omit=dev --audit-level=high` (0 vulnerabilities)
- `pre-commit run --all-files`
- `TC_REQUIRE_WEB_TOOLCHAIN=1 python3 -m pytest tests/release/test_web_quality.py tests/release/test_web_lock.py --noconftest` (44 passed)
