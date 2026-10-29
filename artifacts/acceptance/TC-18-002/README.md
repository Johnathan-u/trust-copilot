# TC-18-002 acceptance work in progress

No completion claim. The first commit adds regression tests before production changes, intended to fail on malformed recipient/message acceptance and cosmetic completion.

Local runtime: Python 3.12 with repository `requirements-dev.lock` installed. `TC_REQUIRE_DB=1 PYTHONPATH=. python -m pytest tests/release/test_domain_vendor_requests.py -q` could not run: no PostgreSQL server is available on localhost:5432. This is an environment failure, not a RED behavior result. The checked production base was `5b97a33d0cd43d07ebba901901d5433d7725eb43`. Raw diagnostic is `local-db-attempt.txt`.

The existing GitHub CI provisions the repository-pinned pgvector/PostgreSQL16 container. Its run and tested SHA will be recorded after the branch is published. Local ruff check/format, diff whitespace and changed-file secret scan passed.

Migration scheduling, public submission route ownership, frontend consumer qualification and real delivery qualification remain open in #85. No provider calls were made.
