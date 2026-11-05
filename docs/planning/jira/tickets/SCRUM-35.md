# SCRUM-35 · How to work TrustCopilot tickets (humans and AI agents)

| Field | Value |
|---|---|
| Jira | [SCRUM-35](https://reinhartjm294trustcopilot.atlassian.net/browse/SCRUM-35) |
| Type | Task |
| Epic | — |
| Status | Idea |
| Points |  |
| Priority | Highest |
| Start | 2026-11-01 |
| Due | 2026-12-15 |
| Sprint |  |
| Labels | `workflow-guide` |
| Blocked by | — |
| Blocks | — |

> Snapshot of Jira on 2026-11-05. Jira is the source of truth for status, dates and sprint; the text below is the Jira description (Jira line breaks shown as a trailing `\`).

---

This project holds the full TrustCopilot backlog: 30 epics (E01-E30) and 384 tickets (TC-EE-NNN), 1,864 story points.

**Picking a ticket**

1. Filter by label: `agent-ready` (an AI agent can do it alone), `needs-owner-accounts` (needs Johnathan's accounts, money or signature for the final step), `human-only` (owner, legal or buyer decision).
2. Only start a ticket whose _is blocked by_ links are all Done.
3. Prefer Highest (P0), then High (P1), then Medium (P2).

**Doing it**

1. Read the ticket's first lines (backlog_id, depends_on, test, repo_state), then the spec link: it has the full definition of done and evidence rules.
2. Move the ticket to In Progress. Branch from `master` as `tc/<TC-ID>-<slug>` (given in each ticket).
3. Implement only that ticket's acceptance criteria. No unrelated refactors, dependency upgrades or hidden features.
4. Run the ticket's test command. Open a PR titled `<TC-ID>: <short summary>` and comment the PR link on the ticket.
5. Move to Done only when every acceptance criterion and the spec's definition of done are met and reviewed.

**Labels**

* `epic-eNN`: which epic
* `p0` / `p1` / `p2`: original priority
* role labels: `frontend`, `backend`, `fullstack`, `integrations`, `security`, `platform`, `ai`, `analytics`, `design`, `docs`, `qa`, `ops`, `privacy`, `identity`, `domain`, `tech-lead`
* repo state at import (2026-10-31): `repo-not-started-or-unverified`, `repo-work-exists-needs-verification`, `repo-in-progress`, `repo-blocked`

**Source of truth:** this Jira project. Repo spec files (docs/planning/tickets/) hold the detailed contract for each ticket.
