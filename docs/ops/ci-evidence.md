# CI release and failure evidence

Operator notes for the `build` and `web-release-e2e` jobs in
`.github/workflows/ci.yml` (TC-02-009). The jobs print one evidence block and
upload redacted browser artifacts. This workflow does not delete logs, and it
does not turn a failed CI run into a success.

## Where the evidence is

Each job prints a block that starts with `TC-02-009 evidence`.

- `commit:` is `github.sha`, the commit the job checked out.
- `image:` is the container digest the job ran, or `image: none` when the job
  does not start a container. `build` prints the Postgres digest and the moto
  digest. `web-release-e2e` prints `image: none`. Playwright's browser is
  installed with `npx playwright install`. It is not a container image.
- `command:` is the exact test command. `build` records `pytest -rs`.
  `web-release-e2e` records the rules Playwright command, the release
  Playwright command, and `scripts/ci/check-release-e2e-report.mjs`.
- `totals:` is `passed`, `failed`, and `skipped`. The e2e block also prints
  `playwright:` and `axe:` with those three counts. Playwright `flaky` is
  added to `failed`. Axe `passed` is the number of reports with zero
  violations. Axe `failed` is the number of reports with a violation. Axe
  `skipped` is 0.

The block is printed before the step exits, including when the tests fail.
The Actions log for that step is the failure record.

Uploaded artifacts are the other copy. `build` uploads the integrated inbox,
trust-request, and logout-all reports. `web-release-e2e` uploads the
Playwright HTML report, axe JSON, and the synthetic screenshots those specs
write. Every `actions/upload-artifact` step sets `retention-days: 14`.

## Retention

GitHub keeps workflow artifacts and logs for 90 days unless a repository or
organization setting says otherwise. Public repositories can use 1 to 90 days.
Private repositories can use 1 to 400 days. The setting is under Settings,
Actions, General, "Check, workflow run, status, artifact and log retention".
Changing it affects new artifacts and logs. It does not rewrite objects that
already exist.

This workflow sets a shorter life on the artifacts it uploads. `retention-days:
14` on every `actions/upload-artifact` step keeps that artifact for 14 days.
The value cannot be longer than the repository limit. There is no per-step
setting for the log. The log stays until the repository retention period
deletes it. A failed job's log is not removed early, and a later workflow
cannot mark that CI run successful.

`deploy.yml` runs on a push to `main` and on `workflow_dispatch`. It builds
images and its deploy step is still a placeholder. It does not use
`workflow_run`, and it does not deploy GitHub Pages. `backlog-tracker.yml`
validates the tracker. It does not deploy Pages. A green deploy run is a
different workflow. It does not change the conclusion of a failed CI run.

A Pages deploy that listened to `workflow_run` with type `completed` would run
after a failed CI job as well as a successful one. `if: success()` does not
stop that, because it describes the new job, not
`github.event.workflow_run.conclusion`. This repository has no such workflow.
`apps/api/tests/release/test_ci_evidence.py` rejects one if it is added without
`github.event.workflow_run.conclusion == 'success'`.

## Redaction

Generated database and storage passwords are masked with `::add-mask::` before
the containers start. The evidence block does not print those values. Writes
of the database URL go to `GITHUB_ENV`, not to the log.

Browser artifacts are redacted before upload.

- Integrated acceptance configs (`playwright.inbox.config.ts`,
  `playwright.trust-requests.config.ts`, `playwright.logout-all.config.ts`,
  `playwright.vendor-requests.config.ts`, `playwright.rules.config.ts`, and
  `playwright.rules-evidence.config.ts`) set `trace: 'off'`. The ones that
  submit a password or a session also set `screenshot: 'off'` and
  `video: 'off'`, so those submissions are not recorded.
- `apps/web/playwright.config.ts` keeps `trace: 'on-first-retry'` so a retried
  failure still has a trace. The release job passes `--retries=0`, so that run
  does not write one. `screenshot: 'only-on-failure'` still applies.
- After the tests, and before any upload, both jobs run
  `python3 scripts/ci/redact-playwright-artifacts.py` on
  `apps/web/playwright-report` and `apps/web/test-results`. The script is
  stdlib Python. It rewrites HTML, JSON, and other text reports, and it
  rewrites text members inside trace zips. Connection URLs, Bearer and Basic
  values, cookie headers, and unquoted password or access-key assignments
  become the word `redacted`. PNG screenshots are not rewritten.
- Uploads that contain `playwright-report` or `test-results` run only when
  that redaction step succeeded. A failed redaction does not upload them.
- The release and integrated specs use synthetic fixtures. They do not load a
  customer document. The redactor does not try to guess prose. Axe JSON
  uploaded from `artifacts/acceptance/` is violation counts from those
  synthetic pages.

The e2e job uses the runner's `python3`. It does not install the API.

## What a failed run looks like

The job conclusion stays `failure`. The evidence block is in that job's log.
Artifacts from the redacted directories remain available for 14 days when
redaction succeeded. The log remains for the repository retention period.
Nothing in `.github/workflows/` deploys Pages, and nothing there sets the CI
conclusion back to success.
