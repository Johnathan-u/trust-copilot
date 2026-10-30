# TC-06-002g evidence

Individual answer create/upsert/PATCH now require a current active parent while
preserving existing foreign 403 responses and all reviewed #128 bulk behavior.

- [Ticket and matrix](../../../docs/release/tickets/TC-06-002g.md)
- [Source identities, commands and actual outcomes](verification.json)

Local SQLite: 91 new and 67 parent cases pass. Six isolated negative controls
detect removed/late parent guards and incorrect foreign-error ordering.
PostgreSQL was unavailable, so its 158 cases remain required. Independent review,
actual landed #128 integration and exact-head CI are still pending. Full
TC-06-001 and TC-06-002 remain open.
