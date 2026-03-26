# Epic 4 & 5 — acceptance and automated test criteria

This document maps backlog tickets to verifiable criteria. Primary automated coverage lives in `apps/api/tests/test_buyer_portal_proof_graph.py` (API layer). Additional pytest modules are noted where relevant.

---

## Epic 4 — Buyer Experience

### E4-20: Buyer-mode interface

**Intent:** Buyers interact without a Trust Copilot account via a dedicated entry surface (procurement co-pilot), not only seller admin UI.

**Acceptance criteria**

- A workspace admin can create a buyer portal with a unique opaque token.
- Public routes exist under `/public/buyer-portal/{token}/…` that do not require session cookies.
- A capabilities manifest lists buyer-facing features (instant match, change tracking, escalations, satisfaction, subscriptions, NDA/trust-center flags as declared).

**Automated tests**

- `TestBuyerPortalAPI.test_public_manifest_and_instant_match`: GET `/public/buyer-portal/{token}/manifest` returns `200` and `features.instant_questionnaire_match === true`.

---

### E4-21: Instant questionnaire response for buyers

**Intent:** Match buyer-submitted question text to the seller’s approved golden-answer library with scoring, review flags, and signal backing (live integrations vs documents).

**Acceptance criteria**

- POST `/public/buyer-portal/{token}/instant-match` with `{ "questions": string[] }` returns one result object per question.
- Each result includes: `match_score`, `need_seller_review`, optional `golden_answer_id`, optional `answer_text`, `confidence`, `signal_backing` (`live_signals` | `documents` | `static` | `none`).
- Matching uses workspace scoped to the portal; invalid or inactive token returns `404`.

**Automated tests**

- `TestBuyerPortalService.test_match_questions_finds_golden`: service-layer match against an approved golden answer.
- `TestBuyerPortalAPI.test_public_manifest_and_instant_match`: HTTP instant-match returns non-null `golden_answer_id` and expected `answer_text` when question text aligns with library.

---

### E4-22: Buyer-side change tracking

**Intent:** Buyers see what changed since prior snapshots; optional email subscription to framework-scoped updates.

**Acceptance criteria**

- Admin can capture a snapshot of workspace posture summary (counts: golden answers, evidence items, control status histogram) via POST `/api/buyer-portal/snapshots/capture`.
- GET `/api/buyer-portal/snapshots/{portal_id}` lists historical snapshots for that portal in the session workspace.
- GET `/public/buyer-portal/{token}/changes` returns a structured delta when at least two snapshots exist; otherwise a clear message.
- POST `/public/buyer-portal/{token}/subscribe` records an email (and optional `frameworks_json`) for the portal.

**Automated tests**

- `TestBuyerPortalService.test_snapshots_and_change_summary`: two captures produce a non-null `get_latest_change_summary` with `deltas`.
- Admin listing subscriptions: covered implicitly when exercising portal lifecycle (extend with GET `/api/buyer-portal/subscriptions/{portal_id}` if needed).

---

### E4-23: Buyer escalation workflow

**Intent:** Buyers file structured escalations; sellers triage and resolve in-workspace.

**Acceptance criteria**

- Public POST `/public/buyer-portal/{token}/escalations` creates a row with `buyer_email`, `escalation_type`, `message`, optional `question_snippet`, optional `answer_id`.
- Admin GET `/api/buyer-portal/escalations` returns escalations for the session workspace.
- Admin PATCH `/api/buyer-portal/escalations/{id}` can set `status` and `seller_notes`; resolving sets `resolved_at`.

**Automated tests**

- `TestBuyerPortalAPI.test_escalation_and_satisfaction`: create via public route, list contains id, patch to `resolved`.

---

### E4-24: Buyer satisfaction signals

**Intent:** Capture post-exchange signals (acceptance, follow-ups, cycle time, deal outcome) for downstream analytics.

**Acceptance criteria**

- POST `/public/buyer-portal/{token}/satisfaction` accepts optional fields: `questionnaire_id`, `accepted_without_edits`, `follow_up_count`, `cycle_hours`, `deal_closed`, `extra_json`.
- Response includes persisted record identifiers and timestamps.

**Automated tests**

- `TestBuyerPortalAPI.test_escalation_and_satisfaction`: satisfaction POST returns `200`.

---

## Epic 5 — Verifiable Proof Graph

### E5-25: Proof graph data model

**Intent:** Traversable graph linking evidence, controls, golden answers, and questionnaire answers within a workspace.

**Acceptance criteria**

- Migrations define `proof_graph_nodes`, `proof_graph_edges`, and related tables (see `073_buyer_experience.py`, `074_proof_graph.py`).
- POST `/api/proof-graph/sync` rebuilds nodes/edges from `evidence_items`, `workspace_controls`, `golden_answers`, and `answers` (via questionnaire workspace scope) and returns counts.
- GET `/api/proof-graph/nodes` and GET `/api/proof-graph/edges` return graph data; nodes support optional `node_type` and `limit` query params.

**Automated tests**

- `TestProofGraphAPI.test_sync_chain_freshness_hash_diff_reuse`: sync returns `nodes >= 1`; filtered GET returns a `golden_answer` node.

---

### E5-26: Proof chain visualization

**Intent:** UI shows a chain from evidence through controls/promises to answers. **API foundation only in repo:** chain payload for embedding.

**Acceptance criteria (API)**

- GET `/api/proof-graph/chain/answer/{answer_id}` returns `404` if the answer is not represented in the graph after sync; otherwise returns ordered `chain` with node metadata.

**Automated tests**

- Add a dedicated test when a seed questionnaire+answer exists in workspace 1, or create via API in test setup, then assert `chain` length ≥ 2.

---

### E5-27: Freshness indicators on proof chains

**Intent:** Each node is classifiable as `live`, `recent`, `aging`, or `stale` from underlying row timestamps and golden expiry.

**Acceptance criteria**

- Each node in `chain_for_answer` includes a `freshness` field.
- GET `/api/proof-graph/freshness/node/{node_id}` returns `{ "freshness": "<bucket>" }` for nodes in the caller’s workspace.

**Automated tests**

- `TestProofGraphAPI.test_sync_chain_freshness_hash_diff_reuse`: freshness for a golden-answer node is one of the four buckets.

---

### E5-28: Cryptographic hashing for high-trust artifacts

**Intent:** SHA-256 at approval/distribution time with recipient verification.

**Acceptance criteria**

- POST `/api/proof-graph/artifacts/hash` records `artifact_kind`, `artifact_id`, and content (via `content_text` or `content_base64`), storing `sha256_hex`.
- POST `/api/proof-graph/artifacts/verify` recomputes hash and compares to latest stored row for that workspace/kind/id.

**Automated tests**

- Same test class: record hash then verify with identical content yields `ok: true`; tampered content would yield `ok: false` (add explicit negative case if desired).

---

### E5-29: Proof graph diffs

**Intent:** Immutable before/after records when the graph changes.

**Acceptance criteria**

- Sync via `sync_with_diff_record` appends a `proof_graph_diffs` row with `trigger_event`, `before_json`, `after_json`, `summary`.
- GET `/api/proof-graph/diffs` lists recent diff records for the workspace.

**Automated tests**

- `TestProofGraphAPI.test_sync_chain_freshness_hash_diff_reuse`: after sync, `GET /diffs` returns at least one entry.

---

### E5-30: Reuse provenance tracking

**Intent:** Every reuse of an answer records questionnaire, deal, buyer ref, version hint, and evidence IDs used.

**Acceptance criteria**

- POST `/api/proof-graph/reuse-provenance` creates `answer_reuse_provenance` scoped to workspace.
- GET `/api/proof-graph/reuse-provenance/answer/{answer_id}` lists instances in reverse chronological order.

**Automated tests**

- Same test class: POST reuse for `answer_id`, then GET lists ≥ 1 instance.

---

## Traceability matrix

| Ticket | Primary pytest reference |
|--------|--------------------------|
| E4-20 | `test_public_manifest_and_instant_match` (manifest) |
| E4-21 | `TestBuyerPortalService.test_match_questions_finds_golden`, `test_public_manifest_and_instant_match` |
| E4-22 | `TestBuyerPortalService.test_snapshots_and_change_summary` |
| E4-23 | `test_escalation_and_satisfaction` |
| E4-24 | `test_escalation_and_satisfaction` (satisfaction POST) |
| E5-25 | `TestProofGraphAPI` (sync + nodes) |
| E5-26 | Manual / future test with seeded answer chain |
| E5-27 | `TestProofGraphAPI` (freshness) |
| E5-28 | `TestProofGraphAPI` (hash + verify) |
| E5-29 | `TestProofGraphAPI` (diffs) |
| E5-30 | `TestProofGraphAPI` (reuse provenance) |
