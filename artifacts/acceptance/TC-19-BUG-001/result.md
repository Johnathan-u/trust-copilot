# Response-size streaming limit evidence

Code and tests SHA: `e617c4ff0dc3afbf21f0a59976596f1e37239f80`.
Base: `5b97a33d0cd43d07ebba901901d5433d7725eb43`.

Environment: Linux, Python 3.12, the repository `requirements-dev.lock` installed with hashes; HTTPX 0.28.1, pytest 9.1.1, ruff 0.5.6. No PostgreSQL service, provider account, or live provider call. All new tests use `httpx.MockTransport` and a tracked synthetic byte stream.

## Verified local command

From `apps/api`, with the locked virtual environment on PATH:

```sh
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy PYTHONPATH=. python -m pytest tests/release/test_message_provider_response_limit.py tests/release/test_message_provider_wiring.py tests/release/test_safe_collection.py -q
```

Exit 0: **85 passed, 0 failed, 0 skipped**. Log: `pytest-local.txt`.

The new test file has 15 tests. Before the implementation change, on the base transport, it returned exit 1: 10 failed because the third response chunk was consumed, 5 passed. The same tests pass with the streaming limit.

Ruff `check` and `format --check` on the two implementation files and new test file: exit 0. `git diff --check`: exit 0. `scripts/security/secret_inventory.py paths` on changed files: exit 0, 0 blocking findings.

## Required CI verification

Adding `tests/release/test_notification_delivery.py` locally produced **85 passed and 22 setup errors**, exit 1. Every error reports `Postgres is required for TC-19-008; not skipping`; the local database service is unavailable. This is not a passing notification-delivery run. The existing full GitHub CI must pass on the PR head before Coordinator merge, including the PostgreSQL-backed suite. CI status remains pending here.

An initial provider-wiring attempt inherited SOCKS proxy environment variables and failed five provider-construction tests because optional `socksio` was absent. Clearing proxy variables restored the unchanged baseline and the final 85-test run. No dependency or production proxy setting was changed.

## Review and scope

An independent reviewer ran all 15 new tests and found no critical or important issues. Deferred minor: buffered response reconstruction does not retain HTTPX elapsed/download counters; existing provider consumers use neither. Status, headers, request, decoded JSON, error shape, and retry policy are preserved.

The cap applies to retained decoded body bytes and stops before the next decoded chunk. HTTPX may temporarily decompress one transport chunk beyond the cap; this is not a strict process-memory ceiling. No new decompressor or dependency is introduced.

No database rows, migrations, API routes, OpenAPI schemas, credentials, or provider scopes change. This proves transport control behavior only; it does not qualify a real Slack/Gmail sandbox integration.
