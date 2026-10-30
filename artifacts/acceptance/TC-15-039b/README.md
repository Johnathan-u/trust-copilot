# TC-15-039b local evidence

Base: `50f0418296e4238bfb402f67250df6d299e76ccc`.
Branch: `codex/TC-15-039b-real-api`.
Claim: [#85 comment 6514057821](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6514057821).
Only the new acceptance test, its dedicated Playwright spec/config, ticket and
this evidence directory are changed. Existing #117 process helpers are imported
unchanged. No runtime, auth/storage route, dependency or CI edit is included.

## Local checks

See [local-checks.txt](local-checks.txt) for the command ledger. The Python harness
collects one test; the dedicated browser config collects two phases. Normal
Playwright discovery excludes the `.acceptance.ts` file and still collects 211
tests in 20 files at this base. TypeScript, focused ESLint/Prettier, Ruff and Python
compilation pass. Two existing process-helper regressions pass, including the
failure-body case and a descendant that ignores SIGTERM.

An independent child-process diagnostic extracted the exact socket bootstrap
constant without importing the test module or starting the API. Using the real
`StorageClient` and synthetic loopback settings, construction made zero storage
attempts; `ensure_buckets()` produced one denied startup attempt. A second
construction after readiness again produced zero attempts. Deliberate calls to
`download_stream()` and external DNS were denied and recorded as post-readiness
storage and external attempts. The acceptance predicate would reject either.
This diagnostic proves the guard observes failures; it does not qualify the API,
database, authorization or successful storage behavior.

Strict acceptance was invoked with `TC_REQUIRE_DB=1 TC_REQUIRE_WEB_TOOLCHAIN=1`.
It exited **3**, because local PostgreSQL on localhost:5432 refused the connection
during Alembic setup. This is a real failure, not a skip or successful runtime
result. The installed Playwright package also reports its locked Chromium
executable absent. No database/browser installation, dependency change, substitute
browser or weakened gate was attempted. No real browser phase ran locally.

## Required CI evidence

**#120 and #121 must be included before qualification.** The coordinator reports
both landed at master `5928f061e2967e9ca717879b0517a66f22f4d6c2`; this harness's
source commit is kept separate from the master integration merge. Run this
new test in the existing PostgreSQL/Python/locked-Chromium job on the final
integrated head, add the two upload directories, and obtain independent review
plus exact-head push and PR checks.

Successful runtime reports must contain one passed, zero skipped/flaky/unexpected
test in each phase, distinct API/Next PIDs across restart, reaped services and
closed ports, explicit startup-only storage denials, zero post-readiness storage
or external attempts, and all persistence/denial assertions. The Python test
compares complete saved reply rows before the second browser phase and checks
the final database state, including approval hashes and delivery provenance.
Full baseline hashes must match after owned cleanup, even after test failure.

Runtime artifacts are generated under:

- `apps/web/playwright-report/trust-requests-restart/{before,after}/`
- `apps/web/test-results/trust-requests-restart/` (phase reports, network denial
  records, process metadata and successful assertion summaries)

No fabricated runtime/axe/screenshot artifacts are committed. Credentials are
synthetic; reports do not include cookies or session state, and raw service logs
are not uploaded. Screenshots, videos and traces are disabled. The child API
retains real authorization and storage construction; only test network egress is
denied. Synthetic S3 startup unavailability is not positive object-store evidence.

All four parent gates remain: permitted assignee lookup/picker, owner/viewer
semantics, integrated API/browser qualification until the required run succeeds,
and owner-gated real provider delivery. This child does not complete TC-15-039 or
claim provider/recipient delivery, positive S3 or the outgoing Trust workflow.
