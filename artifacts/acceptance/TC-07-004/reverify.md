# TC-07-004 re-verify

Product SHA: `b7cc339bd537a0f7649243743a2b87755a20a94e`.
Base: master `fff358abf2001b9d18b0fdf5507ba8a0fc99127c` (#300 is in that history).
Verdict: MEETS-pending-acceptance. The write-up is `docs/release/verification/TC-07-004.md`.
This note does not accept the ticket, does not edit the tracker, and does not record a CI run id.

## Localhost fallback

Not test-only. The host is the Host header. Production compose sets `APP_ENV=production`, and a direct peer of `api:8000` can send `Host: localhost`. Caddy's public path rewrites Host to the site name, so a browser request for `trustcopilot.app` did not use the fallback. The production process still had it.

Closed. The middleware passes `is_production_env()`. In production the host fallback is false. An allowed Origin, an allowed Referer, or a trusted-proxy forwarded origin still passes. Dev and test keep the fallback.

It does not block MEETS. DoD5 (a reviewer other than the implementer accepts this head) is the only gap, and it blocks DONE.

## Lists

Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS.
Headers: Accept, Authorization, Cache-Control, Content-Type, Idempotency-Key, Pragma.
`allow_credentials` stays true. Origins stay the trusted-origin list.

## Counts

| Run | Exit | Total |
|---|---|---|
| `tests/release/test_csrf_proxy.py` before | 1 | 5 failed, 12 passed |
| `tests/release/test_csrf_proxy.py` after | 0 | 17 passed |
| `tests/test_csrf_origins.py` after | 0 | 8 passed |

Python 3.12.3, pytest 9.1.1, Starlette 1.10.0. No database.
Logs: `failing-before-cors.txt`, `passing-after-cors.txt`.
