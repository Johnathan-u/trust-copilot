# TC-02-006b acceptance evidence

`react-hooks/set-state-in-effect` is an error in `apps/web`, and the findings on the branch base are fixed.

- **Base counted:** `ebfbde94befca714adcae99590754cef7d5c7a84`
- **Environment:** Linux, Node v24.22.1, npm 11.19.1
- **Data:** synthetic only. No credentials and no production hosts.

## Counts

|                        | Findings | Files | Lint exit                          |
| ---------------------- | -------- | ----- | ---------------------------------- |
| Before (`before.json`) | 39       | 31    | rule forced to error for the count |
| After (`after.json`)   | 0        | 0     | 0                                  |

## Commands

| Command (cwd `apps/web` unless noted)                                                                | Exit | Result                                                                                                                                          |
| ---------------------------------------------------------------------------------------------------- | ---- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `npx eslint . --rule 'react-hooks/set-state-in-effect: error' --format json` on the base             | 1    | 39 findings in 31 files                                                                                                                         |
| `npm run lint`                                                                                       | 0    | 0 errors, 0 warnings                                                                                                                            |
| `npm run format:check`                                                                               | 0    | formatted                                                                                                                                       |
| `npm run typecheck`                                                                                  | 0    | 0 type errors                                                                                                                                   |
| `npm run test:unit`                                                                                  | 0    | 22 files, 150 passed, 0 failed, 0 skipped                                                                                                       |
| `npm run build`                                                                                      | 0    | Next.js 16.4.3                                                                                                                                  |
| Release Playwright specs on this base, `--retries=0`, plus `scripts/ci/check-release-e2e-report.mjs` | 0    | 35 passed (design-tokens 4, responsive-shell 8, dialog-toast 8, settings-access 3, state-components 9, drawer-followups 3). Axe checker exit 0. |

The release specs rewrite other tickets' axe JSON. Those files were restored from a copy taken before the run and are not part of this change.
