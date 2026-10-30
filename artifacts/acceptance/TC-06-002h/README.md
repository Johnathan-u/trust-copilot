# TC-06-002h evidence

Manual retry now checks explicit workspace and current active parent references
before writes, using the existing reference guard and neutral missing-job outcome.

- [Ruling, scope and acceptance matrix](../../../docs/release/tickets/TC-06-002h.md)
- [Commands, source identities, results and remaining gates](verification.txt)

SQLite red/green and real stored-auth controls qualify the bounded local change.
Migrated PostgreSQL, independent review and required exact-head CI remain pending.
No worker/provider execution or full-parent acceptance is claimed.
