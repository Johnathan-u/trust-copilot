# TC-04-007a local verification

Fresh reproduction and repair against master
`90146e0cfe2220beb3e43f98f6073262f7c0abfb`; recovered historical logs were used only
for diagnosis. The current test file and source identities are recorded in
[verification.json](verification.json).

The SQLite matrix went from 10 failures / 12 passes to 22 passes. It covers
unknown, unverified and verified accounts; user-bound proof, consumption, replay,
expiry and normalization; identical reset throttling and cooldown; and preserved
token, audit and session effects. Only the email transport is replaced by a local
outbox; real HTTP, SQL, proof hashing, rate limiting and mail construction run.

PostgreSQL is unavailable locally. The required full-suite attempt exited before
tests rather than treating missing PostgreSQL as qualification. All 22 PostgreSQL
variants, legacy regressions, independent review and exact-head push/PR CI remain
required. No full-parent acceptance or real-provider qualification is claimed.
