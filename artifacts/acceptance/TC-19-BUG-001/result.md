# Response-size streaming limit evidence

Status: tested code has all four required CI checks green; Coordinator re-review pending. Any later evidence-only head remains draft until its own required CI checks pass. This replaces the first-pass evidence superseded by the decompression-bomb review.

Environment: Linux, Python 3.12, exact hashed requirements-dev.lock; HTTPX 0.28.1, pytest 9.1.1, ruff 0.5.6. No local PostgreSQL or provider network calls. All response fixtures are synthetic HTTPX raw streams.

## Regression evidence

On unchanged first-pass commit `f80aa2e3160cafc3d4dc53b27cf66bb749fb648e`, the strengthened 27-test module returned exit 1: **13 failed, 14 passed**. Failures covered excessive traced allocation for gzip bombs, nested/unsupported encodings, early declared-length rejection, redirect bodies, and accepting truncated gzip.

On exact published code SHA `718378a8d5c56fb945c1cf28c86b8fccd2d09422`, raw streaming with capped stdlib zlib decompression returned exit 0: **97 passed, 0 failed, 0 skipped** (27 response-limit, 41 provider-wiring, 29 safe-collection). The exact-head local run took 14.71 seconds; `pytest-local.txt` contains its output. Ruff check/format, diff check, and changed-path secret scan passed.

```sh
# From apps/api with the locked virtual environment on PATH:
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy PYTHONPATH=. python -m pytest tests/release/test_message_provider_response_limit.py tests/release/test_message_provider_wiring.py tests/release/test_safe_collection.py -q
```

The memory tests construct compressed fixtures before tracing and require allocation below 8 MiB while rejecting single/nested gzip representations of 32 MiB. The decoder limits each output allocation to the remaining body allowance plus one byte. An independent 16 MiB probe reported approximately 2.16 MB traced allocation, one raw chunk consumed, closure, and no retry.

## Required checks

On `718378a8d5c56fb945c1cf28c86b8fccd2d09422`, both [pull-request CI](https://github.com/Johnathan-u/trust-copilot/actions/runs/40922859237) and [push CI](https://github.com/Johnathan-u/trust-copilot/actions/runs/40922849081) completed successfully. Both `build` and `web-release-e2e` passed in each run: all four required checks green. The build includes PostgreSQL-backed API tests in the pinned pgvector16 CI service. This records the tested code SHA; the evidence-only follow-up head and its CI results are recorded in the PR/coordination thread to avoid a self-referential commit hash. Local inclusion of `test_notification_delivery.py` produced 22 setup errors because PostgreSQL was unavailable; those are not passes. Initial inherited SOCKS proxy settings caused five provider-construction failures; clearing test proxy variables restored baseline behavior without adding a dependency or changing production proxy settings.

## Review scope

The Coordinator's bounded-decompression requirement is implemented. Nested or unsupported encoding is rejected before body consumption. Raw DEFLATE is rejected; gzip and zlib-wrapped compressed responses follow the prescribed `wbits=47` behavior. Incomplete or trailing compressed data fails nonretryably. Redirects are classified before reading their body; a declared length above the cap is rejected early.

Fresh independent review: 27 tests passed, no critical or important code finding. Deferred minor: the reconstructed internal response omits HTTPX elapsed/download counters; current callers consume neither.

No database rows, migration, API route/schema, credential, provider scope, or dependency changes. This qualifies transport controls, not real-provider sandbox behavior.
