# TC-15-039c diagnostic evidence

Branch: `codex/TC-15-039c-axe-diagnostics`.
Base: `8f0cc07872057007d635e7bee17687f5fadc696b`.
Claim: [#85 / 6515572542](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6515572542).
No worker publication. The handoff records the resulting commit/tree.

## Actual failed browser evidence

- [Run 41006499666, job 123902477500](https://github.com/Johnathan-u/trust-copilot/actions/runs/41006499666/job/123902477500):
  239 passed / 1 failed; 768px incoming list/reply editor keyboard/axe test.
- Axe artifact `12955643482`: 768px has one serious `color-contrast` node;
  360px and 1440px have zero violations. The exact 768px summary is preserved in
  [observed-failure.json](observed-failure.json), not presented as a clean report.
- HTML artifact `12955449797`: failure screenshot shows enabled/focused Approve
  revision; no trace was available. The summary lost node selectors, HTML and
  measured colors. The screenshot does not identify the violating node.

Reviewer and author agree the transition explanation remains unproven. This
commit changes diagnostics only and claims no contrast correction.

## Preservation behavior

The existing summary schema and mapping are unchanged. Full raw axe violations
are saved alongside them as `violationDetails`. This retains all node targets,
HTML, failure summaries and `any`/`all`/`none` check data, including colors and
contrast measurements supplied by axe. No diagnostic-field allowlist discards
these details.

The original failure assertion runs after writing the JSON, requesting the
full-page screenshot and attaching both files. Existing CI upload paths already
retain both artifacts when the job fails; no workflow/checker change is needed.
The same serious/critical assertion still fails. The shared checker still rejects
any nonzero summary violation count and still requires integer count/list equality.

## Local proof and limits

[verification.txt](verification.txt) records lint, typecheck, formatting and
22-case collection. TypeScript AST and exact expression-source comparisons confirm
all 63 original assertions are unchanged, along with the summary mapping and
existing report fields.

A standalone control executed the edited reporting statements with a synthetic
serious violation containing target/HTML/color data and the real Playwright expect
implementation. JSON retained the complete object; the unchanged assertion failed
only after screenshot and both attachment calls. Screenshot/attachment functions
were stubs, and only the test-owned temporary directory was removed. This checks
serialization and ordering, not actual browser or accessibility acceptance.

The existing package lock matched the available local toolchain exactly; no
dependency changes or installs were made. Locked Chromium was absent, so no real
browser execution is claimed. Final browser diagnostic evidence, root-cause
identification, any specifically authorized product repair and independent review
remain required. No threshold, wait, retry, skip or product/style change is included.
