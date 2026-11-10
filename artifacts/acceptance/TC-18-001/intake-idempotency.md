# TC-18-001 public intake idempotency

Parent for fail-on-parent: `a2b39c80ce14f130285d380db87de75227675a6f` (master, TC-10-003).

The pass-with-fix commands below ran on the working tree that this commit records. No product, test, or doc file changed after those commands. This file is part of that commit. The published head SHA is `git rev-parse HEAD` on `tc/TC-18-001-intake-idempotency` and is the pull request head. Independent acceptance is not claimed.

No schema change. No migration and no downgrade. Persisted idempotency rows already exist; this change does not alter them.

## Environment

- OS: Linux 6.12.113+, Ubuntu 24.04.5
- Python 3.12.3, pytest 9.1.1 (CI build uses Python 3.11)
- Node v24.22.1, npm 11.19.1
- PostgreSQL 16.15 with pgvector, image `pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`
- Database: `postgresql://postgres@127.0.0.1:5432/trustcopilot_test`
- `TC_REQUIRE_DB=1` on the API commands

## Commands and results

Fail on parent, before the product and runbook changes:

```sh
cd apps/web && npm run test:unit -- tests/unit/public-trust-intake.test.ts
```

Exit 1. 4 failed. The lost-response test failed because `Idempotency-Key` was null (`toMatch()` received an object). The conflict and validation-list tests found no alert. Rendering a 422 `detail` list threw `Objects are not valid as a React child`. The bounds test failed with `expected -1 to be 255` (no `maxLength`).

```sh
cd apps/api && TC_REQUIRE_DB=1 python -m pytest tests/release/test_domain_trust_requests.py -q \
  -k 'public_submit_retry_keeps_one_record or public_submit_rejects_blank_or_oversize or intake_reconciliation_runbook'
```

Exit 1. 1 failed, 3 passed, 85 deselected. The multipart retry/conflict test and both blank and 10,001-character route tests passed on the parent: that API behavior was already present. `test_intake_reconciliation_runbook_covers_uncertain_save_and_cleanup` failed because `docs/ops/trust-intake-reconciliation.md` did not exist.

Pass with the fix, same commands:

- Web focused unit file: exit 0, 5 passed.
- API focused selection: exit 0, 4 passed, 85 deselected.

Full suites after the fix:

```sh
cd apps/web && npm run test:unit
cd apps/web && npm run typecheck
cd apps/web && npx playwright test e2e/release/screen-trust-requests.spec.ts --retries=0 --reporter=list
cd apps/api && TC_REQUIRE_DB=1 TC_REQUIRE_WEB_TOOLCHAIN=1 TC_REQUIRE_API_QUALITY=1 python -m pytest -rs
```

- Web unit: exit 0, 49 files, 451 passed.
- Typecheck: exit 0.
- Release Playwright `screen-trust-requests.spec.ts`: exit 0, 32 passed.
- Backend: exit 0, 6393 passed, 1 skipped, 721.87s. The only skip is `tests/test_trust_scoring_blind.py:33` (`external_data` blind pack not checked in).

## Criterion, fix, and test

| Criterion | Fix | Test | Parent | With fix |
|---|---|---|---|---|
| AC3 retry: same `Idempotency-Key` does not create a second request or upload | Public form keeps one key for the same trimmed details and file identity and sends it again after a lost response. The API already returned the stored response before a second insert or upload. | `tests/unit/public-trust-intake.test.ts` ("reuses one key"); `e2e/release/screen-trust-requests.spec.ts` ("public intake keeps one key"); `test_public_submit_retry_keeps_one_record_and_rejects_a_different_body` | Web fail (header missing). API pass | Pass |
| AC3 conflict: same key, different body | API already returns 409 with `This retry key was already used for a different request.` The form shows that string, or a fixed sentence when `detail` is not a string. A changed message uses a new key. | Same API test (409, string detail, no second row, no second upload, body not echoed). Unit test "shows a string conflict" | Web fail (no alert). API pass | Pass |
| AC3 error shape: validation `detail` is not rendered as an object | `publicIntakeError` always returns a string and does not copy the rejected input | Unit test "renders a validation list as text" | Fail (`Objects are not valid as a React child`) | Pass |
| AC3 bounds: blank and oversize message | Trim, `maxLength`, and slice to 255/10,000. Blank message does not submit. 10,001 characters are rejected by `publicIntakeClientError` and by the route | Unit tests "does not submit a blank or oversize message" and "rejects a blank or oversize message before any request". Route test `test_public_submit_rejects_blank_or_oversize_message_with_no_rows` | Web fail (`maxLength` -1; blank submitted). API pass (422 list, zero new rows) | Pass |
| AC3 assignee display | Already read-only from the saved request. Added the missing browser assertion only | `screen-trust-requests.spec.ts` "saved assignee is shown read-only" | Behavior already present | Pass (included in 32) |
| DoD1 | AC3 cases above | Same tests. Full backend skip remains only the external blind pack | AC3 open | Pass, one external skip |
| DoD2 | New cases live in the existing release file. Full suite recorded here | `python -m pytest -rs` and the focused domain selection | Focused: 1 failed, 3 passed | Full: 6393 passed, 1 skipped. Focused: 4 passed |
| DoD4 | Ticket doc cites TC-15-039a/b and the browser restart test. Operator note: `docs/ops/trust-intake-reconciliation.md` | `test_intake_reconciliation_runbook_covers_uncertain_save_and_cleanup` | Fail (file missing) | Pass |
| DoD5 | Not recorded. The implementer does not accept this head | Independent review after this pull request | Open | Open |

The fifth web unit test calls `publicIntakeClientError` directly for a 10,001-character message and a 256-character name. It was added with that function, so it was not part of the four parent failures. A browser cannot place 10,001 characters into the `maxLength` control; the release spec checks that a 10,001-character fill is kept to 10,000 and that a blank message does not post.
