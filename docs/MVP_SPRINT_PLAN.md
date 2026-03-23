# Trust Copilot — MVP Sprint Plan

**Created**: March 2026

---

## Sprint 0 — Scope Lock and Codebase Alignment

### MVP-001 — Audit and label every route, page, and service

Create a full inventory of frontend pages, backend routers, and core services and mark each one as keep, rewrite, hide, or retire. This gives the project a single source of truth for what is actually part of the MVP versus what is leftover from the earlier controls-first design. The output should live in the repo and be referenced by all later cleanup and implementation tickets.

### MVP-002 — Trim the frontend to the MVP navigation surface

Remove non-MVP items from the sidebar and stop exposing pages that do not support the new evidence -> questionnaire -> answer -> governance flow. This includes taking out Vendor Requests, Controls, the standalone Gaps page, and any other pages that are currently misleading or nonsensical in the new product shape. Trust Center stays, but only as a clearly scoped page that fits the current product.

### MVP-003 — Disable or gate legacy backend routers not in MVP

Stop mounting or publicly exposing backend routes that belong to the older controls/compliance pipeline unless they are still required by the new core flow. This reduces confusion, cuts accidental coupling, and prevents the UI from indirectly depending on deprecated logic. Any route that remains temporarily should be behind a feature flag and clearly marked as non-MVP.

### MVP-004 — Define the canonical MVP domain contract

Write down the official domain model for the MVP: Evidence Document, Framework, Subject Area, Questionnaire, Question, Question Signal, Mapping, Answer, and Governance Metric. This contract should define what each object means, where it is created, and which service owns it. The goal is to stop the codebase from drifting between old control-based concepts and the new evidence-native pipeline.

---

## Sprint 1 — Evidence and Questionnaire Intake

### MVP-005 — Make framework selection required during evidence upload

Update the evidence upload flow so users must declare which frameworks a document belongs to before it enters the registry. This makes framework scope an explicit product input instead of something inferred only by AI after the fact. The UI, API, and database path all need to enforce this consistently.

### MVP-006 — Store user-declared vs AI-verified framework metadata separately

Persist framework metadata with provenance so the system can distinguish between what the user declared and what the model later verified or challenged. This matters because the product promise is not "AI guesses everything," but "users define scope and AI refines it." Subject-area tagging should live alongside this so documents can later be matched by both framework and topic.

### MVP-007 — Require framework scope and evidence scope on questionnaire upload

When a questionnaire is uploaded, the user must define which frameworks are relevant and which evidence set the questionnaire is allowed to use. This makes downstream mapping and answer generation deterministic and traceable. It also prevents the system from searching the entire workspace and producing answers from irrelevant evidence.

### MVP-008 — Run passive parse, question detection, and classification on questionnaire ingest

As soon as a questionnaire is uploaded, the system should parse it, detect actual questions, classify each question by framework and subject area, and store those signals automatically. This is the beginning of the passive mapping pipeline and removes the need for a separate "start mapping" mental model. The result should be persisted as first-class data that later powers mapping, answer generation, and governance.

### MVP-009 — Standardize the subject-area taxonomy used across documents and questions

Define one subject taxonomy for both evidence documents and questionnaire questions, so terms like encryption at rest, incident response, access control, and vendor management are represented consistently. Without this, the governance page will be noisy and mapping quality will be unstable because similar ideas will appear under different labels. The taxonomy should be small, understandable, and extendable without rewriting the pipeline.

---

## Sprint 1 — Mapping Pipeline Unification

### MVP-010 — Replace split mapping paths with one canonical mapping pipeline

Retire the old heuristic/control-driven mapping behavior from the normal user flow and standardize on one passive mapping path. That path should use questionnaire framework scope, question-level signals, and selected evidence metadata to produce mappings. The product needs one truth, not a mix of legacy suggestions and newer LLM-based logic.

**Status**: ~70% complete. `compliance_hooks.py`, `control_catalog.py`, `mapping_llm_rerank.py`, 6 dead scripts, 10 dead test files, and all heuristic config paths were deleted in the prior cleanup session (~4,200 lines removed).

### MVP-011 — Refactor mapping review into a clear auto-mapping screen

The mappings screen should present what the system found, why it matched, and where confidence or evidence support is weak. It should no longer look like a leftover manual control-mapping tool from the prior architecture. The goal is a clear operational view of passive auto-mapping, not a confusing side workflow.

### MVP-012 — Enforce selected-evidence-only mapping and retrieval boundaries

Every mapping and answer must be constrained to the evidence set the user selected for that questionnaire. This ensures traceability, avoids accidental leakage from unrelated documents, and keeps the system aligned with the user's chosen compliance context. Boundary enforcement should exist at the API, service, and query levels.

---

## Sprint 2 — Evidence-Grounded Answer Generation

### MVP-013 — Require citation-backed answers or an explicit insufficient-evidence result

The answer pipeline must either produce an answer with real citations to allowed internal evidence or return an honest "insufficient evidence" outcome. This is a foundational trust rule for the product and should be treated as a hard contract, not a best effort. Anything in between creates fake confidence and weakens the product's core value.

### MVP-014 — Simplify review into an exception queue instead of a mandatory human workflow

Review should focus on the exceptions that matter: low-support answers, no-citation answers, parse failures, mapping failures, and user-flagged problems. It should not assume a human must manually approve every normal answer for the product to work. This matches the decision to rely on code verification and autonomous gates rather than manual eyeball-heavy workflows.

### MVP-015 — Preserve citations and traceability in all exports

Exports must carry through the evidence grounding so a generated answer is still traceable once it leaves the app. That includes preserving citations, source references, and enough metadata to understand where the answer came from. An export without traceability breaks the product promise the moment the file is downloaded.

### MVP-016 — Surface job state for parse, tag, map, answer, and export operations

Users need visible status for each asynchronous stage so they can tell whether a questionnaire is parsing, mapping, generating answers, or failed at a specific step. This closes one of the biggest reliability gaps in the current system: silent background failure. The jobs API and UI should speak the same language about progress and failure states.

---

## Sprint 3 — Governance Overhaul

### MVP-017 — Rewrite governance metrics backend around framework and subject demand

Rebuild the backend analytics so governance is driven by the current pipeline rather than legacy controls-era assumptions. The primary metrics should include questionnaire volume by framework, question volume by subject, unanswered rate, low-support rate, and repeated blind spots over time. Governance should reflect what compliance teams actually need to manage, not what the old architecture happened to store.

### MVP-018 — Rebuild the AI Governance page for compliance operations

The AI Governance page should become the operational command view for compliance teams, not a graveyard of inherited charts. It should clearly show what frameworks customers ask about most, where the company lacks evidence depth, and which subject areas keep failing or underperforming. The design should be simplified around decisions a compliance lead would actually make.

### MVP-019 — Fold gap analytics into governance and remove standalone gap concepts

Blind spots and gaps should remain important concepts, but they should live inside Governance rather than on a disconnected standalone page. This keeps the product surface smaller and makes the analytics easier to understand in one place. The backend and UI should use the same definitions for "gap," "low support," and "unanswered."

### MVP-020 — Define governance filters and drill-down behavior

Governance data becomes much more useful when users can filter by timeframe, framework, subject, and questionnaire set. This ticket should define which filters exist, which metrics they affect, and what happens when a user clicks into a problem area. The goal is for governance to move from passive charts to actionable analysis.

### MVP-021 — Keep Trust Center functional but tightly scoped for MVP

Trust Center should remain in the product, but its scope needs to be trimmed to what is actually supported and valuable in the current release. The page should be checked for broken assumptions, dead links, and dependencies on retired systems. It should feel intentional, not like a leftover section that survived cleanup by accident.

---

## Sprint 3 — Reliability, Security, and Cleanup

### MVP-022 — Replace silent failures with visible, typed error handling across the core pipeline

Failures in indexing, tagging, mapping, answer generation, and export should be logged, classified, and surfaced to the user or job status system. The current pattern of swallowing exceptions or logging them too quietly makes debugging and trust impossible. This ticket should remove silent failure behavior from the MVP path entirely.

### MVP-023 — Add robust retry, backoff, and rate-limit handling for LLM calls

Document tagging, question classification, and answer generation all need proper retry logic with exponential backoff and 429-aware handling. The current fixed-delay, low-attempt approach is too weak for real workloads and turns temporary provider limits into product failures. This ticket should also define when a failure becomes terminal and how that is reported.

### MVP-024 — Enforce production-safe environment validation and secret handling

The app must fail fast in production when secrets are placeholders, defaults are insecure, or required environment variables are missing. This closes one of the highest-risk gaps identified in the audit and prevents "it booted, so it must be fine" deployment failures. `.env.example` also needs to be brought up to date so operators know what must be set.

### MVP-025 — Add health checks, restart policies, and resource limits to the deployment stack

Core services need health checks so the system knows whether API, worker, Postgres, and MinIO are actually alive and ready. Restart policies and sensible resource limits reduce the blast radius of crashes, memory leaks, and transient startup issues. This is baseline operational hygiene for an MVP that claims to be secure and scalable.

### MVP-026 — Remove remaining legacy hot paths, dead code hooks, and avoidable performance risks

Any route or service still depending on old control-centric logic or known N+1 patterns should either be removed from MVP or cleaned up before release. The point is not perfection everywhere, but making sure the active product path is clean, predictable, and performant. This ticket should also identify dead configs and stale scripts that mislead future development.

**Status**: ~70% complete. ~4,200 lines of dead heuristic code, scripts, and tests were already removed.

### MVP-027 — Do a frontend quality pass on all MVP pages

Remove stray `console.log` calls, reduce or eliminate explicit `any` usage in MVP pages, and make error/loading/empty states consistent across the core flows. Every important fetch should surface failure clearly instead of silently falling back to empty UI. The result should be a frontend that feels deliberate and trustworthy even before visual polish.

---

## Sprint 4 — Autonomous Verification Gates

### MVP-028 — Add PR-level architecture and quality gates

Every PR should run linting, tests, type checks, build validation, and a few explicit architecture rules. Those rules should block new imports from retired legacy modules into the core pipeline and catch banned patterns like new `console.log` or new unsafe typing in MVP pages. This keeps cleanup from being undone as the codebase continues moving.

### MVP-029 — Add a seeded end-to-end integration gate for the core pipeline

Create a deterministic seeded workflow that spins up the stack, loads fixture evidence and a questionnaire, and verifies the full path from upload to export. This should test parse -> classify -> map -> answer -> export with assertions at each stage. It becomes the primary proof that the product still works as a system, not just as isolated units.

### MVP-030 — Add governance seed assertions tied to real pipeline outputs

Governance should have seeded test data and expected outputs so the charts and metrics can be validated automatically. This prevents the analytics layer from drifting into nonsense again as the pipeline changes underneath it. The tests should assert that framework demand, subject demand, and blind-spot counts are computed from the new canonical data model.

### MVP-031 — Add nightly live-model, failure-injection, and scale smoke tests

Nightly automation should run a small live-model smoke test, inject retryable failures like timeouts or 429s, and execute a representative large questionnaire workload. This is the right place to validate that the AI pipeline still behaves correctly under real-world conditions without slowing down every PR. It also gives an ongoing signal about reliability, grounding, and throughput as the system evolves.

---

## Implementation Order

```
Sprint 0: MVP-001 → MVP-004  (scope lock)
Sprint 1: MVP-005 → MVP-012  (intake + mapping)
Sprint 2: MVP-013 → MVP-016  (answers + jobs)
Sprint 3: MVP-017 → MVP-027  (governance + reliability)
Sprint 4: MVP-028 → MVP-031  (verification gates)
```
