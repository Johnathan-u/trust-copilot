# TC-06-002f local acceptance evidence

Frozen basis: TC-06-002 AC1/AC2, `PRODUCT_SPEC.md`'s indirect-object authorization
requirement, and the foreign-reference acceptance in TC-12-012. This child covers
only confidence-routing object reads; tenant-owned settings and other workflow
contracts remain separate.

The regression suite executes the actual three routers with expiring signed
cookies, stored sessions/users/memberships, current membership changes and real
SQL. Only the database dependency points to fixture-owned storage. Authorization,
parent lookup and routing are not replaced. One explicit fault case raises during
the parent SELECT and requires a 500 without answer metadata instead of falling
through to the service.

There are 92 collected cases: 46 SQLite and 46 migrated PostgreSQL. The original
implementation failed 18 cases while 28 controls passed. After adding the existing
parent guard, all 46 SQLite cases pass. Each request preserves full-row hashes for
12 tables and executes only SELECT statements. A 404 must occur before any answer
query, proving that a mixed batch cannot start projecting its authorized prefix.
Cleanup deletes only IDs inserted by this fixture and restores every baseline
row. Foreign keys and PostgreSQL triggers are never disabled.

Independent negative controls remove the individual question guard, remove the
queue guard, or authorize only the first batch ID. Each makes its focused real-HTTP
foreign-reference assertion fail. The exact implementation was restored afterward.

Removing the four added production lines reproduces the entire original router.
The shared helper and service remain byte-identical. Valid routing results,
thresholds, permission dependencies, empty batches and repeated IDs are preserved.

See `verification.txt` for actual checks and remaining gates. Local SQLite is
control-path evidence, not PostgreSQL qualification. No generation, model, storage,
external provider or publication action was performed. Independent review and both
standard push/PR jobs on the final published head remain required.
