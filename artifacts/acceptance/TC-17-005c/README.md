# TC-17-005c evidence

Local API runs used Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, and PostgreSQL 16.15, database `trustcopilot_test` at `127.0.0.1:5432`. Web runs used Node 24.22.1. Base before the fix: `2661223227c67ce9f45bfb5dae2a4fb22ba1f31d`.

| Run | Result |
| --- | --- |
| `pytest tests/release/test_domain_shareable_spaces.py -q --tb=line` before the fix | 2 failed, 4 passed (`failing-before.txt`). A repeated create with the same Idempotency-Key inserted a second row. The workspace, permission, download, and published-version cases passed. |
| `npx vitest run tests/unit/share-page.test.ts` before `apps/web/app/share/page.tsx` existed | 1 failed suite. The page module could not be resolved. |
| The domain file after the fix | 6 passed, exit 0, no skip (`passing-after.txt`). One create is the same row on a retry and from a new Python process. |
| The existing share tests, the TC-17-005b file, the token migration, and the domain file | 60 passed. |
| Share page, dashboard page, and buyer-link unit tests | 12 passed. `npm run lint` exited 0. |
| `alembic heads` | `tc04007b_rate_buckets`. No new revision. |

The existing shareable-spaces page tests do not use axe, so the new page test does not add it.

This folder does not record CI run ids. This folder does not accept TC-17-005 or TC-17-005c.
