# TC-21-007b: Provenance ids on coverage recommendations

Implemented and pushed as PR #99. Framework catalogs stay **BLOCKED** pending **TC-01-007**. No migration. Schema stays `compliance-coverage-controls/v1`.

A recommendation with no live source stays in the response with empty id lists, so `title` and `improves_questions` do not disappear. The web consumer skips a malformed recommendation item and any malformed id entry.

## Command

Web, from `apps/web`:

```text
npx vitest run lib/coverageConsumer.test.ts
npm run typecheck
```

## SHA

Tests and the four CI checks ran on `6ce4170442c8193569d8355770a5e3f22c823ac4`. That commit was the branch head. This docs commit only changes docs.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| `coverageConsumer.test.ts` | 0 | 6 passed |
| `npm run typecheck` in `apps/web` | 0 | `tsc --noEmit` completed |

## CI

4/4 green on `6ce4170442c8193569d8355770a5e3f22c823ac4`.

| Event | Run | `build` | `web-release-e2e` |
| --- | --- | --- | --- |
| push | `40942497588` | success | success |
| pull_request | `40942505505` | success | success |

The API pytest on `395221f78fcd744d862a5795c76c10da25adb16c` was 47 passed, 94 warnings, 2.74s. It was not repeated for this web-only commit.
