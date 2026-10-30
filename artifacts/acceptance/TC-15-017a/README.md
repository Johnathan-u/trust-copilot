# TC-15-017a local evidence

Base: `d64e3803df975d25622cf28a2556178828db3c60`. Runtime/test file hashes are recorded in `source-hashes.json`; the coordinator records the final commit and required exact-head CI qualification separately.

A regression was run against the original page before implementation: a real-shaped restore 403 removed Archived and produced no alert. The test failed (`1 failed`) because the alert was absent; its captured DOM also showed the archived badge had disappeared. The final unit test retains that assertion. A second regression failed (`false` selected state where `true` was expected) before aligning the acknowledged empty-label state with the API’s existing `Other` fallback. The completed suite covers status failures, malformed acknowledgements, transport errors, duplicate requests, retained drafts, successive autosaves, legacy modal consumers, and late responses after user/workspace changes.

Final local results: `npm run quality` exited 0 (typecheck, lint, formatting, **44 unit files / 446 tests passed**); focused questionnaire tests **25 passed**; Chromium UI16 **4 passed, 0 failed/skipped/flaky**; **9 axe reports / 0 violations**. See `validation.json` and `quality.log`.

Local browser evidence is **synthetic control-path coverage**, not real API or PostgreSQL qualification. UI16 uses real React/Next components and Chromium but supplies explicit API responses; its transport-abort case is separate from HTTP rejection cases. Screenshots contain synthetic questionnaires and users only. Nine scoped WCAG axe scans cover metadata failure, restore failure and acknowledged state at 360, 768 and 1440 CSS pixels. Tab wrapping, Escape/return focus, pending controls and failure/retry/success are asserted in the browser.

Local commands from `apps/web`:

- `node_modules/.bin/vitest run tests/unit/questionnaire-ack.test.ts`
- `node_modules/.bin/playwright test --config=playwright.questionnaire-local.config.ts`
- `npm run quality`

The temporary local Playwright config is preserved as `local-playwright-config.txt`, with the real report in `local-playwright-report.json`. It starts this worktree's Next process on 127.0.0.1:3421; server and browser share one command's network namespace. It uses the already-installed exact Playwright browser, Chrome Headless Shell 156.0.8078.4 / revision 1248, at `/tmp/tc-pr149-pinned-chrome/chrome-headless-shell-linux64/chrome-headless-shell`. The repository config and CI toolchain are unchanged. The dependency symlink uses the existing locked toolchain; both lockfiles SHA256 `351e7d2d85d5bd102e5d29fa06adfb455bc339e6c990a135e6555a4cf717075e` matched. No dependencies or browser downloads were installed.

Backend harness static checks: `/tmp/tc-backend-venv/bin/python -m ruff check apps/api/tests/release/test_questionnaire_ack_browser.py` and Python compileall passed. The required real-API invocation from `apps/api` was attempted:

```
TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test /tmp/tc-backend-venv/bin/python -m pytest tests/release/test_questionnaire_ack_browser.py -q --tb=short
```

It exited 3 during mandatory Alembic setup: PostgreSQL on 127.0.0.1:5432 refused the connection. No test cases ran, no schema bypass or SQLite substitute was used, and no provider calls were made. Real API 403/200, database persistence/cleanup, and six real-browser axe/screenshots remain required CI evidence.

CI wiring for the coordinator:

- Add `e2e/release/ui-16.spec.ts` to the release spec list and verify `--require-spec e2e/release/ui-16.spec.ts --min-tests 4 --axe-dir ../../artifacts/acceptance/TC-15-017a`.
- Preserve `artifacts/acceptance/TC-15-017a/` as the UI artifact directory.
- The existing backend pytest collection discovers `tests/release/test_questionnaire_ack_browser.py`; it requires three successful, non-skipped real browser cases and six zero-violation axe reports.
- Always upload `apps/web/playwright-report/questionnaire-ack/` and `apps/web/test-results/questionnaire-ack/`. Credential-bearing trace/video are disabled, and the harness scans report payloads before upload.

Independent review and build/web-release-e2e on both push and pull_request for the final head remain required. This evidence does not close the full TC-15-017 parent.

Artifact formatting normalization adds the missing final newline to the nine axe
JSON reports and `local-playwright-report.json`, and removes the extra terminal
blank line from `quality.log`. JSON values, log content before its terminal
newlines, and all runtime/test source hashes remain unchanged. This formatting
step does not rerun or upgrade the recorded test qualification.
