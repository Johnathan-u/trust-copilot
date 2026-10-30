# TC-06-003d evidence

Acceptance-only tests preserve existing contract authorization. No production
defect was found or fixed; production, legacy tests and reference guards remain
unchanged.

- [Ticket and matrix](../../../docs/release/tickets/TC-06-003d.md)
- [Source identities, commands and outcomes](verification.json)

Local SQLite: 40 passed. Four isolated negative controls detected their
intentional regressions. PostgreSQL was unavailable; all 44 PostgreSQL cases and
four existing contract tests still require execution, review and exact-head CI.

The focused database qualification command, when the migrated test service is
available, is:

```sh
TC_REQUIRE_DB=1 python -m pytest tests/release/test_authorization_contracts.py tests/test_contracts.py -m integration -q
```

Run from `apps/api`. This command is a remaining qualification step, not a claim
that it has passed. Full TC-06-001 and TC-06-003 remain open.
