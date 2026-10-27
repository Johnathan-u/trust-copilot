# TC-14-003a acceptance evidence

Synthetic data only. The showcase, screenshots and axe output contain no credentials, customer documents or personal data.

## Latest run

Tested commit: `d8bd51a7a312457fb0c059c2445f7a43a209812b` on branch `tc/web/TC-14-003a`.

That commit is the first implementation. This note was refreshed after merging master `301a1a5` (PR #44 and PR #15) and enabling the release specs in CI. The refresh does not change the suite. `web-release-e2e` keeps `permissions: contents: read` and `persist-credentials: false`.

### Environment

- OS: Linux 6.12.94+ x86_64
- Node: v24.22.1 (`apps/web/.nvmrc`)
- npm: 11.19.1
- Next.js: 16.4.3
- Vitest: 5.0.5
- Playwright: 1.64.1 (`apps/web/node_modules`)
- Chromium: Playwright build chromium-1248
- @axe-core/playwright: 4.14.0
- Working directory: `apps/web`
- Install: existing `npm ci --ignore-scripts` tree. No lockfile change.

### Commands and results

```bash
cd apps/web
npm run lint
npm run format:check
npm run typecheck
npm run test:unit
npm run build
npm audit --omit=dev --audit-level=high
```

- Each exit status: 0
- Unit test files: 15 passed
- Unit tests: 105 passed, 0 failed, 0 skipped
- Includes `lib/toast.test.ts` (one persistent polite region and one assertive region) and `lib/destructive-confirm.test.ts`
- Audit: 0 vulnerabilities

```bash
cd /workspace
python3 scripts/security/secret_inventory.py tree --root .
pre-commit run --all-files
ruff check apps/api
TC_REQUIRE_WEB_TOOLCHAIN=1 python3 -m pytest apps/api/tests/release/test_web_quality.py -q --noconftest
```

- Secret tree-scan exit status: 0 (`block` 0)
- pre-commit exit status: 0
- `ruff check apps/api` exit status: 0
- Web quality tests: 26 passed, including the runtime-module coverage check

```bash
cd apps/web
npx playwright test e2e/release/design-tokens.spec.ts e2e/release/responsive-shell.spec.ts e2e/release/dialog-toast.spec.ts --retries=0
```

- Exit status: 0
- Tests: 20 passed, 0 failed, 0 skipped (design-tokens 4, responsive-shell 8, dialog-toast 8)
- Duration: 56.3s
- No required test was skipped
- Axe violationCount 0 in TC-14-001 (6 reports), TC-14-006 (14 reports) and TC-14-003a (18 reports)

The report checker was run locally against a temporary report. A missing `dialog-toast` spec exited 1. A fake `color-contrast` violation exited 1. Those fixtures were deleted. The same checker then exited 0 against the axe JSON these specs wrote.

The spec checks that `#tc-toast-status` and `#tc-toast-alert` are in the DOM and empty before a toast fires. "Show status" puts "Synthetic status saved." in the polite region only. "Show error" puts "Synthetic error stayed on screen." in the assertive region only. "Reject sample" opens an alertdialog, "Remove sample" rejects `onConfirm`, the dialog closes, focus returns to "Reject sample", and the assertive region shows "Synthetic delete was rejected." That error is still present after 4500ms.

Axe (`#dialog-showcase` and `#tc-toast-live`): 0 violations for dialog+status, alertdialog+error, and error toast alone, in dark and light, at 360, 768 and 1440 CSS px. Reports: `axe-{dialog,confirm,toast}-{dark,light}-{360,768,1440}.json` (18 files, each `violationCount` 0, each ending with a newline).

Screenshots: `artifacts/acceptance/TC-14-003a/screenshots/{dialog,confirm}-{dark,light}-{360,768,1440}.png`.
