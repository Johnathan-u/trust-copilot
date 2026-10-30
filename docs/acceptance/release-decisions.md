# Release decisions and change control (TC-01-006)

Status: **ACTIVE**. Baseline: `c20f949`. Adopted 2026-10-27 by the Trust Copilot Coordinator. OD-2 is decided (2026-10-27). OD-1 is an owner statement (2026-10-27) and still needs a signed declaration. The other Owner/seller entries below are **pending**.

The ticket file proposes the name `docs/acceptance/decision-control.md`. This repo uses the coordinator brief's name, `release-decisions.md`, which covers the same scope. `decision-control.md` should be read as an alias for this file.

## 1. Decision owners

### Coordinator succession — 2026-10-30

The owner authorized Codex to take over the autonomous engineering workflow,
including assignment, implementation, independent review, CI repair and merges.
The **Codex coordinator** now fills the Coordinator bot role below, replacing the
dependency on an active Grok coordinator. Routine engineering decisions and
qualified merges require no additional owner approval. Implementing workers do
not self-merge; coordinator-authored changes require an independent reviewer.
Issue #85 records adoption and remains the live ledger. The run protocol is
`docs/release/CODEX_AUTONOMY.md`. Earlier handoff/session-only restrictions are
superseded by this authorization. Owner-only domains and release evidence gates
remain as listed below; they do not prevent unrelated engineering progress.

There are two accountable decision owners. Every decision in the release belongs to exactly one of them.

| Domain | Decision owner (role) | Person | Decides | Does not decide |
|---|---|---|---|---|
| **Legal** | Owner/seller (with counsel as engaged) | Johnathan | Chain of title, third-party licenses (e.g. PyMuPDF), framework content rights, privacy/terms/DPA text, retention and erasure policy, case-study and testimonial consent, legal holds | Technical design |
| **Rights and IP** | Owner/seller | Johnathan | Asset ownership, what may be redistributed, domain and brand ownership | |
| **Spend** | Owner/seller | Johnathan | Any recurring or one-off cost: model spend cap, provider subscriptions, sandbox accounts, hosting, paid tools | |
| **Accounts** | Owner/seller | Johnathan | Creating or owning third-party accounts (Stripe, GA4, Search Console, Google/Microsoft/Slack apps, cloud sandboxes, ID.me, HRIS vendor), and the domain and sending identity | |
| **Sale and buyer terms** | Owner/seller | Johnathan | Pricing and promotions, buyer terms, acceptance criteria agreed with a buyer (TC-30-005), handover support cap, public claims about customers or traction | |
| **Product scope** | Trust Copilot Coordinator | Coordinator bot | Scope freeze (`scope-freeze.md`), in/out-of-scope rulings, ticket creation, splitting, and dependency edges, change-control approvals within §2 | Expanding spend, terms, or rights (escalates to Owner) |
| **Technical rulings** | Trust Copilot Coordinator | Coordinator bot | Architecture, contracts, test and acceptance sufficiency for engineering tickets, release-candidate technical gating (G1–G4) | Rights gating (G0/G5 rights items are Owner) |
| **Security** | Trust Copilot Coordinator (technical), Owner/seller (risk acceptance) | Coordinator / Johnathan | Coordinator: security design, findings triage, fix sufficiency. Owner: accepting any residual risk that ships, and choosing the independent reviewer (cost) | |
| **Merges** | Trust Copilot Coordinator | Coordinator bot | Review and merge of all PRs to `master`. Implementing agents never self-merge. | |
| **Domain** (product domain and data, e.g. tenancy, retention defaults) | Coordinator proposes, Owner approves where legal or policy | Coordinator / Johnathan | | |
| **Buyer** | Owner/seller | Johnathan | Buyer communications, diligence disclosures, final buyer signoff process (E30) | |

Escalation: implementing agents ask the **Coordinator**, not the Owner. The Coordinator escalates to the Owner only for the Owner domains above, batched through the §3 log.

## 2. Change-control rule

1. **Newly discovered scope needs a linked ticket, an estimate, and a dependency before any completion claim.** This covers a runtime-discovered route, an unadvertised provider path, a security finding, a missing UI workflow, or a defect outside a ticket's acceptance. Concretely, before any ticket, epic, or release is reported Done:
   - a backlog ticket ID exists for the new work (`TC-EE-NNN`, in the owning epic per `scope-freeze.md`);
   - it has a provisional Fibonacci estimate (1/2/3/5/8; split if > 8);
   - its `depends_on` edges are set, and any ticket it blocks lists it;
   - the PR, finding, or report that discovered it links the ticket.
2. **No silent scope reduction.** Disabling, hiding, or removing a feature never counts as completion. Reducing scope needs an Owner decision logged in §3 and matching updates to `scope-freeze.md`, `claims-register.md`, UI, APIs, docs, and listing.
3. **No completion claim without acceptance evidence.** A ticket is Done only with its `artifacts/acceptance/<ticket>/` evidence and Coordinator review. Real-provider promises need real sandbox evidence. Mocks prove control paths only.
4. **Who approves what.**
   - The Coordinator approves additions that fit within frozen scope and need no new spend, account, rights, or terms.
   - Anything that adds spend, needs a new account, touches rights or legal text, changes pricing or buyer terms, or moves an out-of-scope item (scope-freeze §7) into scope needs an **Owner decision** first.
5. **Record.** Every scope or technical ruling is recorded in §4 with date, owner, and the affected tickets. Owner decisions are recorded in §3.

## 3. Owner/seller decisions log

OD-2 is **DECIDED 2026-10-27**. OD-1 is an **OWNER STATEMENT 2026-10-27**; a signed declaration is still needed at closing (TC-01-002). The other rows are not decided yet. Engineering continues where §5 of each row allows. A gated item cannot be marked release-qualified until its decision is recorded here with a date.

| # | Decision | Owner | Why it is needed / current state at baseline | Blocks (tickets / gate) | Status |
|---|---|---|---|---|---|
| OD-1 | **Chain of title**: confirm sole authorship or assignments for all code and assets, including AI-assisted and contractor work | Owner/seller | Owner statement 2026-10-27: the owner states they wrote the entire codebase personally, on their own time and equipment, with no employer involvement. A signed declaration is still needed at closing (TC-01-002). | TC-01-002 → TC-01-003/004, TC-29-006, TC-30-004; **G0, G5** | OWNER STATEMENT 2026-10-27 |
| OD-2 | **PyMuPDF license path**: buy an Artifex commercial license, accept AGPL obligations, or replace it (e.g. pypdf/pdfplumber) | Owner/seller (cost and legal), with Coordinator technical input | Decided 2026-10-27: replace with a permissive library (implemented as TC-01-003a by Core). Baseline: `apps/api/pyproject.toml:27` depends on `pymupdf` (AGPL-3.0 or commercial), used in `services/evidence_parser.py` and `services/pdf_questionnaire_parser.py`. | TC-01-003, TC-02-002, TC-09-007/008, TC-01-004; **G0, G5**. Per scope-freeze R4, engineering may start behind an interface. | DECIDED 2026-10-27 |
| OD-3 | **Framework content rights** for SOC 2, HIPAA, ISO 27001, NIST CSF 2, NIST 800-53 r5, NIST 800-171 r3, SIG, CAIQ, HITRUST: what may ship (licensed text, public-domain, reference IDs only) | Owner/seller | Several catalogs are proprietary. New ticket **TC-01-007** (scope-freeze R3). | TC-01-007 → TC-21-001, TC-21-014..022; **G0, G5** | PENDING |
| OD-4 | **HRIS vendor** for the one concrete HRIS adapter | Owner/seller (account and cost), Coordinator (technical shortlist) | The generic `hris` collector in `cloud_connector_service.py` has no real vendor. | TC-20-005 → TC-20-006/007 | PENDING |
| OD-5 | **Provider sandbox accounts** (AWS, GCP, Azure, GitHub org, GitLab, Okta, Google Workspace, Jira, Slack, Gmail OAuth verification, Salesforce, HubSpot, Microsoft/Google/GitHub/OIDC/ID.me login, Stripe) | Owner/seller | Real-provider tickets need sandbox evidence. Without accounts they are BLOCKED, never passed. Buyer-transferable ownership is preferred (TC-30-001). | E05, E19, E20, E24 qualification tickets | PENDING |
| OD-6 | **Model spend cap**: finite ceiling for development, holdout evaluation, and per-workspace production budgets | Owner/seller | The spec requires a finite cap before any real model call. No real call is authorized by the backlog. | TC-11-002, TC-11-008, TC-11-009, TC-24-005, TC-27-004 | PENDING |
| OD-7 | **GA4 property and production domain** (buyer-transferable property, canonical domain, sending domain, `security@` mailbox) | Owner/seller | No GA4 at baseline. `security_page_service.py` advertises `security@trustcopilot.io`. Domain ownership is unconfirmed. | TC-26-002..012, TC-15-063, TC-27-008, TC-30-004 | PENDING |
| OD-8 | **Pricing**: (a) list price, currently $25/mo or $250/yr; (b) the **expired promotion** "Free until April 5, 2026" (`billing.py:16` stops the trial after 2026-04-05; the web copy is removed in TC-01-005); (c) whether any new trial or promo exists; (d) **ROI calculator default `subscription_monthly = 399.0`** (`roi_calculator_service.py:9`), which contradicts the $25 price | Owner/seller | Public pricing and ROI output must agree with billing. The Coordinator will not pick a price. | TC-24-002, TC-24-004, TC-15-002, TC-15-003, TC-25-004; claims-register A6/B2/B3 | PENDING |
| OD-9 | **Case-study and testimonial consent**: whether any real customer will be cited, and the consent form and retention | Owner/seller | None exist at baseline (claims-register A1). Publication needs recorded consent. | TC-25-005, TC-26-015 | PENDING |
| OD-10 | **Retention and erasure policy** (backup expiry, default 30 days proposed; legal hold) | Owner/seller (counsel) | PRODUCT_SPEC §Evidence requires owner and counsel approval of actual retention | TC-08-008, TC-27-002 | PENDING (added by Coordinator from spec) |

Recording format once decided: change Status to `DECIDED YYYY-MM-DD`, then add the decision text, the decider, and the evidence link (signed doc, receipt, or account ID reference, never a secret). Then update the affected tickets.

## 4. Coordinator rulings log

| Date | Ruling | Affected | Reference |
|---|---|---|---|
| 2026-10-27 | Scope frozen: 94 routes, 33 pages, 15 dispatcher rows, 24 providers; out-of-scope list | All epics | `scope-freeze.md` |
| 2026-10-27 | R1: TC-12-004 depends on TC-12-002 and TC-12-003 | TC-12-004 | `scope-freeze.md` §8 |
| 2026-10-27 | R2: TC-26-018 no longer depends on TC-24-005 | TC-26-018 | `scope-freeze.md` §8 |
| 2026-10-27 | R3: new ticket TC-01-007 (framework content rights, Owner decision OD-3) | E01, TC-21-001, TC-21-014..022 | `scope-freeze.md` §8 |
| 2026-10-27 | R4: E01 legal tickets gate release (G0/G5), not engineering start | TC-02-002, TC-09-007/008, TC-21-001, TC-21-014..022 | `scope-freeze.md` §8 |
| 2026-10-27 | Filename ruling: `scope-freeze.md`, `release-decisions.md`, and `claims-register.md` are the canonical acceptance docs. The ticket-proposed names `scope-contract.md` and `decision-control.md` are aliases. | TC-01-001, TC-01-006 | this file |

## Shared progress reporting — owner request, 2026-10-30

The owner requested a repository HTML/CSS information radiator for humans and AI,
with Grok and Codex PM adoption. TC-01-006a implements this bounded operational
child (5 provisional points, excluded from the frozen original denominator).
The authoritative scope remains the original planning package; recorded current
state is `docs/planning/backlog-state.json`, displayed by `docs/tracker/index.html`.
Both PMs follow `docs/release/PM_BACKLOG_PROTOCOL.md` after each meaningful batch.

The single headline measure is accepted original-parent points / 1,864 after
baseline verification. Until then, report the baseline as pending. Child work,
epics, merged PRs and artifact presence do not automatically earn points. Record
scope changes explicitly with a new version; retain open release/owner gates.
Issue #85 remains the assignment/decision ledger. The coordinator lease,
independent review, exact-head CI and all owner-only decisions remain in force.

## 5. Acceptance mapping

- **TC-01-006-AC1** (product, domain, security, legal, and buyer decision owners named by role): §1.
- **TC-01-006-AC2** (new scope gets a linked ticket, estimate, and dependency before any completion claim): §2 rule 1, enforced at Coordinator review and merge.
