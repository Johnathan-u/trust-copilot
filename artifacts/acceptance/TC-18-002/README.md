# TC-18-002 backend acceptance evidence

Backend implementation only. AC3 UI qualification belongs to TC-15-024 after #86 merges; the full public response form belongs to TC-18-003. No live provider or frontend qualification is claimed here.

## Verified code

Code commit `8b5aa49fd2e9b4b17f261d4186e657482ef4f323` passed all four required checks: push run `40930132447` and PR run `40930145535`. Push build `123646048133` passed **3295 backend tests, 1 external-data skip** (the unprovided blind scoring pack). This includes post-claim permission changes, hash-only grants, expiry/revocation, final-submit replay, durable send intent and post-send failure, idempotency owner fencing, lossless migration data and disabled legacy grants while downgraded. Build, web-release-e2e, collection, locks, migrations and lint passed.

Independent review found two issues in the prior implementation: authorization needed rechecking after idempotency's commit, and dropping expiry/revocation columns could reopen old raw grants. Commit `c8392209d04b121eac226fa1ae71097cf0da202b` fixes both. Root independently reread these fixes and the separate sensitive SMTP commit with no remaining blocker, and ran 17 selected checks successfully.

Sensitive SMTP is its own approved commit `05706418b38b43be55270b8231a82601dcee1aa7` (tree `db8b9738549c8f8d8daec8d65bfd01aa9ef2e584`). Four synthetic cases failed before implementation; all five transport tests then passed. Sensitive failures disclose only exception class and a random message id in every environment; default behavior is unchanged. #88 consumes this change after #86 merges.

## Landing update

Coordinator ruling #85 comment `6505384313` opens migration slot 2. Current master `80607881320e1fa2c6416c55730eb98a56449f26` was merged without conflicts; `git merge-tree` reproduced tree `f20ae72ac08bfff6e4f3e81813b23a4e36072895` exactly. The migration parent changed separately to `tc02001a_parent_ws_move`; the only resulting head is `tc18002_vendor_lifecycle`. A separate test-only change makes the touched Wave3 vendor-admin fixture remove its own user/membership rows and assert restored counts.

After this merge/parent update, local checks passed **56 tests, 69 database tests deselected**:

```sh
PYTHONPATH=. python -m pytest -q tests/release/test_sensitive_smtp.py tests/release/test_openapi_ticket_ids.py tests/release/test_safe_collection.py tests/release/test_domain_vendor_requests.py -k 'not domain or schema or before_database_access'
python -m alembic heads
python -m alembic upgrade tc02001a_parent_ws_move:tc18002_vendor_lifecycle --sql
```

Offline SQL rendering and Ruff/diff checks passed. Final exact-head CI for this landing update is pending; its head and result will be posted on #85. No self-merge is authorized.

## Regression history and environment

- Initial RED `717b6968c17749f33717ab69a1a58925bce3c92f`: run `40919867412`, build `123609857229`, 5 intended failures, 3183 passed and 1 external skip.
- Extended RED `6ffbc91e81a346042e334def38620c520078184b`: run `40923565341`, build `123622965016`, 35 failed, 3228 passed and 1 skip. Missing lifecycle/current membership behavior dominated. A deleted-ORM-ID cleanup bug and an outdated empty-email assertion were also corrected.
- Full initial implementation `ca0fdb1982e2f500e80c4869d7014d6be21ea09f`: run `40926364745`, build `123632828108`, 3275 passed and 1 skip. Subsequent independent review strengthened the contract as described above.
- `13dec51` stopped before database tests at safe collection: its synthetic SMTP fixture lacked the scanner's recognized test prefix. The fixture-only correction uses `test-only`; safe collection plus transport checks then passed all 34 locally.

Local runtime is Python 3.12 with the repository's locked dependencies. PostgreSQL is unavailable locally; `local-db-attempt.txt` records that environment failure, not a behavior RED. CI provisions the pinned PostgreSQL 16/pgvector container and Python 3.11. The final acceptance command is `TC_REQUIRE_DB=1 python -m pytest tests/release/test_domain_vendor_requests.py -q`, exercised as a subset of the required full CI suite. Raw early schema/route regression diagnostics and local isolated GREEN are retained alongside this file.
