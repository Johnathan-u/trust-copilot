# TC-18-001 evidence in progress

This initial revision contains regression tests, not a completion claim. Local locked Python3.12 runtime is available, but PostgreSQL is absent. Pure schema cases can run locally; database tests require the existing repository CI and its pinned pgvector16 container. No required database test is claimed as passing or silently skipped.

Scope: bounded intake, tenant/permission boundaries, read-only GET and attachment failure honesty. Full reviewed reply/delivery persistence awaits Coordinator migration scheduling on #85. Live provider and frontend consumer qualification remain open.
