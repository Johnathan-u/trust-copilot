# TC-06-003f evidence

Proof-graph freshness and chain traversal now enforce current source/node
workspace authority and active chain-root eligibility.

- [Ticket and matrix](../../../docs/release/tickets/TC-06-003f.md)
- [Source identities, commands and actual outcomes](verification.json)

Local SQLite: 69 cases passed. Seven isolated negative controls detect their
intentional regressions. PostgreSQL was unavailable; 69 new and six existing
database cases still require execution, independent review and exact-head CI.

Snapshot/history retention, stable IDs, atomic rebuild and authoritative-byte
hashing remain under TC-23-004. Full authorization parents remain open.
