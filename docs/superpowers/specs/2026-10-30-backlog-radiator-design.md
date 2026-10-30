# Backlog information radiator design

Owner request, 2026-10-30: build an HTML/CSS tracker with all required project information for humans and AI, and update repository instructions so Grok and Codex PMs use it. The owner chose direct implementation. Existing engineering authorization and merge gates apply.

## Approach
Use a dependency-free static HTML/CSS/JavaScript interface, a versioned JSON status ledger, and a Python-standard-library builder/validator. This fits the repository, works locally without accounts or hosting, and gives agents deterministic data. Jira is unavailable. Adding a service/database or modifying customer product screens would add unnecessary operational work.

## Scope and authority
- Original scope and requirements remain in docs/planning/TrustCopilot_Execution_Backlog.json.
- docs/planning/backlog-state.json owns reconciled execution/acceptance status, owners, blockers, evidence and history.
- docs/tracker/index.html is the human view. Its generated snapshot is produced from those sources, never edited by hand.
- Issue #85 remains the assignment/decision ledger; the coordinator lease and PR merge protocol remain in force.
- Initial evidence comes from the already audited snapshot at b2bd1e0; all acceptance is pending. Preserve all 384 original tickets, 30 epics and 1,864 points. Preserve all AC/DoD/DoR/interfaces/paths/test commands via canonical records.
- Record supplemental release/child tickets separately; never double count their estimates as original-parent points.
- Completion = accepted original-parent points / 1,864. Keep the displayed percentage null until baseline verification is complete. A parent earns points only after its complete criteria, DoD, tested SHA, evidence and independent review are recorded. Incomplete work, artifacts and merged PRs are evidence, not automatic acceptance.
- A versioned scope change requires an explicit record; validation rejects silent denominator/ID/weight drift.
- Source gaps do not imply an active assignment. Unknown status remains visibly unknown.
- Separate release gates, active PRs, implementation gaps, blockers and baseline review coverage.
- Snapshot timestamp and source SHA are always visible; a static snapshot never claims to poll GitHub live.

## Human interface
Desktop/mobile accessible dashboard with overview, searchable/filterable backlog, epic rollups, release gates and PM handoff. Ticket detail exposes the complete contract, current state, PR/evidence links, owner, next action and dependencies. Support stable ticket deep links and keyboard use, empty-state/reset controls, and data export. No fabricated assignees or dates. Use plain language, visible focus and sufficient contrast. Render repository text safely and only permit safe link protocols. No secrets, analytics, external scripts/fonts or browser-side GitHub credentials.

## Data interface for implementation workers
Generated docs/tracker/data.js assigns window.TRUSTCOPILOT_BACKLOG:
- meta: {title, schema_version, scope_version, revision, as_of_utc, source_sha, baseline_status, metric_label, formula}
- summary: {accepted_points:null|number, completion_percentage:null|number, assessed_tickets:number, total_tickets:384, total_points:1864, state_counts:object}
- epics: original epic objects, plus computed fields if useful.
- tickets: original canonical ticket objects unchanged, each with current:{status,evidence_state,owner:null|string,blockers:array,next_action,updated_at,acceptance:object,pr_links:array,evidence_links:array} and optional followups[].
- release_gates: [{id,title,status,note,evidence_urls:[],ticket_ids:[],owner}]
- operational_gates: any audit gate records, separately labeled.
- history: dated state/acceptance changes; no invented historical percentages.
- followups: [{id,title,parent_id:null|string,story_points:null|number,source_url,source_path}].
- operating: {ledger_url,state_path,guide_path,source_path,commands:object}.
Agent-specific extra fields may be added without removing these fields. Coordinate if a contract change is needed.

## Maintenance and validation
CLI build/check/summary plus a validated update path with expected revision, actor and reason. Reject unknown IDs/statuses, inconsistent points, invalid references, missing acceptance evidence, accepted self-review and silent scope drift. Regenerate the display from the canonical/state pair. Track history and do not accept stale revision updates. Add a focused CI workflow for validation/tests and generated-snapshot consistency, preserving existing product gates.

## Acceptance
All source records and dependencies survive; pending baseline never shows 0%/45%; merge/child/epic counts cannot inflate progress; invalid acceptance/state updates fail; stale snapshots are identifiable; offline UI search/filter/detail and mobile/keyboard work; unsafe text remains inert; both PM instructions identify the same files and update workflow; independent review and required exact-head CI precede merge.
