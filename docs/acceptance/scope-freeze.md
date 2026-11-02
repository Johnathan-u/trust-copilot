# Scope freeze: full-suite release (TC-01-001)

Status: **FROZEN** at baseline `c20f949161ac12a619b396d30904448ffd74d532`. Frozen by the Trust Copilot Coordinator (scope authority, per `release-decisions.md`) on 2026-10-27. **Amended 2026-11-02** (change control, owner-approved OD-11): the inventory is reconciled to master `574f2e2` and the post-freeze epics E31–E37 are added in §11. The original 384-ticket, 1,864-point denominator is unchanged.

Sources: `Traceability.json` (127 surfaces), `TrustCopilot_Feature_Scope.md`, `PRODUCT_SPEC.md` §Scope, and `TrustCopilot_Execution_Backlog.json` (384 tickets, 30 epics), from the delivery package. The ticket file names this document `docs/acceptance/scope-contract.md`. This repo uses the coordinator brief's name, `scope-freeze.md`, which serves the same purpose. `scope-contract.md` should be read as an alias for this file.

## 1. Objective

Deliver the **complete** existing Trust Copilot product, meaning every inventoried surface below, to the full-release contract in `PRODUCT_SPEC.md`. Completion is shown only by acceptance evidence at one release SHA (independent security review, real provider sandbox trials, real-model holdouts, original-cell export checks, buyer clean-room install and restore). Seeded demos, endpoint names, compile success, or a signed sale agreement do not count.

## 2. Freeze rules

1. **Everything inventoried here is REQUIRED FOR FULL RELEASE.** All 127 Traceability rows carry `scope: REQUIRED FOR FULL RELEASE`, and there are no focused-release exclusions.
2. **No silent disabling.** Hiding, feature-flagging off, returning 404/501, or deleting an unfinished surface does **not** count as completion. Reducing scope needs an explicit owner decision recorded in `release-decisions.md`, plus matching changes to this file, the UI, APIs, docs, listing, and `claims-register.md`.
3. **Owner epic** means the epic accountable for the surface's acceptance. Mapping rule: the epic of the surface's first delivery ticket in `Traceability.json`. All delivery tickets are listed. Every surface is also covered by security ticket **TC-06-005** (all-surface tenant and role matrix, E06).
4. **New findings.** Runtime route enumeration, provider discovery, or security qualification may turn up surfaces not listed here. Each one gets a linked ticket with an estimate and dependency under the change-control rule (`release-decisions.md`). A finding is never ignored because of backlog size.
5. **Out of scope** (§7) means not part of this release contract. Building any of it requires change control first.

## 3. API route modules (94 modules, 531 static operations on master `574f2e2`)

| # | Module | Path | Ops | Owner epic | Delivery tickets | Security |
|---|---|---|---|---|---|---|
| 1 | `ai_insights` | `apps/api/app/api/routes/ai_insights.py` | 1 | E21 Compliance controls mappings and gaps | TC-21-012 | TC-06-005 |
| 2 | `ai_mappings` | `apps/api/app/api/routes/ai_mappings.py` | 25 | E21 Compliance controls mappings and gaps | TC-21-011 | TC-06-005 |
| 3 | `alert_management` | `apps/api/app/api/routes/alert_management.py` | 2 | E22 Monitoring alerts and remediation | TC-22-005 | TC-06-005 |
| 4 | `alerting_engine` | `apps/api/app/api/routes/alerting_engine.py` | 5 | E22 Monitoring alerts and remediation | TC-22-006 | TC-06-005 |
| 5 | `answer_approval` | `apps/api/app/api/routes/answer_approval.py` | 10 | E12 Review approval and reusable knowledge | TC-12-006 | TC-06-005 |
| 6 | `answer_outcomes` | `apps/api/app/api/routes/answer_outcomes.py` | 3 | E23 Deals contracts promises and proof | TC-23-006 | TC-06-005 |
| 7 | `answer_tiers` | `apps/api/app/api/routes/answer_tiers.py` | 2 | E12 Review approval and reusable knowledge | TC-12-008 | TC-06-005 |
| 8 | `answers` | `apps/api/app/api/routes/answers.py` | 4 | E12 Review approval and reusable knowledge | TC-12-001, TC-12-002, TC-12-003, TC-12-004 | TC-06-005 |
| 9 | `audit` | `apps/api/app/api/routes/audit.py` | 2 | E16 Workspace administration audit and API usability | TC-16-003 | TC-06-005 |
| 10 | `auth` | `apps/api/app/api/routes/auth.py` | 33 | E04 Accounts and sessions | TC-04-001, TC-04-002, TC-04-003, TC-04-004, TC-05-004, TC-05-005, TC-05-006, TC-05-007, TC-05-008, TC-05-001 | TC-06-005 |
| 11 | `aws_connector` | `apps/api/app/api/routes/aws_connector.py` | 5 | E20 Cloud directory code and CRM integrations | TC-20-008, TC-20-009, TC-20-010, TC-20-011, TC-20-012, TC-20-013 | TC-06-005 |
| 12 | `benchmarks` | `apps/api/app/api/routes/benchmarks.py` | 1 | E25 Product reporting and analytics | TC-25-003 | TC-06-005 |
| 13 | `billing` | `apps/api/app/api/routes/billing.py` | 4 | E24 Billing entitlements and credit ledger | TC-24-001, TC-24-002, TC-24-005 | TC-06-005 |
| 14 | `buyer_portal` | `apps/api/app/api/routes/buyer_portal.py` | 13 | E17 Trust center public sharing and NDA | TC-17-007 | TC-06-005 |
| 15 | `case_studies` | `apps/api/app/api/routes/case_studies.py` | 14 | E25 Product reporting and analytics | TC-25-005 | TC-06-005 |
| 16 | `citation_composer` | `apps/api/app/api/routes/citation_composer.py` | 2 | E12 Review approval and reusable knowledge | TC-12-010 | TC-06-005 |
| 17 | `cloud_connectors` | `apps/api/app/api/routes/cloud_connectors.py` | 6 | E20 Cloud directory code and CRM integrations | TC-20-005, TC-20-006, TC-20-007, TC-20-025, TC-20-026, TC-20-027, TC-20-028, TC-20-029, TC-20-030, TC-20-031, TC-20-032, TC-20-033, TC-20-034, TC-20-035, TC-20-036, TC-20-037, TC-20-038, TC-20-039, TC-20-040, TC-20-041, TC-20-042, TC-20-043, TC-20-044, TC-20-045 | TC-06-005 |
| 18 | `compliance_alerts` | `apps/api/app/api/routes/compliance_alerts.py` | 1 | E21 Compliance controls mappings and gaps | TC-21-008 | TC-06-005 |
| 19 | `compliance_audit` | `apps/api/app/api/routes/compliance_audit.py` | 5 | E21 Compliance controls mappings and gaps | TC-21-010 | TC-06-005 |
| 20 | `compliance_controls` | `apps/api/app/api/routes/compliance_controls.py` | 12 | E21 Compliance controls mappings and gaps | TC-21-003 | TC-06-005 |
| 21 | `compliance_coverage` | `apps/api/app/api/routes/compliance_coverage.py` | 1 | E21 Compliance controls mappings and gaps | TC-21-007 | TC-06-005 |
| 22 | `compliance_evidence` | `apps/api/app/api/routes/compliance_evidence.py` | 4 | E21 Compliance controls mappings and gaps | TC-21-004 | TC-06-005 |
| 23 | `compliance_export` | `apps/api/app/api/routes/compliance_export.py` | 3 | E21 Compliance controls mappings and gaps | TC-21-009 | TC-06-005 |
| 24 | `compliance_frameworks` | `apps/api/app/api/routes/compliance_frameworks.py` | 2 | E21 Compliance controls mappings and gaps | TC-21-001 | TC-06-005 |
| 25 | `compliance_gaps` | `apps/api/app/api/routes/compliance_gaps.py` | 2 | E21 Compliance controls mappings and gaps | TC-21-006 | TC-06-005 |
| 26 | `compliance_mappings` | `apps/api/app/api/routes/compliance_mappings.py` | 5 | E21 Compliance controls mappings and gaps | TC-21-005 | TC-06-005 |
| 27 | `confidence_routing` | `apps/api/app/api/routes/confidence_routing.py` | 5 | E12 Review approval and reusable knowledge | TC-12-012 | TC-06-005 |
| 28 | `confidence_scoring` | `apps/api/app/api/routes/confidence_scoring.py` | 2 | E12 Review approval and reusable knowledge | TC-12-011 | TC-06-005 |
| 29 | `connector_health` | `apps/api/app/api/routes/connector_health.py` | 1 | E20 Cloud directory code and CRM integrations | TC-20-003 | TC-06-005 |
| 30 | `connector_wizard` | `apps/api/app/api/routes/connector_wizard.py` | 5 | E20 Cloud directory code and CRM integrations | TC-20-001, TC-20-002, TC-15-036 | TC-06-005 |
| 31 | `contracts` | `apps/api/app/api/routes/contracts.py` | 2 | E23 Deals contracts promises and proof | TC-23-002 | TC-06-005 |
| 32 | `control_engine` | `apps/api/app/api/routes/control_engine.py` | 4 | E22 Monitoring alerts and remediation | TC-22-002 | TC-06-005 |
| 33 | `control_timeline` | `apps/api/app/api/routes/control_timeline.py` | 1 | E22 Monitoring alerts and remediation | TC-22-003 | TC-06-005 |
| 34 | `controls` | `apps/api/app/api/routes/controls.py` | 8 | E21 Compliance controls mappings and gaps | TC-21-002 | TC-06-005 |
| 35 | `credentials` | `apps/api/app/api/routes/credentials.py` | 5 | E20 Cloud directory code and CRM integrations | TC-20-002, TC-07-002 | TC-06-005 |
| 36 | `credit_prompts` | `apps/api/app/api/routes/credit_prompts.py` | 1 | E24 Billing entitlements and credit ledger | TC-24-004 | TC-06-005 |
| 37 | `credits` | `apps/api/app/api/routes/credits.py` | 6 | E24 Billing entitlements and credit ledger | TC-24-003 | TC-06-005 |
| 38 | `crm_connectors` | `apps/api/app/api/routes/crm_connectors.py` | 3 | E20 Cloud directory code and CRM integrations | TC-20-049, TC-20-050, TC-20-051, TC-20-052, TC-20-053, TC-20-054 | TC-06-005 |
| 39 | `dashboard_cards` | `apps/api/app/api/routes/dashboard_cards.py` | 8 | E25 Product reporting and analytics | TC-25-001 | TC-06-005 |
| 40 | `deals` | `apps/api/app/api/routes/deals.py` | 15 | E23 Deals contracts promises and proof | TC-23-001 | TC-06-005 |
| 41 | `demo_proof` | `apps/api/app/api/routes/demo_proof.py` | 7 | E25 Product reporting and analytics | TC-25-011 | TC-06-005 |
| 42 | `documents` | `apps/api/app/api/routes/documents.py` | 8 | E08 Evidence lifecycle and privacy | TC-08-001, TC-07-006, TC-08-007, TC-08-002 | TC-06-005 |
| 43 | `evidence_approval` | `apps/api/app/api/routes/evidence_approval.py` | 6 | E12 Review approval and reusable knowledge | TC-12-007 | TC-06-005 |
| 44 | `evidence_cards` | `apps/api/app/api/routes/evidence_cards.py` | 2 | E12 Review approval and reusable knowledge | TC-12-013 | TC-06-005 |
| 45 | `evidence_diff` | `apps/api/app/api/routes/evidence_diff.py` | 2 | E22 Monitoring alerts and remediation | TC-22-012 | TC-06-005 |
| 46 | `evidence_gaps` | `apps/api/app/api/routes/evidence_gaps.py` | 5 | E21 Compliance controls mappings and gaps | TC-21-013 | TC-06-005 |
| 47 | `evidence_search` | `apps/api/app/api/routes/evidence_search.py` | 3 | E08 Evidence lifecycle and privacy | TC-08-010 | TC-06-005 |
| 48 | `executive_dashboard` | `apps/api/app/api/routes/executive_dashboard.py` | 1 | E25 Product reporting and analytics | TC-25-002 | TC-06-005 |
| 49 | `export_pack` | `apps/api/app/api/routes/export_pack.py` | 4 | E13 Workbook and evidence exports | TC-13-007 | TC-06-005 |
| 50 | `exports` | `apps/api/app/api/routes/exports.py` | 4 | E13 Workbook and evidence exports | TC-13-001, TC-13-002, TC-13-004, TC-13-005 | TC-06-005 |
| 51 | `feature_flags` | `apps/api/app/api/routes/feature_flags.py` | 4 | E16 Workspace administration audit and API usability | TC-16-006 | TC-06-005 |
| 52 | `feedback_capture` | `apps/api/app/api/routes/feedback_capture.py` | 2 | E12 Review approval and reusable knowledge | TC-12-014 | TC-06-005 |
| 53 | `freshness_policies` | `apps/api/app/api/routes/freshness_policies.py` | 5 | E22 Monitoring alerts and remediation | TC-22-008 | TC-06-005 |
| 54 | `github_connector` | `apps/api/app/api/routes/github_connector.py` | 4 | E20 Cloud directory code and CRM integrations | TC-20-014, TC-20-015, TC-20-016, TC-20-017, TC-20-018, TC-20-019 | TC-06-005 |
| 55 | `gmail` | `apps/api/app/api/routes/gmail.py` | 12 | E19 Slack Gmail and notification delivery | TC-19-001, TC-19-005, TC-19-006, TC-19-007 | TC-06-005 |
| 56 | `golden_answers` | `apps/api/app/api/routes/golden_answers.py` | 9 | E12 Review approval and reusable knowledge | TC-12-005 | TC-06-005 |
| 57 | `google_connector` | `apps/api/app/api/routes/google_connector.py` | 4 | E20 Cloud directory code and CRM integrations | TC-20-020, TC-20-021, TC-20-022, TC-20-023, TC-20-024 | TC-06-005 |
| 58 | `in_app_notifications` | `apps/api/app/api/routes/in_app_notifications.py` | 4 | E19 Slack Gmail and notification delivery | TC-19-010 | TC-06-005 |
| 59 | `incident_pages` | `apps/api/app/api/routes/incident_pages.py` | 3 | E25 Product reporting and analytics | TC-25-010 | TC-06-005 |
| 60 | `ingestion` | `apps/api/app/api/routes/ingestion.py` | 3 | E22 Monitoring alerts and remediation | TC-22-001 | TC-06-005 |
| 61 | `jobs` | `apps/api/app/api/routes/jobs.py` | 4 | E10 Jobs storage and consistency | TC-10-001, TC-10-002, TC-10-003, TC-10-004 | TC-06-005 |
| 62 | `knowledge_packs` | `apps/api/app/api/routes/knowledge_packs.py` | 1 | E12 Review approval and reusable knowledge | TC-12-009 | TC-06-005 |
| 63 | `members` | `apps/api/app/api/routes/members.py` | 17 | E16 Workspace administration audit and API usability | TC-16-001, TC-05-003, TC-04-005 | TC-06-005 |
| 64 | `monitoring` | `apps/api/app/api/routes/monitoring.py` | 1 | E22 Monitoring alerts and remediation | TC-22-004 | TC-06-005 |
| 65 | `nda_access` | `apps/api/app/api/routes/nda_access.py` | 6 | E17 Trust center public sharing and NDA | TC-17-006 | TC-06-005 |
| 66 | `notifications` | `apps/api/app/api/routes/notifications.py` | 12 | E19 Slack Gmail and notification delivery | TC-19-009 | TC-06-005 |
| 67 | `operator_queue` | `apps/api/app/api/routes/operator_queue.py` | 6 | E22 Monitoring alerts and remediation | TC-22-011 | TC-06-005 |
| 68 | `product_events` | `apps/api/app/api/routes/product_events.py` | 5 | E25 Product reporting and analytics | TC-25-006 | TC-06-005 |
| 69 | `promises` | `apps/api/app/api/routes/promises.py` | 8 | E23 Deals contracts promises and proof | TC-23-003 | TC-06-005 |
| 70 | `proof_graph` | `apps/api/app/api/routes/proof_graph.py` | 10 | E23 Deals contracts promises and proof | TC-23-004 | TC-06-005 |
| 71 | `proof_widgets` | `apps/api/app/api/routes/proof_widgets.py` | 1 | E23 Deals contracts promises and proof | TC-23-005 | TC-06-005 |
| 72 | `questionnaires` | `apps/api/app/api/routes/questionnaires.py` | 16 | E09 Questionnaire intake and mapping | TC-09-001, TC-09-002, TC-09-003, TC-09-005, TC-09-007, TC-09-008 | TC-06-005 |
| 73 | `remediation` | `apps/api/app/api/routes/remediation.py` | 15 | E22 Monitoring alerts and remediation | TC-22-007 | TC-06-005 |
| 74 | `retention` | `apps/api/app/api/routes/retention.py` | 5 | E08 Evidence lifecycle and privacy | TC-08-008, TC-08-007 | TC-06-005 |
| 75 | `reuse_analytics` | `apps/api/app/api/routes/reuse_analytics.py` | 1 | E25 Product reporting and analytics | TC-25-007 | TC-06-005 |
| 76 | `roi_calculator` | `apps/api/app/api/routes/roi_calculator.py` | 1 | E25 Product reporting and analytics | TC-25-004 | TC-06-005 |
| 77 | `search` | `apps/api/app/api/routes/search.py` | 2 | E08 Evidence lifecycle and privacy | TC-08-010 | TC-06-005 |
| 78 | `security_faq` | `apps/api/app/api/routes/security_faq.py` | 12 | E17 Trust center public sharing and NDA | TC-17-004 | TC-06-005 |
| 79 | `security_page` | `apps/api/app/api/routes/security_page.py` | 3 | E17 Trust center public sharing and NDA | TC-17-003 | TC-06-005 |
| 80 | `shareable_spaces` | `apps/api/app/api/routes/shareable_spaces.py` | 4 | E17 Trust center public sharing and NDA | TC-17-005 | TC-06-005 |
| 81 | `signal_mapping` | `apps/api/app/api/routes/signal_mapping.py` | 3 | E22 Monitoring alerts and remediation | TC-22-009 | TC-06-005 |
| 82 | `sla_tracking` | `apps/api/app/api/routes/sla_tracking.py` | 1 | E22 Monitoring alerts and remediation | TC-22-010 | TC-06-005 |
| 83 | `slack` | `apps/api/app/api/routes/slack.py` | 6 | E19 Slack Gmail and notification delivery | TC-19-001, TC-19-002, TC-19-004 | TC-06-005 |
| 84 | `slack_ingest` | `apps/api/app/api/routes/slack_ingest.py` | 8 | E19 Slack Gmail and notification delivery | TC-19-003 | TC-06-005 |
| 85 | `sli` | `apps/api/app/api/routes/sli.py` | 1 | E25 Product reporting and analytics | TC-25-009 | TC-06-005 |
| 86 | `source_registry` | `apps/api/app/api/routes/source_registry.py` | 5 | E20 Cloud directory code and CRM integrations | TC-20-001, TC-20-003, TC-20-004 | TC-06-005 |
| 87 | `tags` | `apps/api/app/api/routes/tags.py` | 6 | E08 Evidence lifecycle and privacy | TC-08-011 | TC-06-005 |
| 88 | `trust_articles` | `apps/api/app/api/routes/trust_articles.py` | 8 | E17 Trust center public sharing and NDA | TC-17-001 | TC-06-005 |
| 89 | `trust_center_analytics` | `apps/api/app/api/routes/trust_center_analytics.py` | 1 | E25 Product reporting and analytics | TC-25-008 | TC-06-005 |
| 90 | `trust_center_publish` | `apps/api/app/api/routes/trust_center_publish.py` | 2 | E17 Trust center public sharing and NDA | TC-17-002 | TC-06-005 |
| 91 | `trust_requests` | `apps/api/app/api/routes/trust_requests.py` | 20 | E18 Trust requests and vendor responses | TC-18-001 | TC-06-005 |
| 92 | `vendor_requests` | `apps/api/app/api/routes/vendor_requests.py` | 8 | E18 Trust requests and vendor responses | TC-18-002 | TC-06-005 |
| 93 | `vendor_response` | `apps/api/app/api/routes/vendor_response.py` | 2 | E18 Trust requests and vendor responses | TC-18-003 | TC-06-005 |
| 94 | `workspaces` | `apps/api/app/api/routes/workspaces.py` | 5 | E16 Workspace administration audit and API usability | TC-16-002, TC-08-008, TC-16-001 | TC-06-005 |

Note: `evidence_gaps` declares 0 static operations at baseline but stays in scope (TC-21-013). Static counts are a baseline only. Runtime enumeration (TC-02 CI and TC-28-001) is mandatory.

scope-freeze amendment approved by coordinator 2026-10-27: `case_studies` is 14 static operations (baseline was 6). The eight added routes are `POST /api/case-studies/{id}/consents`, `POST /api/case-studies/{id}/consents/{consent_id}/revoke`, `POST /api/case-studies/{id}/result-permissions`, `POST /api/case-studies/{id}/result-permissions/{permission_id}/revoke`, `POST /api/case-studies/{id}/submit-review`, `POST /api/case-studies/{id}/review`, `POST /api/case-studies/{id}/publish`, and `POST /api/case-studies/{id}/withdraw`. The section total is 497 (baseline was 489).

scope-freeze amendment 2026-11-02 (inventory reconciliation, no new modules): 34 static operations were added inside 15 existing modules by in-scope tickets. Each one is covered by the module's owner epic and the tickets below, plus TC-06-005.

| Module | Operations added | Added by |
|---|---|---|
| `answers` | `POST /api/answers` | TC-11-001 |
| `auth` | `POST /api/auth/sessions/revoke-all` | TC-04-004b, TC-04-006a |
| `compliance_mappings` | `POST /api/compliance/control-mappings/rollback` | TC-21-005 |
| `deals` | `POST /api/deals/{deal_id}/links` | TC-23-001 |
| `demo_proof` | `POST /api/demo-proof`, `GET /api/demo-proof/summaries/{summary_id}` | TC-25-011 |
| `evidence_gaps` | `GET`/`POST /api/evidence-gaps`, `GET /{gap_id}`, `POST /{gap_id}/decision`, `POST /{gap_id}/resolve` | TC-21-013, TC-21-013a |
| `jobs` | `GET /api/jobs`, `POST /{job_id}/cancel`, `POST /{job_id}/retry` | TC-10-002, TC-10-003, TC-10-004, TC-15-038a |
| `members` | `POST /api/members/clear-mfa-reenrol/{user_id}` | TC-07-002 |
| `notifications` | `GET`/`PUT /api/notifications/channel-preferences`, `GET /delivery-attempts` | TC-19-008 |
| `security_faq` | `GET /published`, `GET /{faq_id}/revisions`, `POST /{faq_id}/approve`, `/publish`, `/withdraw` | TC-17-004 |
| `security_page` | `GET /api/security-page/claims`, `PUT /claims/{claim_key}` | TC-17-003 |
| `trust_requests` | `PATCH /{request_id}/replies/{note_id}`, `POST .../approve`, `POST .../send` | TC-18-001 |
| `vendor_requests` | `POST /api/vendor-requests`, `POST /{request_id}/send`, `/resend`, `/revoke` | TC-18-002 |
| `vendor_response` | `POST /api/vendor-response/submit` | TC-18-002 |
| `workspaces` | `GET /api/workspaces/creation-policy` | TC-04-001a, TC-04-006a |

## 4. Pages (44 inventoried routes: 43 page files plus 1 redirect)

| # | Route | Path | Owner epic | Delivery tickets | Security |
|---|---|---|---|---|---|
| 1 | `/accept-invite` | `apps/web/app/accept-invite/page.tsx` | E15 Every screen and missing workflow UI | TC-15-009 | TC-06-005 |
| 2 | `/checkout` | `apps/web/app/checkout/page.tsx` | E15 Every screen and missing workflow UI | TC-15-003 | TC-06-005 |
| 3 | `/dashboard/ai-governance` | `apps/web/app/dashboard/ai-governance/page.tsx` | E15 Every screen and missing workflow UI | TC-15-035 | TC-06-005 |
| 4 | `/dashboard/audit` | `apps/web/app/dashboard/audit/page.tsx` | E15 Every screen and missing workflow UI | TC-15-032 | TC-06-005 |
| 5 | `/dashboard/compliance-gaps` | `apps/web/app/dashboard/compliance-gaps/page.tsx` | E15 Every screen and missing workflow UI | TC-15-025 | TC-06-005 |
| 6 | `/dashboard/documents` | `apps/web/app/dashboard/documents/page.tsx` | E15 Every screen and missing workflow UI | TC-15-016 | TC-06-005 |
| 7 | `/dashboard/exports` | `apps/web/app/dashboard/exports/page.tsx` | E15 Every screen and missing workflow UI | TC-15-022 | TC-06-005 |
| 8 | `/dashboard/gmail` | `apps/web/app/dashboard/gmail/page.tsx` | E15 Every screen and missing workflow UI | TC-15-031 | TC-06-005 |
| 9 | `/dashboard/members` | `apps/web/app/dashboard/members/page.tsx` | E15 Every screen and missing workflow UI | TC-15-028 | TC-06-005 |
| 10 | `/dashboard/notifications` | `apps/web/app/dashboard/notifications/page.tsx` | E15 Every screen and missing workflow UI | TC-15-029 | TC-06-005 |
| 11 | `/dashboard` | `apps/web/app/dashboard/page.tsx` | E15 Every screen and missing workflow UI | TC-15-015 | TC-06-005 |
| 12 | `/dashboard/proof-chain` | `apps/web/app/dashboard/proof-chain/page.tsx` | E15 Every screen and missing workflow UI | TC-15-026 | TC-06-005 |
| 13 | `/dashboard/questionnaires/[id]` | `apps/web/app/dashboard/questionnaires/[id]/page.tsx` | E15 Every screen and missing workflow UI | TC-15-018 | TC-06-005 |
| 14 | `/dashboard/questionnaires` | `apps/web/app/dashboard/questionnaires/page.tsx` | E15 Every screen and missing workflow UI | TC-15-017 | TC-06-005 |
| 15 | `/dashboard/requests` | `apps/web/app/dashboard/requests/page.tsx` | E15 Every screen and missing workflow UI | TC-15-023 | TC-06-005 |
| 16 | `/dashboard/review/[id]` | `apps/web/app/dashboard/review/[id]/page.tsx` | E15 Every screen and missing workflow UI | TC-15-020, TC-15-021 | TC-06-005 |
| 17 | `/dashboard/review` | `apps/web/app/dashboard/review/page.tsx` | E15 Every screen and missing workflow UI | TC-15-019 | TC-06-005 |
| 18 | `/dashboard/security` | `apps/web/app/dashboard/security/page.tsx` | E15 Every screen and missing workflow UI | TC-15-033 | TC-06-005 |
| 19 | `/dashboard/settings` | `apps/web/app/dashboard/settings/page.tsx` | E15 Every screen and missing workflow UI | TC-15-034 | TC-06-005 |
| 20 | `/dashboard/slack` | `apps/web/app/dashboard/slack/page.tsx` | E15 Every screen and missing workflow UI | TC-15-030 | TC-06-005 |
| 21 | `/dashboard/trust-center` | `apps/web/app/dashboard/trust-center/page.tsx` | E15 Every screen and missing workflow UI | TC-15-027 | TC-06-005 |
| 22 | `/dashboard/vendor-requests` | `apps/web/app/dashboard/vendor-requests/route.ts` (redirect to `/dashboard/requests` since TC-15-024; the page itself was merged into `/dashboard/requests`) | E15 Every screen and missing workflow UI | TC-15-024 | TC-06-005 |
| 23 | `/forgot-password` | `apps/web/app/forgot-password/page.tsx` | E15 Every screen and missing workflow UI | TC-15-006 | TC-06-005 |
| 24 | `/login` | `apps/web/app/login/page.tsx` | E15 Every screen and missing workflow UI | TC-15-004 | TC-06-005 |
| 25 | `/onboarding` | `apps/web/app/onboarding/page.tsx` | E15 Every screen and missing workflow UI | TC-15-010 | TC-06-005 |
| 26 | `/` | `apps/web/app/page.tsx` | E15 Every screen and missing workflow UI | TC-15-001 | TC-06-005 |
| 27 | `/pricing` | `apps/web/app/pricing/page.tsx` | E15 Every screen and missing workflow UI | TC-15-002 | TC-06-005 |
| 28 | `/register` | `apps/web/app/register/page.tsx` | E15 Every screen and missing workflow UI | TC-15-005 | TC-06-005 |
| 29 | `/reset-password` | `apps/web/app/reset-password/page.tsx` | E15 Every screen and missing workflow UI | TC-15-007 | TC-06-005 |
| 30 | `/trust/[slug]` | `apps/web/app/trust/[slug]/page.tsx` | E15 Every screen and missing workflow UI | TC-15-012 | TC-06-005 |
| 31 | `/trust` | `apps/web/app/trust/page.tsx` | E15 Every screen and missing workflow UI | TC-15-011 | TC-06-005 |
| 32 | `/vendor-response` | `apps/web/app/vendor-response/page.tsx` | E15 Every screen and missing workflow UI | TC-15-013, TC-15-014 | TC-06-005 |
| 33 | `/verify-email` | `apps/web/app/verify-email/page.tsx` | E15 Every screen and missing workflow UI | TC-15-008 | TC-06-005 |
| 34 | `/dashboard/case-studies` | `apps/web/app/dashboard/case-studies/page.tsx` | E15 Every screen and missing workflow UI | TC-25-005 | TC-06-005 |
| 35 | `/dashboard/compliance-frameworks` | `apps/web/app/dashboard/compliance-frameworks/page.tsx` | E21 Compliance controls mappings and gaps | TC-21-001 | TC-06-005 |
| 36 | `/dashboard/controls` | `apps/web/app/dashboard/controls/page.tsx` | E15 Every screen and missing workflow UI | TC-15-042 | TC-06-005 |
| 37 | `/dashboard/controls/[id]` | `apps/web/app/dashboard/controls/[id]/page.tsx` | E15 Every screen and missing workflow UI | TC-15-042 | TC-06-005 |
| 38 | `/dashboard/deals` | `apps/web/app/dashboard/deals/page.tsx` | E15 Every screen and missing workflow UI | TC-15-049a, TC-23-001 | TC-06-005 |
| 39 | `/dashboard/demo-proof` | `apps/web/app/dashboard/demo-proof/page.tsx` | E25 Product reporting and analytics | TC-25-011 | TC-06-005 |
| 40 | `/dashboard/jobs` | `apps/web/app/dashboard/jobs/page.tsx` | E15 Every screen and missing workflow UI | TC-15-038a, TC-10-004 | TC-06-005 |
| 41 | `/dashboard/security-page` | `apps/web/app/dashboard/security-page/page.tsx` | E17 Trust center public sharing and NDA | TC-17-003 | TC-06-005 |
| 42 | `/dashboard/trust-requests` | `apps/web/app/dashboard/trust-requests/page.tsx` | E15 Every screen and missing workflow UI | TC-15-039a, TC-18-001 | TC-06-005 |
| 43 | `/design-tokens` | `apps/web/app/design-tokens/page.tsx` | E14 Design system and accessibility | TC-14-001 | TC-06-005 |
| 44 | `/design-dialogs` | `apps/web/app/design-dialogs/page.tsx` | E14 Design system and accessibility | TC-14-003 | TC-06-005 |

scope-freeze amendment approved by coordinator 2026-10-27: `/dashboard/case-studies` is in this inventory. Baseline was 33 existing page files.

scope-freeze amendment 2026-11-02: rows 35–44 are page files added by in-scope tickets after the freeze. Row 22 is not a reduction: TC-15-024 merged the outbound vendor-request screen into `/dashboard/requests` and kept the old URL as a redirect, so no workflow was removed. `/design-tokens` and `/design-dialogs` are public design-system reference pages (E14); their exposure in production is decided under TC-14-001/TC-14-003.

E15 also creates the *missing* workflow UI surfaces defined in its tickets (for example TC-15-036 connector setup, TC-15-038 job and activity center, TC-15-060 privacy, cookies, terms, subprocessors, and contact pages). Those are in scope through their tickets even though they are not existing page files.

## 5. Background dispatchers and in-process jobs

| # | Dispatcher | Source (baseline) | Owner epic | Acceptance tickets |
|---|---|---|---|---|
| 1 | Worker job-claim loop, thread autoscaling | `apps/api/app/worker.py:84` `claim_job`, `:63` `_adapt_thread_count`, `:568` `main` | E10 Jobs storage and consistency | TC-10-001, TC-10-002, TC-10-004, TC-10-007, TC-08-005, TC-03-003 |
| 2 | Job kind `parse_questionnaire` (+ auto-classify) | `worker.py:121`, `:166`, dispatch `:385` | E09 Questionnaire intake and mapping | TC-09-001..009, TC-10-003 |
| 3 | Job kind `parse_evidence` | `worker.py:387` | E08 Evidence lifecycle and privacy | TC-08-001, TC-08-002, TC-10-003 |
| 4 | Job kind `index_document`; startup `enqueue_missing_index_jobs` | `worker.py:225`, `:389`, `:413` | E08 Evidence lifecycle and privacy | TC-08-001, TC-10-003, TC-10-005 |
| 5 | Job kind `generate_answers` | `worker.py:244`, `:391` | E11 AI grounding and citations | TC-11-001, TC-11-002, TC-11-003, TC-12-004, TC-10-003 |
| 6 | Job kind `export` | `worker.py:290`, `:394` | E13 Workbook and evidence exports | TC-13-001, TC-13-002, TC-13-004, TC-13-005, TC-10-006 |
| 7 | Job completion notifications and job audit | `worker.py:401`, `:540` | E19 Slack Gmail and notification delivery | TC-19-008, TC-19-010, TC-16-003 |
| 8 | In-process gap-generation thread | `apps/api/app/services/answer_generation.py:997` | E21 Compliance controls mappings and gaps | TC-21-006, TC-10-002 (move to durable job or prove bounded) |
| 9 | In-process password-reset email thread | `apps/api/app/api/routes/auth.py:332` | E04 Accounts and sessions | TC-04-002, TC-04-007, TC-19-008 |
| 10 | In-process invite email thread | `apps/api/app/api/routes/members.py:205` | E16 Workspace administration audit and API usability | TC-16-001, TC-19-008 |
| 11 | API startup: bucket init, system-tag seed, prod secret checks | `apps/api/app/main.py:180` `lifespan` | E03 Deployment and migrations | TC-03-001, TC-03-003, TC-10-005 |
| 12 | Scheduled monitoring, connector cadence, digests (**no durable scheduler at baseline**) | none; required by spec | E22 Monitoring alerts and remediation | TC-22-004, TC-20-003, TC-22-006, TC-10-001 |
| 13 | Notification rule delivery | notifications services | E19 Slack Gmail and notification delivery | TC-19-008, TC-19-009 |
| 14 | Provider event / billing webhook processing | billing routes / Stripe webhook | E24 Billing entitlements and credit ledger | TC-24-001, TC-24-003, TC-24-005 |
| 15 | First-party product event capture (outbox) | product_events | E26 Public traffic analytics and acquisition evidence | TC-26-014, TC-26-016, TC-26-017 |
| 16 | Job-lease heartbeat thread (renews the running job's lease) | `apps/api/app/core/job_lease.py` `JobLeaseHeartbeat`, started from `worker.py` `_start_job_lease_heartbeat` | E10 Jobs storage and consistency | TC-10-001, TC-10-001a, TC-10-001b |
| 17 | Abandoned-job recovery and scheduled retries | `worker.py` `recover_abandoned_jobs`, `_try_schedule_retry` | E10 Jobs storage and consistency | TC-10-001, TC-10-003, TC-10-004 |
| 18 | Storage startup reconcile and orphaned-object sweep | `services/storage_reconcile.py` `startup_reconcile`, `sweep_orphans_best_effort` (called from `worker.py`) | E10 Jobs storage and consistency | TC-10-005 |

scope-freeze amendment 2026-11-02: rows 16–18 were added by in-scope E10 tickets after the freeze. The five worker job kinds are unchanged. Baseline line numbers in rows 1–11 refer to `c20f949`.

## 6. Registered or advertised providers

Every provider that is configured, registered (`source_registry_service.py`, `connector_wizard_service.py`, `cloud_connector_service.py`, `crm_connector_service.py`), or advertised in UI or copy is in scope. Under the change-control rule, each provider needs real sandbox evidence. Mock-only evidence never closes a real-provider promise. If sandbox access is unavailable, the ticket is recorded as BLOCKED; that is not a pass.

| # | Provider | Kind | Baseline source | Owner epic | Acceptance tickets | Owner decision needed |
|---|---|---|---|---|---|---|
| 1 | OpenAI (completions + embeddings) | Model | `core/config.py` OPENAI_*, `services/embedding_service.py`, `mapping_llm_*` | E11 AI grounding and citations | TC-11-001, TC-11-002, TC-11-008, TC-11-009, TC-21-011 | Model spend cap |
| 2 | S3-compatible object storage (MinIO in dev) | Storage | `services/storage.py`, S3_* | E10 Jobs storage and consistency | TC-10-005, TC-10-006, TC-06-006, TC-27-002 | Hosting/accounts |
| 3 | SMTP email | Email | `services/email_service.py` | E19 Slack Gmail and notification delivery | TC-19-008, TC-04-002 | Sending domain |
| 4 | Stripe | Payments | STRIPE_*, `api/routes/billing.py` | E24 Billing entitlements and credit ledger | TC-24-001..005 | Pricing; buyer-owned Stripe account |
| 5 | Sentry | Error tracking | SENTRY_* | E26 Public traffic analytics and acquisition evidence | TC-26-018, TC-27-004 | Account |
| 6 | Google login | Identity | `services/oauth_service.py` | E05 MFA SSO and role policies | TC-05-004, TC-05-005 | Sandbox account |
| 7 | GitHub login | Identity | `core/config.py:131` | E05 MFA SSO and role policies | TC-05-004, TC-05-006 | Sandbox account |
| 8 | Microsoft login | Identity | `core/config.py:133` | E05 MFA SSO and role policies | TC-05-004, TC-05-007 | Sandbox account |
| 9 | Generic OIDC and ID.me | Identity | OIDC_*, IDME_*, `services/sso_service.py` | E05 MFA SSO and role policies | TC-05-008, TC-05-009 | ID.me approval |
| 10 | Slack | Ingest + notify | `api/routes/slack*.py` | E19 Slack Gmail and notification delivery | TC-19-001..004 | Slack app/workspace |
| 11 | Gmail | Ingest + reply | `api/routes/gmail.py` | E19 Slack Gmail and notification delivery | TC-19-001, TC-19-005..007 | Google OAuth verification |
| 12 | AWS | Posture connector | `aws_connector` | E20 Cloud directory code and CRM integrations | TC-20-008..013 | Sandbox account |
| 13 | GitHub (connector) | Posture connector | `github_connector` | E20 Cloud directory code and CRM integrations | TC-20-014..019 | Sandbox org |
| 14 | Google Workspace | Posture connector | `google_connector` | E20 Cloud directory code and CRM integrations | TC-20-020..024 | Sandbox tenant |
| 15 | Google Cloud | Posture connector | `cloud_connector_service.py:12` | E20 Cloud directory code and CRM integrations | TC-20-025..030 | Sandbox project |
| 16 | Microsoft Azure | Posture connector | `cloud_connector_service.py:27` | E20 Cloud directory code and CRM integrations | TC-20-031..035 | Sandbox subscription |
| 17 | GitLab | Posture connector | `cloud_connector_service.py:42` | E20 Cloud directory code and CRM integrations | TC-20-036..040 | Sandbox group |
| 18 | Okta | Posture connector | `cloud_connector_service.py:57` | E20 Cloud directory code and CRM integrations | TC-20-041..045 | Sandbox org |
| 19 | Jira | Ingest connector | `source_registry_service.py:87` | E20 Cloud directory code and CRM integrations | TC-20-046..048 | Sandbox site |
| 20 | HRIS (generic; vendor unresolved) | Workforce connector | `cloud_connector_service.py:72` | E20 Cloud directory code and CRM integrations | TC-20-005 (spike), TC-20-006, TC-20-007 | **HRIS vendor selection** |
| 21 | Salesforce | CRM | `crm_connector_service.py` (mock at baseline) | E20 Cloud directory code and CRM integrations | TC-20-049..051 | Sandbox org |
| 22 | HubSpot | CRM | `crm_connector_service.py` (mock at baseline) | E20 Cloud directory code and CRM integrations | TC-20-052..054 | Sandbox portal |
| 23 | Google Analytics 4 | Public analytics | none at baseline | E26 Public traffic analytics and acquisition evidence | TC-26-002..008 | **GA4 property/domain** |
| 24 | Google Search Console | Public indexing | none at baseline | E26 Public traffic analytics and acquisition evidence | TC-26-011 | Domain |

scope-freeze amendment 2026-11-02: no provider was added on master. Two providers are approved for v1.1 under OD-11 (§11): Google Drive (TC-32-013) and Confluence (TC-32-014). Each needs real sandbox evidence like the rows above. PDF parsing is a library, not a provider: PyMuPDF (AGPL) was replaced by pypdf (BSD-3) in TC-01-003a (OD-2), and E37 replaces pypdf with the owned engine (TC-37-019).

Framework content (SOC 2, HIPAA, ISO 27001, NIST CSF 2, NIST 800-53 r5, NIST 800-171 r3, SIG, CAIQ, HITRUST) is in scope through TC-21-001 and TC-21-014..022. Content rights are covered by the new ticket **TC-01-007** (§8, ruling R3).

## 7. Explicitly out of scope

These are open-ended or "infinite" extensions. They are **not** part of the release contract, and not building them is not a gap. Adding any of them needs a linked ticket, estimate, and dependency under the change-control rule, plus an owner decision when it affects spend or terms.

- Providers or connectors not registered or advertised at baseline (for example Datadog, PagerDuty, ServiceNow, Linear, CrowdStrike, Jamf, Intune, Cloudflare, BambooHR beyond the **one** HRIS vendor chosen in TC-20-005). *Moved in by OD-11 (2026-11-02):* Google Drive (TC-32-013) and Confluence (TC-32-014) evidence sync, v1.1. TrustCopilot's own device agent (TC-34-009, v2.0) is not a Jamf or Intune connector; those stay out.
- A second model or embedding provider, self-hosted or fine-tuned models, or model switching without the TC-11-009 regression gate. One configured provider is sufficient (PRODUCT_SPEC §Architecture).
- Infrastructure beyond a single Linux x86-64 Docker Compose host: Kubernetes, multi-host HA, multi-region, or new queue or cache services, unless a measured need is ticketed (E27). *Moved in by OD-11:* an EU-region deployment of the same single-host stack, with documented data flows (TC-32-007, v1.1). Multi-region HA stays out.
- Compliance frameworks beyond the nine catalog tickets (for example PCI DSS, FedRAMP, CMMC, DORA, ISO 42001, EU AI Act catalogs). *Moved in by OD-11:* question packs, not full catalogs, for DORA (TC-32-004), NIS2 (TC-32-005) and EU AI Act and ISO 42001 sections (TC-32-012), v1.1. They follow the TC-01-007 content-rights rules. The full catalogs stay out until ticketed.
- Third-party certification or attestation of Trust Copilot itself (SOC 2 report, ISO certificate). The independent security review in E28 is in scope, but certification is not.
- Native mobile or desktop apps, browser extensions, and localization beyond English. *Moved in by OD-11:* the employee device agent (TC-34-009, v2.0) and the portal-questionnaire browser extension (TC-33-006, after v2.0). Reading Ukrainian, Polish and Romanian *source documents* (TC-32-009) and Ukrainian marketing material (TC-31-010, TC-31-014) are not UI localization: the product UI stays English.
- Questionnaire or evidence formats beyond those named in E08 and E09 tickets.
- New public developer API, SDK, or third-party webhooks beyond existing routes, and app-marketplace listing submissions. The E37 parsing API is a **separate product** in its own repository (`pdf-engine`) and adds no public API to TrustCopilot. Only its TrustCopilot integration tickets are TrustCopilot scope (§11).
- Sending answers to customers without human review, and automated remediation beyond the approved, postcondition-verified flow in TC-22-013.
- Importers from competitor tools (for example Vanta, Drata, Loopio, OneTrust). TC-32-002 imports the customer's own past completed questionnaire files, not competitor-tool data, so this item stays out.
- Paid acquisition campaigns or ad spend, and content marketing beyond E15 copy/SEO and E26 measurement. The E31 and E33 go-to-market tasks are owner and sales work, not product scope. Any ad spend is still an owner decision.
- Support or feature work after handover beyond the capped support agreed in TC-30-005.

## 8. Coordinator rulings (recorded at freeze)

| # | Ruling | Backlog at baseline | Change | Rationale |
|---|---|---|---|---|
| R1 | **TC-12-004** (Preserve approved text through generation and cache hits) depends on **TC-12-002** and **TC-12-003** | `depends_on: ['TC-11-003', 'TC-11-001', 'TC-06-001']` | Replace with `[TC-12-002, TC-12-003]`. The prior three stay transitive because TC-12-002 and TC-12-003 each depend on them. | Preserving approved text needs the revision and concurrency model (TC-12-002) and explicit review states (TC-12-003) to exist first. |
| R2 | **TC-26-018** (Add scrubbed frontend errors and web-vitals diagnostics) does **not** depend on billing reconciliation | `depends_on: ['TC-26-014', 'TC-24-005', 'TC-07-011']` | Remove TC-24-005. Keep TC-26-014 and TC-07-011. | Frontend error and web-vitals diagnostics have no data or contract dependency on the billing or provider ledger. |
| R3 | **New ticket TC-01-007: Framework content rights (owner decision)** | none | Add to E01. Owner: Owner/seller. Gates release (G0/G5) for TC-21-001 and TC-21-014..022. Must state, for each of the nine framework catalogs, whether redistribution rights exist (licensed, public-domain such as NIST, or not permitted) and what content may ship. | Several catalogs (for example ISO 27001, HITRUST, SIG, CAIQ) are proprietary. The spec requires "legally permitted content", which is a rights decision, not an engineering one. |
| R4 | **E01 legal tickets gate release (G0/G5), not engineering start** | TC-01-002 (chain of title), TC-01-003 (PyMuPDF and restrictive licenses), TC-01-004 (license inventory) appear as `depends_on` of engineering tickets (new TC-01-007 applies the same way to the framework tickets): TC-02-002, TC-21-001, TC-09-007, TC-09-008, TC-21-014, TC-21-015, TC-21-016, TC-21-017, TC-21-018, TC-21-019, TC-21-020, TC-21-021, TC-21-022 | Engineering on these tickets may **start** before the legal tickets close. The legal tickets become **release gates**: none of these tickets can be marked release-qualified, and no release candidate may pass G0 (scope and rights path) or G5 (final rights clearance), until the gating legal ticket is accepted by the Owner/seller. Transfer deliverables (TC-29-006, TC-30-004) keep their hard dependency. | Rights resolution is an owner and counsel activity on a different critical path. Blocking engineering on it would idle the build without reducing legal risk. Engineering work that might be discarded (for example a PyMuPDF replacement) should be isolated behind interfaces. |

These rulings change dependency edges in the package backlog. The package JSON is not edited by this PR. The backlog owner should apply R1–R4 to `TrustCopilot_Execution_Backlog.json` and add TC-01-007 on the next package revision. Until then, this file takes precedence.

## 9. Owner-epic summary

| Epic | Surfaces owned (API + pages) |
|---|---|
| E04 Accounts and sessions | 1 |
| E08 Evidence lifecycle and privacy | 5 |
| E09 Questionnaire intake and mapping | 1 |
| E10 Jobs storage and consistency | 1 |
| E12 Review approval and reusable knowledge | 11 |
| E13 Workbook and evidence exports | 2 |
| E14 Design system and accessibility | 2 |
| E15 Every screen and missing workflow UI | 39 |
| E16 Workspace administration audit and API usability | 4 |
| E17 Trust center public sharing and NDA | 8 |
| E18 Trust requests and vendor responses | 3 |
| E19 Slack Gmail and notification delivery | 5 |
| E20 Cloud directory code and CRM integrations | 9 |
| E21 Compliance controls mappings and gaps | 14 |
| E22 Monitoring alerts and remediation | 12 |
| E23 Deals contracts promises and proof | 6 |
| E24 Billing entitlements and credit ledger | 3 |
| E25 Product reporting and analytics | 12 |
| **Total** | **138** |

Amended 2026-11-02: +10 pages (§4 rows 35–44). The route-module count is unchanged.

## 10. Acceptance mapping

- **TC-01-001-AC1:** §3 covers all 94 route modules (531 static operations on master `574f2e2`; 497 after the 2026-10-27 amendment; baseline 489), §4 all 44 page routes (43 page files plus the row-22 redirect; baseline 33), §5 the dispatchers, and §6 the registered or advertised providers. Each has an owner epic and named acceptance tickets. Mechanical check: `artifacts/acceptance/TC-01-001/check_scope_freeze.py`.
- **TC-01-001-AC2:** Freeze rule 2 forbids silent disabling as completion. §7 lists the out-of-scope extensions explicitly.
- Post-freeze scope (2026-11-02): §11 maps every epic added after the freeze (E31–E37, 123 Jira tickets) to a release, an owner and its gates. Every §7 item moved into scope cites owner decision OD-11.
- Owner acceptance: **accepted by the Owner/seller (Johnathan Reinhart) on 2026-11-02** with the instruction to bring the freeze up to date and resolve it (recorded as OD-11 in `release-decisions.md`). Per the ticket DoD, the named accountable owner reviews this file. The Coordinator signs for scope; the Owner/seller signs for R3/R4 rights gating (`release-decisions.md`).

## 11. Post-freeze scope (change control, 2026-11-02)

Seven epics were added in Jira after the freeze. The owner approved them on 2026-11-02 (OD-11), which also records the approvals asked for in TC-32-011 and TC-34-012. They are tracked **outside** the original 384-ticket, 1,864-point denominator, as TC-01-006a requires for added work. Each row belongs to the release named here and is required only for that release; nothing in v1.1 or v2.0 blocks v1.0 acceptance.

| Epic | Jira | What it adds | Tickets | Release | Gates and notes |
|---|---|---|---|---|---|
| E31 Wedge validation and go-to-market (CEE vendors) | SCRUM-420 | Discovery calls, pilots, partners, pricing, the Nov 30 go/kill decision | 18 owner tasks | None (go-to-market, not product) | TC-31-015 US company and Stripe gates live billing for E35, E36 and E37 |
| E32 Wedge product: vendor-side fidelity and DORA | SCRUM-421 | Fidelity suite, past-questionnaire import, vendor profile, DORA, NIS2 and AI-Act packs, continuity pack, EU hosting, non-English sources, consultant workspace, Google Drive and Confluence sync | 14 | **v1.0:** TC-32-001 (already in scope as an E13 extension) and TC-32-010 (consultant workspace, needed by E35). **v1.1 (by May 28, 2027):** the rest | TC-32-008 (AI provider EU data handling) stays an owner decision. TC-32-011 is approved by OD-11. Story points are still to be estimated, which is required before any completion claim (change-control rule 1) |
| E33 Scale the wedge to $1M ARR | SCRUM-422 | Revenue gates, regional expansion, competitor watch | 9 | None (go-to-market), except TC-33-006 browser extension after v2.0 | Revenue gates are owner decisions |
| E34 Compliance automation platform | SCRUM-464 | Policy library and writer, policy lifecycle and acceptance, employee roster and portal, security training, on/offboarding checks, device agent, audit-readiness dashboard, pilot qualification | 12 | **v2.0 (Feb 16 to Dec 17, 2027)**, sequenced after v1.0 and E32 | TC-34-012 approved by OD-11. Policy and training content must be original (TC-01-007). Story points still to be estimated |
| E35 MSP and vCISO edition | SCRUM-477 | MSP roles, client workspaces, portfolio dashboard, client switcher, isolation tests, branding, white-label exports and trust page, MSP templates, MSP billing | 14 (71 pts) | **v1.0 (Dec 15, 2026)** | Owner-approved 2026-11-01. TC-35-011 SIG, CAIQ and HECVAT templates are gated by OD-3 and TC-01-007. TC-35-012 pricing is an owner decision |
| E36 MSP wedge: questionnaire-first, low price, full white-label | SCRUM-492 | Questionnaire-only workspaces, zero-touch provisioning, single intake, digest, pricing page, ROI calculator, self-serve trial, white-label email and portal, brand-leak test | 11 (38 pts) | **v1.0 (Dec 15, 2026)** | TC-36-005 prices are an owner decision. The ROI default must agree with billing (OD-8) |
| E37 PDF engine and parsing API | SCRUM-505 | Owned Rust PDF engine in the separate `pdf-engine` repository, sold separately as a parsing API | 45 (204 pts) | **Separate product** (May 9, 2027). TrustCopilot scope is only TC-37-019 (pypdf replaced by the engine, Jan 31), TC-37-031 (answers filled into the vendor's own PDF, Mar 28) and TC-37-036 (evidence OCR, Apr 18), all v1.1 | Decisions TC-37-001 done 2026-11-02. API prices TC-37-041 deferred to Mar 2027. Live API billing needs TC-31-015 |

**Releases.**
- **v1.0 (Dec 15, 2026):** §3–§6 inventory, E35, E36, TC-32-001 and TC-32-010.
- **v1.1 (by May 28, 2027):** the rest of E32, plus the three E37 TrustCopilot integration tickets.
- **v2.0 (by Dec 17, 2027):** E34.
- **After v2.0:** TC-33-006.

Any further addition follows the change-control rule (`release-decisions.md` §2) and is added to this table.

