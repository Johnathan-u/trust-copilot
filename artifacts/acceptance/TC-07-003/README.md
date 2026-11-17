# TC-07-003 post-login redirect evidence

The behavior under test is already on master. No API route reads `next`. The named release file runs the web checks that cover the acceptance criteria.

Command, from `apps/api`, with Node 24 on `PATH`:

```sh
python -m pytest tests/release/test_login_redirect.py -q --tb=short --capture=no
```

The backlog command is the same file with `-q` only. `--tb=short --capture=no` is how the saved logs were captured, so the vitest reporter is visible. Both forms collect 1 pytest. That pytest runs:

```sh
npx vitest run lib/post-login-path.test.ts tests/unit/login-next.test.ts tests/unit/middleware.test.ts
```

from `apps/web`. The vitest run is 3 files and 14 tests: 7 in `lib/post-login-path.test.ts`, 3 in `tests/unit/login-next.test.ts`, and 4 in `tests/unit/middleware.test.ts`.

## SHA

Production web code in both runs is `37ac10b80e55e6901a5b70c930207c734b5b4b17`. That commit already rejects a dangerous `next` in `safePostLoginPath` and uses the result after password sign-in, MFA verify, and the enrolment continuation. The parent commit therefore passes this test once the file exists. It cannot show a failing-before log. The failing run below stubs `safePostLoginPath` in the working tree and does not commit that edit.

`git diff -- apps/web/lib/post-login-path.ts` was empty before the passing run, and again after the file was restored.

## Failing before

`safePostLoginPath` in `apps/web/lib/post-login-path.ts` returned the raw string whenever it was non-empty. The decode loop and the same-origin check did not run. Empty, null, and undefined still returned `/dashboard`. No other file changed. The edit was restored with `git checkout -- apps/web/lib/post-login-path.ts` before the passing run.

Exit status 1. Pytest: 1 failed, 0 passed. Vitest: 7 failed, 7 passed, 14 total. Log: [failing-before.txt](failing-before.txt).

The four rejection cases in `lib/post-login-path.test.ts` received the dangerous string instead of `/dashboard` (`https://example.com`, `/\example.com`, `javascript:alert(1)`, `%2F%2Fexample.com`). The safe-path, missing-value, and encoded-query cases in that file still passed. Middleware's four tests still passed. They do not call `safePostLoginPath`.

All three cases in `tests/unit/login-next.test.ts` failed. The first fails on the phish sign-in: `window.location.origin` is `https://example.com`. The MFA and enrolment cases use `next=/dashboard/security`. They then see the same origin. The file's `beforeEach` calls `history.replaceState` with a relative `/login`. After the phish assignment, that relative URL stays on `https://example.com`, and the later relative assignment does too.

## Passing after

The auth file was restored. The same command then exited 0. Pytest: 1 passed. Vitest: 3 files passed, 14 tests passed, 0 failed, 0 skipped. Log: [passing-after.txt](passing-after.txt).

The backlog form, `python -m pytest tests/release/test_login_redirect.py -q --tb=line`, also exited 0: 1 passed. Pytest captures the vitest reporter on that form, so the 14 tests are not repeated in that short summary.

## Environment

Local cloud VM, Linux 6.12.113+ x86_64. Node v24.22.1. npm 11.19.1. Vitest 5.0.5. Python 3.12.3. pytest 9.1.1. `apps/web/node_modules` came from `npm ci --ignore-scripts`. No database and no live provider were used. The API suite's autouse fixtures ran and continued when PostgreSQL was not listening. The Vite config-loader warning in both logs is the existing warning from `apps/web/vitest.config.ts`. It is not a failure.

The logs contain the synthetic fixture host `example.com` and the string `javascript:alert(1)` from the existing unit file. They contain no password, token, or customer document.

## CI

`ci-runs.md` is added after `build` and `web-release-e2e` are green on both `push` and `pull_request` for the commit that contains these logs. That follow-up commit records those run IDs. The follow-up commit's own run IDs are in the pull request body.
