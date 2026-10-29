# TC-17-004 acceptance in progress

Regression-first stage on master `76ae791`. Local locked Python 3.12 pure-schema tests reproduced five failures (length bounds, NUL and blank content). PostgreSQL is unavailable locally, so no DB behavior result is claimed. The existing GitHub CI supplies pinned pgvector16 for required lifecycle, scope, permission, failure and migration tests.

No new dependency or live provider is used. Full acceptance requires exact-head CI, lossless migration round-trip and independent review. Evidence will be updated after implementation.
