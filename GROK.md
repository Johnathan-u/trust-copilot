# Grok PM entry point

Use [AGENTS.md](AGENTS.md) and [the shared PM backlog protocol](docs/release/PM_BACKLOG_PROTOCOL.md) before choosing or reporting work.

The human information radiator is [docs/tracker/index.html](docs/tracker/index.html). The shared status source is [docs/planning/backlog-state.json](docs/planning/backlog-state.json); original scope remains in [the execution backlog](docs/planning/TrustCopilot_Execution_Backlog.json).

Grok PM and Codex PM use the same original-parent acceptance formula and status records. Update the shared tracker after each meaningful authorized work batch. Treat historical BACKLOG_STATUS and handoff tables as dated context, and reconcile against live master/PRs and issue #85.

The current Codex coordinator succession and single coordinator lease remain in force. Grok workers return changes/evidence to that coordinator and do not self-publish or merge. Do not infer active work or completion from a branch name or merged PR alone.
