# TC-06-002d retrieval authorization evidence

This is fresh evidence from reconstruction after the runtime snapshot lost the
previous unpublished commits. Base: `8f0cc07872057007d635e7bee17687f5fadc696b`.
The [claim](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6515017225)
limits the repair to current document-parent eligibility in retrieval.

The local SQLite suite demonstrates the defect and repair with actual stored
membership/session authentication and FK-enforced rows. Synthetic vectors use
the existing vector type. PostgreSQL tests are collected but remain unexecuted
locally: required mode exits 3 because localhost:5432 refuses connections.

The unchanged-source baseline produced 20 failing and 10 passing local cases.
The repaired suite passes all 30. Five deliberately removed/replaced predicates
each cause an assertion failure. Collection lists all 71 cases. Six existing
local retrieval/vector checks and 29 collection-safety checks pass. A broader
legacy selection also records one PostgreSQL setup error alongside six passes.

Full-row snapshots cover 18 relevant tables before/after reads and owned-ID
cleanup. No database, auth, SQL, pgvector or provider mocks substitute for the
required PostgreSQL cases. All source mutations used for negative controls were
restored. `verification.json` records the new code commit, blob identities,
commands and unresolved gates. Full parent tickets remain open. Publication and
merge are coordinator-owned and have not been performed by this worker.
