# TC-02-006b acceptance evidence

`react-hooks/set-state-in-effect` is an error in `apps/web`, and the findings on the branch base are fixed.

- **Base counted:** `ebfbde94befca714adcae99590754cef7d5c7a84`
- **Implementation commit:** `433b69e8134683dbab85f9c655d8ffed6588235b`
- **Merged master:** `a53dc7c2661cfc6253f9dc4a16231b33fe1bce4a` (pure merge `85c20161097bd9c37fd15c5a86116f0e55dbab50`, no conflicts)
- **Environment:** Linux, Node v24.22.1, npm 11.19.1
- **Data:** synthetic only. No credentials and no production hosts.

## Counts

|                        | Findings | Files | Lint exit                          |
| ---------------------- | -------- | ----- | ---------------------------------- |
| Before (`before.json`) | 39       | 31    | rule forced to error for the count |
| After (`after.json`)   | 0        | 0     | 0                                  |

## Commands

| Command (cwd `apps/web` unless noted)                                                        | Exit | Result                                                                                                                                                                     |
| -------------------------------------------------------------------------------------------- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `npx eslint . --rule 'react-hooks/set-state-in-effect: error' --format json` on the base     | 1    | 39 findings in 31 files                                                                                                                                                    |
| `npm run lint`                                                                               | 0    | 0 errors, 0 warnings                                                                                                                                                       |
| `npm run format:check`                                                                       | 0    | formatted                                                                                                                                                                  |
| `npm run typecheck`                                                                          | 0    | 0 type errors                                                                                                                                                              |
| `npm run test:unit` after the master merge                                                   | 0    | 24 files, 164 passed, 0 failed, 0 skipped                                                                                                                                  |
| `npm run build`                                                                              | 0    | Next.js 16.4.3                                                                                                                                                             |
| Release Playwright specs after the master merge, `--retries=0`, plus the release e2e checker | 0    | 43 passed (design-tokens 4, responsive-shell 8, dialog-toast 8, settings-access 3, state-components 9, drawer-followups 3, workspace-create-denied 8). Axe checker exit 0. |

The release specs rewrite other tickets' axe JSON. Those files were restored from a copy taken before the run and are not part of this change.
