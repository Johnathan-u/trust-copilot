# TC-15-038b evidence

See [the release child ticket](../../../docs/release/tickets/TC-15-038b.md) and [verification.json](verification.json) for the exact local implementation, checks and limitations.

No generated browser evidence is committed as a substitute for execution. The release spec creates these six reports during a real Chromium run:

- `axe-page-360.json`, `axe-page-768.json`, `axe-page-1440.json`
- `axe-dialog-360.json`, `axe-dialog-768.json`, `axe-dialog-1440.json`

Each report contains `width`, `surface`, integer `violationCount`, and a `violations` array whose length matches that count. The corresponding six screenshots are written beneath `screenshots/` and attached to the Playwright result. The coordinator's CI integration must clear previous generated reports/screenshots before running the 39-case spec (including all original 29 cases) and require fresh output. Unit tests and browser API fixtures prove consumer control paths only; the parent retains integrated browser/API/database qualification.
