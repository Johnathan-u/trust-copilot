# Claims register (TC-01-005)

Baseline: `c20f949` (master). Branch: `tc/coord/TC-01-005`. Last reviewed: 2026-10-27. A4 was updated on `tc/ca/TC-25-005` after master (including PR #2) was merged into that branch.

This file lists every capability, traction, customer, testimonial, revenue, pricing, security, and compliance claim found in `README.md`, the public web pages (`/`, `/pricing`, `/checkout`, root metadata), and API copy that is returned to users. Each claim has one status.

## Status definitions

| Status | Meaning |
|---|---|
| **Supported** | A passing acceptance result is linked (`artifacts/acceptance/<ticket>/`). Baseline count was 0. A row is Supported only for the part the linked evidence actually covers. |
| **Withheld pending _ticket_** | The feature exists in code, but the claim is **not release-qualified**. The copy is kept only as a plain, non-absolute product description, with no guarantee, metric, or certification language. It may not appear in sales or buyer material as a verified capability until the linked ticket's acceptance passes and this row moves to Supported. |
| **Removed** | The claim was deleted or reworded in this PR because it was false, unverifiable, absolute ("never", "no hallucinations"), expired, or pointed at material that does not exist. |
| **Labeled example** | Synthetic or heuristic data that could pass as real. It now carries an explicit example, illustrative, or heuristic label in the source and output. |

Line numbers in the **Location** column refer to this branch, after the edit. For Removed rows, `@c20f949` gives the baseline line.

## A. Traction, customers, testimonials, revenue

| # | Location | Claim | Status | Ticket |
|---|---|---|---|---|
| A1 | (whole repo) | Customer logos, customer counts, testimonials, "trusted by", usage or traction numbers | **None found.** Nothing to remove. Do not add any without signed consent and evidence. | TC-25-005, TC-26-015 |
| A2 | `apps/api/app/services/crm_connector_service.py:23,32,73` (`@c20f949` :23,:32,:73) | Mock CRM sync inserts deals as real `Deal` rows: "Acme Corp" $150,000 ARR, "Globex Industries", "StartupCo" $45,000. These feed `/api/deals/revenue-unblocked` and risk ranking as if they were real pipeline revenue. | **Labeled example.** Company names now end in "(example data)". Sync responses include `"mock": true, "data_basis": "synthetic_example"`. Docstrings say the deals are synthetic. Real sync is withheld. | TC-20-049..054, TC-15-049 |
| A3 | `apps/api/app/services/deal_analytics_service.py:54-67`, `revenue_risk_service.py:49-59` | "Revenue unblocked" and "revenue at risk" amounts | **Withheld.** These are heuristic, user-data-derived numbers, not traction. They must not appear in marketing. | TC-23-008 |
| A4 | `apps/api/app/services/case_study_service.py:55-97`; workflow in `apps/api/app/api/routes/case_studies.py` | naming an organization is a customer claim and requires consent before publishing. | **Supported** for the blank template and the consent gate only. The template is `data_basis: blank_template` and `customer_claim: false`, and its notice says it contains no customer, quote, or result. `hours_saved` and the other suggested metrics are field names (`metrics_are_field_names_not_results: true`), not measured results. Publish checks that every quoted organization has consented and that the consent permits every quoted result. Naming an organization is a customer claim and requires consent before publishing. Synthetic rows stay `synthetic_example` with `customer_claim: false`. No seed inserts a case study. Evidence: `tests/release/test_domain_case_studies.py`, `tests/test_case_studies.py`, and `artifacts/acceptance/TC-25-005/`. **Withheld** beyond that. `consent_reference` is an operator string, not a signed document (TC-26-015). Reviewer signoff other than the implementer is still open. This change publishes no real customer name, logo, quote, or result. Per-org attribution (each result belonging to one organization) is follow-up TC-25-005a and is not part of this row. | TC-25-005, TC-26-015, TC-25-005a |
| A5 | `apps/api/app/services/roi_calculator_service.py:15,49-58` (`@c20f949` :15) | ROI output shows `time_reduction_pct` above 90%, `roi_multiple`, and dollars saved, based on a hardcoded 0.5 h per questionnaire. The route is public. | **Labeled example.** Output adds `estimate_basis: {type: "illustrative", ...}` with "Not measured customer results." | TC-25-004 |
| A6 | `apps/api/app/services/roi_calculator_service.py:9` | Default `subscription_monthly = 399.0` contradicts the public $25/mo price | **Withheld pending owner pricing decision.** Not changed because pricing is an owner decision (see release-decisions log). | TC-25-004, TC-01-006 (pricing) |
| A7 | `apps/api/app/services/proof_widgets_service.py:45,52-54` | `hours_saved_estimate` is answers × 0.08 h | **Labeled example.** Adds `hours_saved_basis: "heuristic ... not measured"`. | TC-23-005 |
| A8 | `apps/api/app/services/demo_proof_service.py:27-28, 30-120, 141-164` | "Sample SOC 2 Security Questionnaire" with hardcoded confidence values (78–97), plus coverage report and gap list derived from them. The package was described as "for sales". | **Labeled example.** All outputs carry `data_basis: "synthetic_example"` and `disclaimer`. The questionnaire also carries `confidence_basis: "illustrative hardcoded values, not model output"`. The "for sales" wording was removed. | TC-25-011, TC-11-006 |
| A9 | `apps/api/app/services/demo_proof_service.py:70` (`@c20f949` :58) | "Isolation is validated by automated integration tests." | **Removed.** No such qualified test evidence exists. | TC-06-005 |
| A10 | `apps/api/app/services/demo_proof_service.py:30-120` | Sample answers state AES-256 at rest, DigitalOcean managed-DB encryption, TLS 1.2+, Sentry/Prometheus | **Labeled example.** Covered by the synthetic disclaimer. Deployment facts are unverified. | TC-27-008, TC-20-010, TC-25-011 |
| A11 | `apps/api/app/services/ai_insights.py:143,162` | Average "confidence" percentages | **Withheld.** These are heuristic model scores, not accuracy. | TC-11-006, TC-21-012 |

## B. Pricing and commercial terms

| # | Location | Claim | Status | Ticket |
|---|---|---|---|---|
| B1 | `apps/web/app/page.tsx` @c20f949:108-109,112; `pricing/page.tsx` @c20f949:85-86; `checkout/page.tsx` @c20f949:225,227,249,251,276,278,291,419 | "~~$25~~ FREE", "Free until April 5, 2026", "No charge until April 5, 2026", "Card will be requested after April 5" | **Removed.** The promotion expired on 2026-04-05. `billing.py:16,83` stops adding a trial after that date, so the copy told buyers they were not being charged when they would be. The pages now show the existing list price ($25/mo, $250/yr) with no new terms. | TC-24-002, TC-15-002, TC-15-003 |
| B2 | `apps/web/app/page.tsx:175,274`; `pricing/page.tsx:83-85`; `checkout/page.tsx:224,247`; `dashboard/settings/page.tsx:57,77` | Price $25/month or $250/year, "Save $50/year" | **Withheld pending owner pricing decision.** Unchanged list price. | TC-24-002; owner decision (release-decisions.md) |
| B3 | `apps/web/app/page.tsx:84`; `pricing/page.tsx:53` | "No tiers, no feature gates, no per-seat pricing" / "No per-seat charges" | **Withheld pending owner pricing decision and entitlement enforcement** | TC-24-004 |
| B4 | `apps/web/app/page.tsx:114`; `pricing/page.tsx:90`; `checkout/page.tsx:259` | "Unlimited questionnaire uploads" | **Withheld.** Plan limits are not yet defined or enforced. | TC-24-004 |
| B5 | `apps/web/app/page.tsx:111`; `pricing/page.tsx:86,119`; `checkout/page.tsx:222,245` | "Cancel anytime", "retain access through the end of your billing period" | **Withheld** | TC-24-002 |
| B6 | `apps/web/app/page.tsx:181`; `pricing/page.tsx:120` | "No credit card required to explore the demo"; demo workspace with sample data | **Withheld.** "Explore the full product" was reworded to "explore the product". | TC-29-005 |

## C. Capability claims (web and README)

| # | Location | Claim | Status | Ticket |
|---|---|---|---|---|
| C1 | `apps/web/app/layout.tsx:10`; `page.tsx:171`; `pricing/page.tsx:117` (`@c20f949` layout:10, page:173, pricing:117) | "grounded in your real evidence — not hallucinations" / "not generic text or hallucinations" | **Removed.** Reworded to "AI-drafted answers that cite your uploaded evidence, for your team to review". | TC-11-003, TC-11-005, TC-11-008 |
| C2 | `page.tsx:213` (`@c20f949` :215) | "Every AI answer cites real evidence... No hallucinations, no generic text." | **Removed.** Reworded to "reference the evidence retrieved... so reviewers can verify each one". | TC-11-003, TC-12-010 |
| C3 | `page.tsx:115,166,213,242`; `pricing/page.tsx:91`; `checkout/page.tsx:260`; `README.md:3` | Evidence-grounded answers with citations (descriptive) | **Withheld** | TC-11-003, TC-11-004, TC-11-008 |
| C4 | `page.tsx:187-189` (`@c20f949` :189-191) | "Compliance questionnaires take weeks. Generic AI makes things up... invents plausible-sounding nonsense... every answer is grounded" | **Removed.** Reworded without absolutes or competitor disparagement. | TC-11-008 |
| C5 | `page.tsx:197,202,215,270` (`@c20f949` :199,204,217,273) | "answers in minutes", "ready to send back in minutes, not weeks", "Stop spending weeks" | **Removed.** No measured cycle-time evidence. | TC-25-004, TC-11-008 |
| C6 | `page.tsx:215` (`@c20f949` :217) | "Supports common compliance frameworks" | **Removed.** Framework content rights are not yet resolved. | TC-01-007 (new), TC-21-014 |
| C7 | `page.tsx:244` (`@c20f949` :246) | "Full review workflow with export to Word, PDF, Excel" | **Removed.** PDF export is not qualified, and the export fallback silently swaps formats. Reworded to "Review and approval workflow with questionnaire export". | TC-13-005, TC-13-006 |
| C8 | `page.tsx:117`; `pricing/page.tsx:93`; `checkout/page.tsx:262` | "Review, approval, and export workflow" | **Withheld** | TC-12-003, TC-13-004 |
| C9 | `README.md:40` (`@c20f949` :40) | Export places "answers in the original layout" | **Removed.** Known global column-offset defect. Reworded to "written back into the uploaded workbook (exact placement not yet verified)". | TC-13-001, TC-13-002 |
| C10 | `README.md:3,38`; `page.tsx:201`; `pricing/page.tsx:115` (`@c20f949` pricing:116) | Questionnaire parsing; "Excel, CSV, and common security questionnaire formats automatically" | **Removed** (the CSV and "common formats" part). Now reads "Excel (XLSX)". XLSX parsing is **Withheld**. | TC-09-001..006, TC-09-007, TC-09-008 |
| C11 | `README.md:37`; `page.tsx:200` | Evidence upload (PDF, DOCX, XLSX): "indexes and understands them" | **Withheld** | TC-08-001, TC-07-007 |
| C12 | `page.tsx:116,214,234,243`; `pricing/page.tsx:92`; `checkout/page.tsx:261` | Compliance gap detection, blind spots, weak-evidence analytics | **Withheld** | TC-21-006, TC-21-013 |
| C13 | `page.tsx:118,216,245`; `pricing/page.tsx:94`; `checkout/page.tsx:263`; `README.md:93-96` | Public Trust Center portal | **Withheld** | TC-17-001, TC-17-002 |
| C14 | `page.tsx:119,217,245`; `pricing/page.tsx:95`; `checkout/page.tsx:264` | Vendor requests with secure links | **Withheld** | TC-18-002, TC-18-003 |
| C15 | `page.tsx:120,218`; `pricing/page.tsx:96`; `checkout/page.tsx:265` | Gmail and Slack evidence ingestion | **Withheld.** Real provider wiring is not yet qualified. | TC-19-001, TC-19-003, TC-19-006 |
| C16 | `page.tsx:121`; `pricing/page.tsx:97,117`; `checkout/page.tsx:266` | Team collaboration, multiple members with roles | **Withheld** | TC-16-001, TC-05-003 |
| C17 | `pricing/page.tsx:99` | "AI model and response style controls" | **Withheld** | TC-21-012 |
| C18 | `README.md:29-31` | Registration, verification, password reset, workspace switching | **Withheld** | TC-04-001, TC-16-002 |
| C19 | `README.md:7-24,86-91` | Quick start and commands | **Withheld.** Clean-install instructions are not yet independently verified. | TC-29-001 |
| C20 | `README.md:90` (`@c20f949` :90) | Tests "(no failures; ...)" | **Removed.** Unqualified suite-status claim. | TC-02-001 |
| C21 | `README.md` @c20f949:16,28,32,90,100-106 | Links to 36 docs (Deploy, Observability, Backup/restore, Incident response, Status page, SSO setup, Security overview, Tenancy, Audit, Enterprise readiness, Marketing, ...) | **Removed.** None of these files exist in the repo, so the links implied documentation that is absent. Replaced with a pointer to `docs/acceptance/`. | TC-29-001..004 |

## D. Security, privacy, compliance

| # | Location | Claim | Status | Ticket |
|---|---|---|---|---|
| D1 | `page.tsx:259` (`@c20f949` :261,265); `pricing/page.tsx:118` (`@c20f949` :119) | "Evidence is never used to train models", "Evidence never used for training", "never used to train AI models" | **Removed.** This depends on third-party provider terms and the account configuration, which are not documented. | TC-08-009, TC-11-008 |
| D2 | `page.tsx:259` (`@c20f949` :261) | "designed to meet the security expectations of the teams that use it" | **Removed** | TC-17-003 |
| D3 | `pricing/page.tsx:118` (`@c20f949` :119) | "strict access controls" | **Removed.** Reworded to "access is controlled by workspace roles". | TC-06-002, TC-06-005 |
| D4 | `page.tsx:259,262`; `pricing/page.tsx:118` | Data scoped or isolated per workspace | **Withheld** | TC-06-001, TC-06-002, TC-06-005, TC-06-006 |
| D5 | `page.tsx:263`; `pricing/page.tsx:98`; `README.md:32` | Role-based access control (admin, editor, reviewer) | **Withheld** | TC-05-003, TC-06-002 |
| D6 | `page.tsx:264`; `pricing/page.tsx:98` | Audit logging | **Withheld** | TC-16-003 |
| D7 | `README.md:33` | CSRF via Origin/Referer; login rate limiting | **Withheld** | TC-07-005, TC-04-001 |
| D8 | `apps/api/app/services/security_page_service.py:32-38` (`@c20f949` :29-31) | Certifications: "SOC 2 Type II, in_progress, audit underway"; "GDPR, compliant"; "ISO 27001, planned" | **Removed.** All three are now `status: "not_attested"` with a plain statement that no audit, assessment, or certification has been completed. Names are kept so the response shape stays stable. | TC-17-003, TC-21-014 |
| D9 | `security_page_service.py:39-49` (`@c20f949` :34-41) | Highlights: "AES-256 encryption at rest", "TLS 1.2+", "Automated daily backups with 7-day recovery", "Comprehensive audit logging", "Containerized deployment on managed infrastructure" | **Removed** (the absolute versions). Hosting controls are now prefixed "Deployment-dependent, not yet verified:". "Comprehensive" was dropped. App-level features are **Withheld**. | TC-20-010, TC-27-002, TC-27-008, TC-16-003 |
| D10 | `security_page_service.py:52-53` (`@c20f949` :45-46) | `dpa_available: true`, `subprocessor_list_available: true` | **Removed.** Set to `false` because no DPA or subprocessor list exists in the repo. | TC-08-009, TC-15-060 |
| D13 | `security_page_service.py:26` (`@c20f949` :26) | Subtitle "How we protect your data and maintain compliance" | **Removed.** "and maintain compliance" was dropped. | TC-17-003 |
| D14 | `security_page_service.py:51` | `security@trustcopilot.io` contact address (implies the domain and mailbox are owned and monitored) | **Withheld pending owner domain decision** | TC-27-008; owner decision (release-decisions.md) |
| D11 | `security_page_service.py:28-31` | (new) `notice` saying default FAQ answers are templates and no certifications are claimed | n/a (added) | TC-17-003 |
| D12 | `apps/api/app/services/security_faq_service.py:14-129` (DEFAULT_FAQ) seeded at `:137,155` | 20 default answers asserting DigitalOcean US hosting, AES-256, TLS/Caddy, MFA, OIDC SSO with Okta/Azure AD/JIT, 30-day deletion, 5-day deletion SLA, audit log coverage, daily geo-separated backups, PITR, incident response with Sentry, vulnerability scanning, GDPR processor role and DPA template, no training use, 99.9% uptime target, subprocessor list and change notice, code review and CI process | **Labeled example.** New seeds are prefixed "[Template: verify against your deployment before publishing]". Each fact is withheld until verified. Entries already seeded in existing workspaces are not rewritten (no data migration). | TC-17-004, TC-08-008, TC-08-009, TC-05-001, TC-05-009, TC-27-002, TC-29-004 |

## Counts

| Status | Rows |
|---|---|
| Supported | 1 (A4-part: blank template and consent gate) |
| Removed (deleted or honestly reworded) | 20 (A9, B1, B6-part, C1, C2, C4, C5, C6, C7, C9, C10-part, C20, C21, D1, D2, D3, D8, D9-part, D10, D13) |
| Labeled example (synthetic or heuristic) | 6 (A2, A5, A7, A8, A10, D12) |
| Withheld pending ticket or owner decision | 27 (A3, A4-part, A6, A11, B2-B6, C3, C8, C10-part, C11-C19, D4-D7, D9-part, D14) |
| No claim present | 1 (A1: no testimonials, customer logos, or traction figures exist) |

Total: 52 rows (A1–A11, B1–B6, C1–C21, D1–D14). D11 is a notice added by TC-01-005, not a claim. A4, B6, C10, and D9 are split between two statuses, so the counts add up to 55. A4-part is Supported only for the blank template and the consent gate in `artifacts/acceptance/TC-25-005/`. Signed consent evidence (TC-26-015) and reviewer signoff stay withheld.

## Rules going forward

1. A row moves to **Supported** only when it links a passing acceptance result (`artifacts/acceptance/<ticket>/`).
2. New public copy that makes a claim needs a row here in the same PR.
3. Synthetic, demo, or heuristic outputs must carry `data_basis` or an equivalent visible label.
4. Testimonials, case studies, logos, and traction numbers need recorded consent (TC-25-005) and evidence (TC-26-015).
