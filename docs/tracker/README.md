# Trust Co-Pilot backlog tracker

[Open the published tracker](https://johnathan-u.github.io/trust-copilot/docs/tracker/) on the repository's existing GitHub Pages site. The normal Pages build publishes merged repository changes; the displayed timestamp identifies the committed snapshot.

Open **`index.html`** from a repository checkout. Keep `styles.css`, `app.js` and generated `data.js` beside it. The dashboard works without a server or network connection. External source/evidence links need network access.

For local HTTP access, run `python -m http.server 8080` from the repository root and open `http://localhost:8080/docs/tracker/`.

The dashboard provides the full original backlog, epic rollups, current evidence and execution states, dependencies, PRs, acceptance requirements, blockers, release gates and snapshot history. Search by ticket ID, title or requirement, filter the view, and open a ticket for its complete contract. A source timestamp and SHA identify what the snapshot actually covers.

Engineering prerequisites and release approvals are shown separately using the accepted scope-freeze rulings. Historical planning dependencies and the initial PR audit remain available with their original provenance.

## For both PMs and human maintainers

Read [the shared PM protocol](../release/PM_BACKLOG_PROTOCOL.md). The protocol applies to **Grok PM and Codex PM**.

- Scope and complete original contracts: [canonical backlog](../planning/TrustCopilot_Execution_Backlog.json).
- Current machine-readable state: [backlog-state.json](../planning/backlog-state.json).
- Assignments and decisions: [issue #85](https://github.com/Johnathan-u/trust-copilot/issues/85).
- Build, validate, summarize and update: `python scripts/backlog_tracker.py --help` from the repository root.

The displayed completion metric uses accepted original-ticket points over the frozen 1,864-point scope. It stays **Baseline verification pending** until the initial assessment is complete. Partial implementations, merged PRs and child work remain visible without being automatically marked Done.

## Refresh

```bash
python scripts/backlog_tracker.py build
python scripts/backlog_tracker.py check
python -m unittest discover -s scripts/tests -p 'test_backlog_tracker.py'
```

The browser regression suite uses the repository's existing locked Playwright dependency. After installing `apps/web` dependencies and its Chromium browser, run `node --test docs/tracker/tests/browser.test.cjs` from the repository root. The dedicated Backlog tracker workflow runs both suites and checks the generated snapshot on affected pushes and pull requests.

Use the validated `update` command and expected revision for state changes. Commit the state and generated snapshot together through the existing review process. The view is a repository snapshot; it does not write to GitHub, save shared changes in browser storage or automatically poll external services.

## Safety and scope

The tracker adds no application service, database, hosting requirement, analytics, external script or dependency. It does not change the customer product or replace the existing coordinator lease, review, CI, owner decision or release acceptance rules.
