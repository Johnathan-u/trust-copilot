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
not self-merge except as OD-15 allows; coordinator-authored changes require an independent reviewer.
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
| **Security** | Trust Copilot Coordinator (technical), Owner/seller (risk acceptance) | Coordinator / Johnathan | Coordinator: security design, findings triage, fix sufficiency. Owner: accepting any residual risk that ships, and choosing the independent reviewer (cost). Under OD-14 the owner's residual-risk acceptance is given when the Coordinator concurs with an independently reviewed default. | |
| **Merges** | Trust Copilot Coordinator | Coordinator bot | Review and merge of PRs to `master`. Implementing agents do not self-merge, except as OD-15 allows: the worker Grok may merge its own green PRs, except for account, authentication, authorization and evidence-gate work (standing-queue groups 0 and 1). Acceptance always needs the Coordinator's independent review, after the merge if the PR was self-merged. | |
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

OD-2 is **DECIDED 2026-10-27**. OD-11 is **DECIDED 2026-11-02**. OD-12 is **DECIDED 2026-11-05**. OD-13 and OD-14 are **DECIDED 2026-11-06**. OD-15 is **DECIDED 2026-11-10**. OD-1 is an **OWNER STATEMENT 2026-10-27**; a signed declaration is still needed at closing (TC-01-002). The other rows are not decided yet. Engineering continues where §5 of each row allows. A gated item cannot be marked release-qualified until its decision is recorded here with a date.

| # | Decision | Owner | Why it is needed / current state at baseline | Blocks (tickets / gate) | Status |
|---|---|---|---|---|---|
| OD-1 | **Chain of title**: confirm sole authorship or assignments for all code and assets, including AI-assisted and contractor work | Owner/seller | Owner statement 2026-10-27: the owner states they wrote the entire codebase personally, on their own time and equipment, with no employer involvement. A signed declaration is still needed at closing (TC-01-002). | TC-01-002 → TC-01-003/004, TC-29-006, TC-30-004; **G0, G5** | OWNER STATEMENT 2026-10-27 |
| OD-2 | **PyMuPDF license path**: buy an Artifex commercial license, accept AGPL obligations, or replace it (e.g. pypdf/pdfplumber) | Owner/seller (cost and legal), with Coordinator technical input | Decided 2026-10-27: replace with a permissive library (implemented as TC-01-003a by Core). Baseline: `apps/api/pyproject.toml:27` depends on `pymupdf` (AGPL-3.0 or commercial), used in `services/evidence_parser.py` and `services/pdf_questionnaire_parser.py`. | TC-01-003, TC-02-002, TC-09-007/008, TC-01-004; **G0, G5**. Per scope-freeze R4, engineering may start behind an interface. | DECIDED 2026-10-27 |
| OD-3 | **Framework content rights** for SOC 2, HIPAA, ISO 27001, NIST CSF 2, NIST 800-53 r5, NIST 800-171 r3, SIG, CAIQ, HITRUST: what may ship (licensed text, public-domain, reference IDs only) | Owner/seller | Several catalogs are proprietary. New ticket **TC-01-007** (scope-freeze R3). | TC-01-007 → TC-21-001, TC-21-014..022; **G0, G5** | PENDING |
| OD-4 | **HRIS vendor** for the one concrete HRIS adapter | Owner/seller (account and cost), Coordinator (technical shortlist) | The generic `hris` collector in `cloud_connector_service.py` has no real vendor. | TC-20-005 → TC-20-006/007 | PENDING |
| OD-5 | **Provider sandbox accounts** (AWS, GCP, Azure, GitHub org, GitLab, Okta, Google Workspace, Jira, Slack, Gmail OAuth verification, Salesforce, HubSpot, Microsoft/Google/GitHub/OIDC/ID.me login, Stripe) | Owner/seller | Real-provider tickets need sandbox evidence. Without accounts they are BLOCKED, never passed. Buyer-transferable ownership is preferred (TC-30-001). | E05, E19, E20, E24 qualification tickets | PENDING |
| OD-6 | **Model spend cap**: finite ceiling for development, holdout evaluation, and per-workspace production budgets | Owner/seller | The spec requires a finite cap before any real model call. No real call is authorized by the backlog. | TC-11-002, TC-11-008, TC-11-009, TC-24-005, TC-27-004 | PENDING |
| OD-7 | **GA4 property and production domain** (buyer-transferable property, canonical domain, sending domain, `security@` mailbox) | Owner/seller | No GA4 at baseline. Since TC-17-003 the security page shows no contact address until an owner approves one (`security_contact` claim). Domain ownership is unconfirmed. | TC-26-002..012, TC-15-063, TC-27-008, TC-30-004 | PENDING |
| OD-8 | **Pricing**: (a) list price, currently $25/mo or $250/yr; (b) the **expired promotion** "Free until April 5, 2026" (`billing.py:16` stops the trial after 2026-04-05; the web copy is removed in TC-01-005); (c) whether any new trial or promo exists; (d) **ROI calculator default `subscription_monthly = 399.0`** (`roi_calculator_service.py:9`), which contradicts the $25 price | Owner/seller | Public pricing and ROI output must agree with billing. The Coordinator will not pick a price. | TC-24-002, TC-24-004, TC-15-002, TC-15-003, TC-25-004; claims-register A6/B2/B3 | PENDING |
| OD-9 | **Case-study and testimonial consent**: whether any real customer will be cited, and the consent form and retention | Owner/seller | None exist at baseline (claims-register A1). Publication needs recorded consent. | TC-25-005, TC-26-015 | PENDING |
| OD-10 | **Retention and erasure policy** (backup expiry, default 30 days proposed; legal hold) | Owner/seller (counsel) | PRODUCT_SPEC §Evidence requires owner and counsel approval of actual retention | TC-08-008, TC-27-002 | PENDING (added by Coordinator from spec) |
| OD-11 | **Post-freeze scope additions**: bring epics E31–E37 into the scope record, including the §7 out-of-scope items they move in (DORA, NIS2 and AI-Act question packs; Google Drive and Confluence; EU-region hosting; the device agent; the browser extension), and set their release order | Owner/seller | Decided 2026-11-02 by Johnathan Reinhart. It started from the owner's instruction "its out of date -- go thru everything and add it and resolve" ([instruction](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6584748710), [confirmation](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6585029126)). The owner confirmed on 2026-11-02 in the working session, answering an explicit sign-off question about PR #173 (answer: "Approve, drop the gates"): he signs off the amended freeze, approves E31–E37 into scope, and drops the planned approval checkpoints in TC-32-011 (after the Nov 30 go/kill decision) and TC-34-012 (Feb 15, 2027). Approved tickets may start on their Jira dates. Recorded in `scope-freeze.md` §11. It also records the approvals asked for in TC-32-011 (Jira SCRUM-450) and TC-34-012 (SCRUM-476). Release order: v1.0 Dec 15, 2026 = frozen inventory + E35 + E36 + TC-32-010; v1.1 by May 28, 2027 = rest of E32 (including TC-32-001) + E37 TrustCopilot integration; v2.0 by Dec 17, 2027 = E34. E37's parsing API is a separate product (`pdf-engine` repo). The original 1,864-point denominator is unchanged. Decisions still open inside these epics stay open: TC-32-008, TC-35-012, TC-36-005, TC-37-041, TC-31-015, OD-3. | E31–E37; TC-32-011, TC-34-012 | DECIDED 2026-11-02 |
| OD-12 | **Restrictive licences other than PyMuPDF** (TC-01-003-AC1): the path for every remaining non-permissive dependency or bundled service | Owner/seller (legal), with Coordinator technical input | Decided 2026-11-05 by Johnathan Reinhart in the working session, approving the Coordinator's recommendation (answer: "yes i agree"). A scan of the shipped stack found MinIO (AGPL-3.0) in `docker-compose.prod.yml`: it is **removed from production**, which now uses an external S3-compatible service (`S3_ENDPOINT`, new `S3_REGION`); MinIO stays in the dev compose file only. psycopg2-binary (LGPL), certifi (MPL-2.0), sharp/libvips (LGPL) and caniuse-lite (CC-BY-4.0) ship unmodified with their notices. No outside counsel was engaged. Record: `license-resolution.md`; implemented in [#175](https://github.com/Johnathan-u/trust-copilot/pull/175). | TC-01-003; **G0, G5** | DECIDED 2026-11-05 |
| OD-13 | **Key custody and residual key risk** (TC-07-002 owner sign-off) | Owner/seller (security risk acceptance), with Coordinator technical input | Decided 2026-11-06 by Johnathan Reinhart in the working session ("i sign off on all if we concur"), accepting the defaults the Coordinator (Claude) recommended and concurs with: (1) keyrings stay in environment variables for v1.0, KMS or a secret manager is a later option; (2) production must set `SESSION_KEYRING`, `OAUTH_STATE_KEYRING`, `MFA_KEYRING` and `CONNECTOR_KEYRING` with four distinct values instead of deriving them from `SESSION_SECRET` (enforcement: follow-up TC-07-002a, Jira SCRUM-551); (3) a production rotation runs the rotation tool on a copy, because the tool refuses production; the cut-over procedure is written in TC-07-002a's runbook; (4) a locked-out sole workspace admin has no in-product recovery and there is no keyring backup: both are accepted v1.0 limitations, covered by the TC-07-002a operator runbook. Review evidence: [#180 review](https://github.com/Johnathan-u/trust-copilot/pull/180#issuecomment-6671755163); recorded in [#183](https://github.com/Johnathan-u/trust-copilot/pull/183). | TC-07-002, TC-07-002a | DECIDED 2026-11-06 |
| OD-14 | **Standing delegation of concurring sign-offs** | Owner/seller | Decided 2026-11-06 by Johnathan Reinhart in the working session ("i sign off on all if we concur"), answering the Coordinator's offer to record a standing rule for sign-offs like TC-07-002's. **Scope:** owner sign-off steps on engineering tickets that concern security risk acceptance, engineering exceptions or test-scope choices (for example key custody, how a verification baseline is produced, a manual instead of a scheduled test job), where the Coordinator (Claude) concurs with an independently reviewed recommended default. The Coordinator records the sign-off, closes the item and lists it in the next progress report so the owner can overrule it. **Excluded, still decided by the owner each time:** every Owner/seller domain in §1 (Legal; Rights and IP; Spend; Accounts, including the domain and sending identity; Sale and buyer terms, including the handover support cap; Buyer communications, diligence disclosures and final buyer signoff; Domain decisions that are legal or policy), §2 rules 2 and 4 (scope reductions; moving out-of-scope items into scope), public claims, and anything irreversible. The Coordinator never concurs with its own unreviewed work. Recorded in [#183](https://github.com/Johnathan-u/trust-copilot/pull/183). | Engineering tickets with an owner sign-off step | DECIDED 2026-11-06 |
| OD-15 | **Worker self-merge** | Owner/seller | Decided 2026-11-10 by Johnathan Reinhart in the working session ("also give grok permission to approve and merge itself so it can be fully auntinimou" [sic: autonomous]). The Coordinator (Claude) advised two things: self-merged work cannot count as accepted, because each ticket's DoD needs a reviewer other than the implementer; and the security groups should keep pre-merge review. The Coordinator's worker prompt included a line the owner could delete for full autonomy: "Recommended exception (delete this line for full autonomy): for queue groups 0 and 1 (#193 and the security tickets), don't merge." The owner did not say whether he kept it. The worker's sitrep, which the owner forwarded, says it did not merge groups 0 and 1 "because groups 0 and 1 need your approval first". This record therefore treats the exception as kept; the owner can overrule. The owner did not respond to the advice on acceptance, so acceptance stays with the Coordinator under §2 rule 3 and each ticket's DoD. **Terms, from the Coordinator's worker prompt that the owner sent:** (1) the worker (Grok) may squash-merge its own PR, pinned to a head SHA whose `build` and `web-release-e2e` jobs are green on both push and pull_request; it never merges red, skipped or running CI, never force-pushes master and never bypasses checks; (2) after each merge it watches master CI. If master goes red, it opens a revert PR of its own merge and may self-merge that pure revert once it is green on both events. This is the only exception to the AGENTS.md rule that a repair PR on a red master needs independent review. The fix then goes on a new branch; (3) **exception:** standing-queue groups 0 and 1 (#193 / TC-04-001, TC-21-002, TC-21-003, TC-04-004, TC-06-001) are not self-merged. They wait for the Coordinator's review, not the owner's. The Coordinator also applies the same pre-merge review to any other account, authentication, authorization or evidence-gate work, a wider reading the owner has not confirmed; (4) the worker never edits the tracker, Jira or backlog snapshots, and never marks work accepted. **Acceptance:** the Coordinator reviews self-merged PRs after merge and records acceptance only then. A gap found after merge is fixed before new work, and a security hole is reverted first. The tracker notes which tickets were reviewed after merge. **Release gating:** no release candidate is cut while master contains a self-merged PR not yet independently reviewed. Recorded in [#199](https://github.com/Johnathan-u/trust-copilot/pull/199). | Implementation PRs by the worker | DECIDED 2026-11-10 |

Recording format once decided: change Status to `DECIDED YYYY-MM-DD`, then add the decision text, the decider, and the evidence link (signed doc, receipt, or account ID reference, never a secret). Then update the affected tickets.

## 4. Coordinator rulings log

| Date | Ruling | Affected | Reference |
|---|---|---|---|
| 2026-10-27 | Scope frozen: 94 routes, 33 pages, 15 dispatcher rows, 24 providers; out-of-scope list | All epics | `scope-freeze.md` |
| 2026-10-27 | R1: TC-12-004 depends on TC-12-002 and TC-12-003 | TC-12-004 | `scope-freeze.md` §8 |
| 2026-10-27 | R2: TC-26-018 no longer depends on TC-24-005 | TC-26-018 | `scope-freeze.md` §8 |
| 2026-10-27 | R3: new ticket TC-01-007 (framework content rights, Owner decision OD-3) | E01, TC-21-001, TC-21-014..022 | `scope-freeze.md` §8 |
| 2026-10-27 | R4: E01 legal tickets gate release (G0/G5), not engineering start | TC-02-002, TC-09-007/008, TC-21-001, TC-21-014..022 | `scope-freeze.md` §8 |
| 2026-11-02 | Scope-freeze amendment: inventory reconciled to master `574f2e2`. 94 route modules, unchanged; 531 static operations (+34 in 15 modules, all from in-scope tickets); 44 page routes (+10 pages; `/dashboard/vendor-requests` was already a redirect at baseline and is now a server redirect (TC-15-024), not a reduction); 19 dispatcher rows (+4); 24 providers, unchanged | All epics | `scope-freeze.md` §3–§6 |
| 2026-11-02 | PF-1: post-freeze epics E31–E37 recorded with release targets (v1.0, v1.1, v2.0, separate product, go-to-market), per OD-11. Added work stays outside the 1,864-point original denominator | E31–E37 | `scope-freeze.md` §11 |
| 2026-11-05 | Licence resolution (TC-01-003, OD-12): production compose bundles no MinIO; a release test keeps the shipped images and runtime dependency licences matched to `license-resolution.md` | TC-01-003 | `license-resolution.md` |
| 2026-11-06 | TC-07-002 accepted after owner sign-off (OD-13); follow-up TC-07-002a (SCRUM-551) added for distinct production keyrings and the key and recovery runbook; standing delegation of concurring sign-offs recorded (OD-14) | TC-07-002, TC-07-002a | §3 OD-13, OD-14 |
| 2026-11-10 | Worker self-merge allowed except for account, authentication, authorization and evidence-gate work (groups 0 and 1); acceptance still needs independent review (OD-15) | Worker PRs | §3 OD-15 |
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
