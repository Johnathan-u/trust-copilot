# TC-12-001 local evidence

The existing first-answer and bulk routing repair is implemented at `1e5614a999202c2de9e3a72b505c08fabcf7216d`, based on actual master `5928f061e2967e9ca717879b0517a66f22f4d6c2`. [Release notes](../../../docs/release/tickets/TC-12-001.md) define the precise error/atomicity contract and remaining dependency gates. [verification.json](verification.json) records the actual commands, local results, failure controls and limitations.

All 67 local SQLite cases pass using real HTTP handlers and stored session/membership authorization. The same 67 cases are collected for migrated PostgreSQL. Required PostgreSQL mode exits 3 because the local service refuses connections; no PostgreSQL acceptance or future CI pass is claimed. Independent review and exact-head CI remain pending.
