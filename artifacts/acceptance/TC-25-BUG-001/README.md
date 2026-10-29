# TC-25-BUG-001 verification

Base: `8f41a9715c38cec09d767a16e6a31003a30ef8b0`. The coordinator records the local/published tree identity and final CI head in #85 and the PR. No completion claim relies on an older head.

The new test file renders the real DemoProofPage with controlled fetch responses and an injected workspace context. Response-body completions are held separately from fetch resolution; HTTP and network failures are tested separately. Tests assert visible summary/error state and current loading/saving controls rather than implementation details.

| Check | Result |
| --- | --- |
| New regression against unchanged page | 16 expected failures; 2 current-error cases passed |
| New regressions plus existing action confirmation suite | 27 passed |
| Full `npm run test:unit` | 208 passed, 30 files |
| `npm run lint` | exit 0 |
| `npm run typecheck` | exit 0 |
| `npm run format:check` | exit 0 |
| `npm run build` | exit 0 |
| `git diff --check` | exit 0 |
| Browser | unavailable: installed Playwright Chromium executable is absent |

Commands ran under Node24.22.1/npm11.9.0 with the repository's existing dependency installation. The initial build rejected a node_modules symlink outside Turbopack's workspace root. Copying that unchanged installation into this isolated worktree resolved the environment issue; the normal production build then passed. No dependency or build configuration change was made. Existing npm proxy-environment and Vite configuration warnings were not suppressed.

```sh
npm run test:unit -- tests/unit/demo-proof-requests.test.ts
npm run test:unit -- tests/unit/demo-proof-requests.test.ts tests/unit/action-confirmation.test.ts
npm run test:unit
npm run lint
npm run typecheck
npm run format:check
npm run build
```

No demo-proof browser spec exists in the current e2e tree. The real-component race regressions run in the existing unit gate. Required browser release CI remains a merge gate; no local browser pass, live provider qualification or overall TC-25-011 completion is claimed.
