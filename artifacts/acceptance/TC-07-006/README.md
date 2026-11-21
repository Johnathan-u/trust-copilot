# TC-07-006: stream-bounded uploads with honest 413

The API, the Next.js `/api` proxy, and production Caddy stop at `MAX_UPLOAD_BYTES` (default 52428800). A larger body is HTTP 413. The bytes past the cap are not kept. A rejected or interrupted upload leaves no document, questionnaire, trust request, job, or stored object.

This note does not accept the ticket. No migration.

## Red command

See `commands.md`. Base `ba789896951bc60e8f67842c87f67a0b50fbe988`. Exit 1. 8 failed, 15 passed. Log: `failing-before.txt`.

## Green command

Same pytest command after the product change. Exit 0. 23 passed, 0 skipped. Log: `passing-after.txt`.

Web proxy unit test: 8 passed (`apps/web/tests/unit/api-proxy.test.ts`).

Environment: `environment.txt`.

Local pytest and the web unit test ran on `7e6bec9a511c94e80b57d16533200499d537695d`. The commit that records this SHA does not change product code.
