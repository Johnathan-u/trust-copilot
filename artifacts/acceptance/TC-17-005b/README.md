# TC-17-005b evidence

Local runs used Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, Alembic 1.20.1, and PostgreSQL 16.15, database `trustcopilot_test` at `127.0.0.1:5432`. Base before the fix: `05ca009fbca03a0993997a429e5a697cf3879065`.

| Run | Result |
| --- | --- |
| `pytest tests/release/test_tc17005b_space_scoping.py -q --tb=line` before the fix | 6 failed, 3 passed (`failing-before.txt`). Create stored a foreign article id. Update did not check asset ids. Token access returned a foreign id and a missing id. A listed download and a listed article read were not served. |
| The new file, the existing share tests, the deal-room token gate, the token migration, the NDA/share authorization suite, and the document list/content tests, after the fix | 218 passed (`passing-after.txt`). |
| `alembic heads` | `tc04007b_rate_buckets`. No new revision. |

CI run IDs for the exact head are on the pull request. This folder does not record them. This folder does not accept TC-17-005 or TC-17-005b.
