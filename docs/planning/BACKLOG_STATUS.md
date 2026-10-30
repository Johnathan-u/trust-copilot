# Backlog status — historical PR inventory

> **Superseded for current status on 2026-10-30.** Use the [shared tracker](../tracker/index.html),
> [machine-readable state](backlog-state.json) and [PM protocol](../release/PM_BACKLOG_PROTOCOL.md).
> This dated PR-title inventory is retained for traceability. Its merged counts
> are not accepted-ticket completion and must not be used as the current percentage.

Generated 2026-10-29 from master d9ab8b6 and public PR titles (last 100 merged PRs). Status is inferred from PR titles; confirm on #85 before claiming.

| Epic | Total | Merged | Open PR | Backlog |
|---|---|---|---|---|
| E01 | 6 | 3 | 0 | 3 |
| E02 | 9 | 4 | 0 | 5 |
| E03 | 7 | 2 | 0 | 5 |
| E04 | 7 | 0 | 0 | 7 |
| E05 | 10 | 0 | 0 | 10 |
| E06 | 6 | 0 | 0 | 6 |
| E07 | 14 | 1 | 1 | 12 |
| E08 | 11 | 1 | 0 | 10 |
| E09 | 8 | 0 | 0 | 8 |
| E10 | 7 | 3 | 0 | 4 |
| E11 | 9 | 1 | 0 | 8 |
| E12 | 14 | 0 | 0 | 14 |
| E13 | 7 | 1 | 0 | 6 |
| E14 | 13 | 4 | 1 | 8 |
| E15 | 67 | 0 | 2 | 65 |
| E16 | 6 | 0 | 0 | 6 |
| E17 | 10 | 0 | 1 | 9 |
| E18 | 3 | 0 | 2 | 1 |
| E19 | 10 | 2 | 0 | 8 |
| E20 | 54 | 0 | 1 | 53 |
| E21 | 22 | 6 | 1 | 15 |
| E22 | 14 | 0 | 0 | 14 |
| E23 | 8 | 0 | 1 | 7 |
| E24 | 5 | 1 | 0 | 4 |
| E25 | 11 | 2 | 0 | 9 |
| E26 | 19 | 0 | 0 | 19 |
| E27 | 9 | 0 | 0 | 9 |
| E28 | 6 | 0 | 0 | 6 |
| E29 | 6 | 0 | 0 | 6 |
| E30 | 6 | 0 | 0 | 6 |

## E01

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-01-001 | Freeze full-suite scope and objective | Seller / product lead / counsel | merged #4 4d35f0d |
| TC-01-002 | Establish authorship and asset chain of title | Seller / product lead / counsel | backlog |
| TC-01-003 | Resolve PyMuPDF and other restrictive licenses | Seller / product lead / counsel | backlog |
| TC-01-004 | Generate exact dependency and asset license inventory | Seller / product lead / counsel | backlog |
| TC-01-005 | Replace unsupported product and traction claims | Seller / product lead / counsel | merged #2 d57821e |
| TC-01-006 | Define release decisions and change control | Seller / product lead / counsel | merged #3 f72def3 |

## E02

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-02-001 | Isolate test collection from live services | Technical lead | merged #20 1661bd5 |
| TC-02-002 | Lock compatible Python and PostgreSQL driver dependencies | Technical lead | merged #42 a339a55 |
| TC-02-003 | Upgrade and lock supported frontend dependencies | Technical lead | merged #9 1eaf03e |
| TC-02-004 | Create disposable exact-stack test infrastructure | Technical lead | backlog |
| TC-02-005 | Establish backend lint type and unit checks | Technical lead | backlog |
| TC-02-006 | Add meaningful frontend unit lint and formatting gates | Technical lead | merged #10 a64db44 |
| TC-02-007 | Run database storage and browser tests in CI | Technical lead | backlog |
| TC-02-008 | Add secret dependency license and image checks | Technical lead | backlog |
| TC-02-009 | Retain redacted release and failure evidence | Technical lead | backlog |

## E03

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-03-001 | Validate configuration and forbid unsafe production defaults | Platform / backend engineer | merged #14 6a04247 |
| TC-03-002 | Build secure persistent Compose services | Platform / backend engineer | backlog |
| TC-03-003 | Separate readiness liveness and worker health | Platform / backend engineer | merged #19 3fc621f |
| TC-03-004 | Qualify existing migration chain and audited-data upgrade | Platform / backend engineer | backlog |
| TC-03-005 | Serialize migrations and test interruption recovery | Platform / backend engineer | backlog |
| TC-03-006 | Produce immutable minimal release images | Platform / backend engineer | backlog |
| TC-03-007 | Rehearse version upgrade and rollback | Platform / backend engineer | backlog |

## E04

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-04-001 | Complete verified registration and isolated workspace creation | Backend / frontend engineer | backlog |
| TC-04-002 | Make verify invite and reset tokens single-use and bounded | Backend / frontend engineer | backlog |
| TC-04-003 | Invalidate authority after password change or reset | Backend / frontend engineer | backlog |
| TC-04-004 | Require expiration session record and current authority | Backend / frontend engineer | backlog |
| TC-04-005 | Revoke demoted removed and suspended member access | Backend / frontend engineer | backlog |
| TC-04-006 | Enforce idle absolute and remember-me lifetimes | Backend / frontend engineer | backlog |
| TC-04-007 | Bound identity abuse and account enumeration | Backend / frontend engineer | backlog |

## E05

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-05-001 | Implement verified TOTP enrollment and challenge | Identity / security engineer | backlog |
| TC-05-002 | Complete one-use recovery codes and owner recovery | Identity / security engineer | backlog |
| TC-05-003 | Define owner admin editor reviewer viewer and custom roles | Identity / security engineer | backlog |
| TC-05-004 | Implement browser-bound OAuth state PKCE and identity linking | Identity / security engineer | backlog |
| TC-05-005 | Qualify Google login and disconnect | Identity / security engineer | backlog |
| TC-05-006 | Qualify GitHub login and disconnect | Identity / security engineer | backlog |
| TC-05-007 | Qualify Microsoft login and tenant policy | Identity / security engineer | backlog |
| TC-05-008 | Qualify generic OIDC and ID.me paths | Identity / security engineer | backlog |
| TC-05-009 | Complete SSO enforcement and deprovisioning rules | Identity / security engineer | backlog |
| TC-05-010 | Separate deployment operators from workspace administrators | Identity / security engineer | backlog |

## E06

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-06-001 | Centralize principal construction and membership checks | Security / backend engineer | backlog |
| TC-06-002 | Enforce object permissions on the core workflow | Security / backend engineer | backlog |
| TC-06-003 | Enforce permissions on all expanded domain objects | Security / backend engineer | backlog |
| TC-06-004 | Separate public token grants from signed-in access | Security / backend engineer | backlog |
| TC-06-005 | Generate endpoint-by-role-by-tenant regression coverage | Security / backend engineer | backlog |
| TC-06-006 | Bind storage cache and background access to tenant authority | Security / backend engineer | backlog |

## E07

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-07-001 | Contain exposed signing literals cookies and traces | Security engineer / independent reviewer | merged #40 f7468ff |
| TC-07-002 | Separate key purposes and rehearse credential migration | Security engineer / independent reviewer | open PR #93 |
| TC-07-003 | Reject dangerous post-login URLs | Security engineer / independent reviewer | backlog |
| TC-07-004 | Enforce trusted origin host and proxy boundaries | Security engineer / independent reviewer | backlog |
| TC-07-005 | Constrain browser scripts markup and security headers | Security engineer / independent reviewer | backlog |
| TC-07-006 | Reject oversized uploads before buffering | Security engineer / independent reviewer | backlog |
| TC-07-007 | Isolate parsers and bound archive complexity | Security engineer / independent reviewer | backlog |
| TC-07-008 | Harden private bucket and signed downloads | Security engineer / independent reviewer | backlog |
| TC-07-009 | Block SSRF and unconstrained outbound calls | Security engineer / independent reviewer | backlog |
| TC-07-010 | Test SQL command template and spreadsheet injection boundaries | Security engineer / independent reviewer | backlog |
| TC-07-011 | Redact secrets and sensitive evidence from diagnostics | Security engineer / independent reviewer | backlog |
| TC-07-012 | Map attack paths to ASVS 5 requirements | Security engineer / independent reviewer | backlog |
| TC-07-013 | Independently verify release security and retest fixes | Security engineer / independent reviewer | backlog |
| TC-07-014 | Define vulnerability response and update ownership | Security engineer / independent reviewer | backlog |

## E08

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-08-001 | Preserve immutable document versions and source locators | Backend / privacy owner | backlog |
| TC-08-002 | Report unsupported and empty evidence honestly | Backend / privacy owner | backlog |
| TC-08-003 | Promote only complete successful indexes | Backend / privacy owner | backlog |
| TC-08-004 | Scope retrieval and caches to eligible source versions | Backend / privacy owner | backlog |
| TC-08-005 | Remove shared SQLAlchemy Sessions across worker threads | Backend / privacy owner | merged #1 1d15cf1 |
| TC-08-006 | Invalidate source support on archive or replacement | Backend / privacy owner | backlog |
| TC-08-007 | Delete source-derived content and prevent resurrection | Backend / privacy owner | backlog |
| TC-08-008 | Implement owner data export retention and workspace deletion | Backend / privacy owner | backlog |
| TC-08-009 | Document data region subprocessors and model submission behavior | Backend / privacy owner | backlog |
| TC-08-010 | Complete search APIs and cross-source result navigation | Backend / privacy owner | backlog |
| TC-08-011 | Complete tag taxonomy aliases and source classification | Backend / privacy owner | backlog |

## E09

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-09-001 | Correct numbered uppercase and multi-section detection | Backend / frontend engineer | backlog |
| TC-09-002 | Persist per-question original workbook answer-cell mapping | Backend / frontend engineer | backlog |
| TC-09-003 | Build mapping preview and correction workflow | Backend / frontend engineer | backlog |
| TC-09-004 | Detect unsupported workbook structures before processing | Backend / frontend engineer | backlog |
| TC-09-005 | Qualify DOCX and text-PDF questionnaire intake | Backend / frontend engineer | backlog |
| TC-09-006 | Make repeat upload and parsing deterministic | Backend / frontend engineer | backlog |
| TC-09-007 | Support existing DOC and XLS intake through isolated conversion | Backend / frontend engineer | backlog |
| TC-09-008 | Implement TXT questionnaire parsing and explicit output contract | Backend / frontend engineer | backlog |

## E10

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-10-001 | Implement periodic leases and abandoned-job recovery | Backend / platform engineer | merged #84 a2458c9 |
| TC-10-002 | Classify errors and apply bounded retries | Backend / platform engineer | merged #33 d28bcb6 |
| TC-10-003 | Make parse index generate and export side effects idempotent | Backend / platform engineer | merged #28 d527863 |
| TC-10-004 | Implement cancellation and audited manual retry | Backend / platform engineer | backlog |
| TC-10-005 | Coordinate transaction job enqueue and storage writes | Backend / platform engineer | backlog |
| TC-10-006 | Persist original and export hashes in private storage | Backend / platform engineer | backlog |
| TC-10-007 | Verify persistent data after service and host restart | Backend / platform engineer | backlog |

## E11

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-11-001 | Define typed model responses and failures | AI/backend engineer / domain reviewer | merged #16 1a0e614 |
| TC-11-002 | Bound context tokens retries and per-workspace spend | AI/backend engineer / domain reviewer | backlog |
| TC-11-003 | Validate claim-specific citation identifiers and quotes | AI/backend engineer / domain reviewer | backlog |
| TC-11-004 | Open cited source at its actual support location | AI/backend engineer / domain reviewer | backlog |
| TC-11-005 | Enforce abstention contradiction and untrusted-evidence rules | AI/backend engineer / domain reviewer | backlog |
| TC-11-006 | Replace misleading confidence percentages | AI/backend engineer / domain reviewer | backlog |
| TC-11-007 | Create separate development and held-out ground truth | AI/backend engineer / domain reviewer | backlog |
| TC-11-008 | Run and grade three independent real-model holdouts | AI/backend engineer / domain reviewer | backlog |
| TC-11-009 | Gate model prompt and embedding upgrades with regression | AI/backend engineer / domain reviewer | backlog |

## E12

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-12-001 | Repair first-answer and bulk route contracts | Full-stack engineer | backlog |
| TC-12-002 | Persist edits with revision and optimistic concurrency | Full-stack engineer | backlog |
| TC-12-003 | Implement explicit review status transitions and audit | Full-stack engineer | backlog |
| TC-12-004 | Preserve approved text through generation and cache hits | Full-stack engineer | backlog |
| TC-12-005 | Golden answer library versioning and reuse | Full-stack engineer | backlog |
| TC-12-006 | Reusable answer approval events | Full-stack engineer | backlog |
| TC-12-007 | Evidence approval and reset lifecycle | Full-stack engineer | backlog |
| TC-12-008 | Answer tier classification and overrides | Full-stack engineer | backlog |
| TC-12-009 | Knowledge pack lifecycle and portable exports | Full-stack engineer | backlog |
| TC-12-010 | Citation composition with actual support | Full-stack engineer | backlog |
| TC-12-011 | Explainable confidence scoring | Full-stack engineer | backlog |
| TC-12-012 | Confidence routing and review queues | Full-stack engineer | backlog |
| TC-12-013 | Evidence card detail and provenance | Full-stack engineer | backlog |
| TC-12-014 | Bounded contextual feedback capture | Full-stack engineer | backlog |

## E13

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-13-001 | Write answers to explicit original workbook targets | Backend engineer / QA | backlog |
| TC-13-002 | Preserve the supported workbook structure | Backend engineer / QA | backlog |
| TC-13-003 | Write formula-like answers as literal spreadsheet text | Backend engineer / QA | merged #7 5c8f1dc |
| TC-13-004 | Enforce eligible approval snapshots and unresolved manifest | Backend engineer / QA | backlog |
| TC-13-005 | Report export failures without format substitution | Backend engineer / QA | backlog |
| TC-13-006 | Complete citation and evidence package exports | Backend engineer / QA | backlog |
| TC-13-007 | Auditable export pack assembly API | Backend engineer / QA | backlog |

## E14

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-14-001 | Define typography color spacing and interaction tokens | Frontend / product designer | merged #6 705bdde |
| TC-14-002 | Unify buttons inputs selects and form validation | Frontend / product designer | backlog |
| TC-14-003 | Repair dialog focus and accessible notifications | Frontend / product designer | merged #21 58b8c87 |
| TC-14-004 | Build consistent tables filters pagination and bulk selection | Frontend / product designer | backlog |
| TC-14-005 | Unify loading empty error retry and partial-success states | Frontend / product designer | merged #66 e17d8e5 |
| TC-14-006 | Replace fixed sidebar grid with responsive navigation | Frontend / product designer | merged #15 a516c77 |
| TC-14-007 | Unify breadcrumbs tabs deep links and return navigation | Frontend / product designer | backlog |
| TC-14-008 | Write accurate concise action and error copy | Frontend / product designer | open PR #75 |
| TC-14-009 | Qualify keyboard screen-reader and WCAG 2.2 AA behavior | Frontend / product designer | backlog |
| TC-14-010 | Set visual regression baselines and polish budget | Frontend / product designer | backlog |
| TC-14-011 | Polish progress transitions and reduced-motion behavior | Frontend / product designer | backlog |
| TC-14-012 | Set and verify public-page and application performance budgets | Frontend / product designer | backlog |
| TC-14-013 | Qualify Chromium Firefox and WebKit core workflows | Frontend / product designer | backlog |

## E15

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-15-001 | Finish and polish / | Frontend / full-stack engineer | backlog |
| TC-15-002 | Finish and polish /pricing | Frontend / full-stack engineer | backlog |
| TC-15-003 | Finish and polish /checkout | Frontend / full-stack engineer | backlog |
| TC-15-004 | Finish and polish /login | Frontend / full-stack engineer | backlog |
| TC-15-005 | Finish and polish /register | Frontend / full-stack engineer | backlog |
| TC-15-006 | Finish and polish /forgot-password | Frontend / full-stack engineer | backlog |
| TC-15-007 | Finish and polish /reset-password | Frontend / full-stack engineer | backlog |
| TC-15-008 | Finish and polish /verify-email | Frontend / full-stack engineer | backlog |
| TC-15-009 | Finish and polish /accept-invite | Frontend / full-stack engineer | backlog |
| TC-15-010 | Finish and polish /onboarding | Frontend / full-stack engineer | backlog |
| TC-15-011 | Finish and polish /trust | Frontend / full-stack engineer | backlog |
| TC-15-012 | Finish and polish /trust/[slug] | Frontend / full-stack engineer | backlog |
| TC-15-013 | Finish and polish /vendor-response — part 1 | Frontend / full-stack engineer | backlog |
| TC-15-014 | Finish and polish /vendor-response — part 2 | Frontend / full-stack engineer | backlog |
| TC-15-015 | Finish and polish /dashboard | Frontend / full-stack engineer | backlog |
| TC-15-016 | Finish and polish /dashboard/documents | Frontend / full-stack engineer | backlog |
| TC-15-017 | Finish and polish /dashboard/questionnaires | Frontend / full-stack engineer | backlog |
| TC-15-018 | Finish and polish /dashboard/questionnaires/[id] | Frontend / full-stack engineer | backlog |
| TC-15-019 | Finish and polish /dashboard/review | Frontend / full-stack engineer | backlog |
| TC-15-020 | Finish and polish /dashboard/review/[id] — part 1 | Frontend / full-stack engineer | backlog |
| TC-15-021 | Finish and polish /dashboard/review/[id] — part 2 | Frontend / full-stack engineer | backlog |
| TC-15-022 | Finish and polish /dashboard/exports | Frontend / full-stack engineer | backlog |
| TC-15-023 | Finish and polish /dashboard/requests | Frontend / full-stack engineer | backlog |
| TC-15-024 | Finish and polish /dashboard/vendor-requests | Frontend / full-stack engineer | backlog |
| TC-15-025 | Finish and polish /dashboard/compliance-gaps | Frontend / full-stack engineer | open PR #92 |
| TC-15-026 | Finish and polish /dashboard/proof-chain | Frontend / full-stack engineer | backlog |
| TC-15-027 | Finish and polish /dashboard/trust-center | Frontend / full-stack engineer | backlog |
| TC-15-028 | Finish and polish /dashboard/members | Frontend / full-stack engineer | backlog |
| TC-15-029 | Finish and polish /dashboard/notifications | Frontend / full-stack engineer | backlog |
| TC-15-030 | Finish and polish /dashboard/slack | Frontend / full-stack engineer | backlog |
| TC-15-031 | Finish and polish /dashboard/gmail | Frontend / full-stack engineer | backlog |
| TC-15-032 | Finish and polish /dashboard/audit | Frontend / full-stack engineer | backlog |
| TC-15-033 | Finish and polish /dashboard/security | Frontend / full-stack engineer | backlog |
| TC-15-034 | Finish and polish /dashboard/settings | Frontend / full-stack engineer | backlog |
| TC-15-035 | Finish and polish /dashboard/ai-governance | Frontend / full-stack engineer | backlog |
| TC-15-036 | Connectors catalog and setup | Frontend / full-stack engineer | backlog |
| TC-15-037 | Credential custody and rotation | Frontend / full-stack engineer | backlog |
| TC-15-038 | Job and activity center | Frontend / full-stack engineer | backlog |
| TC-15-039 | Incoming Trust request inbox | Frontend / full-stack engineer | backlog |
| TC-15-040 | Share spaces and NDA administration | Frontend / full-stack engineer | backlog |
| TC-15-041 | Buyer portal publishing and preview | Frontend / full-stack engineer | backlog |
| TC-15-042 | Framework control library and control detail | Frontend / full-stack engineer | open PR #90 |
| TC-15-043 | Mapping and evidence review queue | Frontend / full-stack engineer | backlog |
| TC-15-044 | Evidence cards and approval workflow | Frontend / full-stack engineer | backlog |
| TC-15-045 | Freshness retention and workspace policy editor | Frontend / full-stack engineer | backlog |
| TC-15-046 | Monitoring alerts and timelines | Frontend / full-stack engineer | backlog |
| TC-15-047 | Remediation playbooks tickets and action approval | Frontend / full-stack engineer | backlog |
| TC-15-048 | Golden answers and knowledge packs | Frontend / full-stack engineer | backlog |
| TC-15-049 | Deal pipeline and CRM sync administration | Frontend / full-stack engineer | backlog |
| TC-15-050 | Contract ingestion clause review and amendments | Frontend / full-stack engineer | backlog |
| TC-15-051 | Promise register contradictions and expiry | Frontend / full-stack engineer | backlog |
| TC-15-052 | Billing subscriptions credit ledger and usage | Frontend / full-stack engineer | backlog |
| TC-15-053 | Executive benchmarks ROI and outcome reports | Frontend / full-stack engineer | backlog |
| TC-15-054 | Private product adoption and cohort report | Frontend / full-stack engineer | backlog |
| TC-15-055 | Deployment owner public traffic report | Frontend / full-stack engineer | backlog |
| TC-15-056 | Trust visitor and download report | Frontend / full-stack engineer | backlog |
| TC-15-057 | Feedback and case-study review | Frontend / full-stack engineer | backlog |
| TC-15-058 | Public security FAQ and incident administration | Frontend / full-stack engineer | backlog |
| TC-15-059 | Contextual support and help | Frontend / full-stack engineer | backlog |
| TC-15-060 | Create privacy cookies terms subprocessors and contact pages | Frontend / full-stack engineer | backlog |
| TC-15-061 | Create public status history and vulnerability-report flow | Frontend / full-stack engineer | backlog |
| TC-15-062 | Create branded 404 access-denied expired-session and unavailable screens | Frontend / full-stack engineer | backlog |
| TC-15-063 | Implement correct metadata sitemap robots and social previews | Frontend / full-stack engineer | backlog |
| TC-15-064 | Build operator queue assignment and resolution screen | Frontend / full-stack engineer | backlog |
| TC-15-065 | Public shared-space access and revocation | Frontend / full-stack engineer | backlog |
| TC-15-066 | Public buyer portal browse and scoped downloads | Frontend / full-stack engineer | backlog |
| TC-15-067 | NDA request acceptance and approved access | Frontend / full-stack engineer | backlog |

## E16

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-16-001 | Complete invitations suspension removal and owner transfer | Full-stack engineer | backlog |
| TC-16-002 | Refresh all context on workspace switching | Full-stack engineer | backlog |
| TC-16-003 | Record meaningful redacted audit events for critical actions | Full-stack engineer | backlog |
| TC-16-004 | Complete scoped API key lifecycle and documentation | Full-stack engineer | backlog |
| TC-16-005 | Publish stable API errors pagination and examples | Full-stack engineer | backlog |
| TC-16-006 | Make runtime feature flags safe and auditable | Full-stack engineer | backlog |

## E17

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-17-001 | Trust article draft version publication and acknowledgment | Full-stack engineer | backlog |
| TC-17-002 | Policy-driven Trust publication | Full-stack engineer | backlog |
| TC-17-003 | Configurable evidence-backed public security claims | Full-stack engineer | backlog |
| TC-17-004 | Reviewed FAQ authoring and publication | Full-stack engineer | open PR #91 (draft) |
| TC-17-005 | Scoped share spaces and revocable asset grants | Full-stack engineer | backlog |
| TC-17-006 | NDA request review access and withdrawal | Full-stack engineer | backlog |
| TC-17-007 | Working buyer portal manifest and gated assets | Full-stack engineer | backlog |
| TC-17-008 | Qualify buyer instant-match disclosure and review thresholds | Full-stack engineer | backlog |
| TC-17-009 | Implement semantic portal snapshots changes and subscriptions | Full-stack engineer | backlog |
| TC-17-010 | Complete buyer escalations and satisfaction feedback | Full-stack engineer | backlog |

## E18

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-18-001 | Incoming Trust intake assignment and reviewed reply | Full-stack engineer | open PR #88 (draft) |
| TC-18-002 | Outbound vendor request creation expiry and completion | Full-stack engineer | open PR #86 (draft) |
| TC-18-003 | Secure vendor response save resume and submit | Full-stack engineer | backlog |

## E19

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-19-001 | Wire real Slack and Gmail providers by configuration | Integration engineer | merged #12 4848666 |
| TC-19-002 | Complete Slack install permissions and disconnect | Integration engineer | backlog |
| TC-19-003 | Implement actual Slack message thread and file ingestion | Integration engineer | backlog |
| TC-19-004 | Complete approved Slack notifications and responses | Integration engineer | backlog |
| TC-19-005 | Complete Gmail OAuth and mailbox selection | Integration engineer | backlog |
| TC-19-006 | Implement real Gmail email and attachment intake | Integration engineer | backlog |
| TC-19-007 | Send reviewed Gmail replies with correct threading | Integration engineer | backlog |
| TC-19-008 | Complete email in-app and channel delivery preferences | Integration engineer | merged #27 9c7f899 |
| TC-19-009 | Notification rules templates and delivery log APIs | Integration engineer | backlog |
| TC-19-010 | Personal notification inbox and preferences | Integration engineer | backlog |

## E20

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-20-001 | Define versioned provider adapter and observation contracts | Integration engineer | open PR #5 |
| TC-20-002 | Implement encrypted credential lifecycle and least privileges | Integration engineer | backlog |
| TC-20-003 | Implement real cadence checkpoints and sync status | Integration engineer | backlog |
| TC-20-004 | Handle provider disconnect deletion and reconnect | Integration engineer | backlog |
| TC-20-005 | Resolve the generic HRIS provider into a concrete adapter specification | Integration engineer | backlog |
| TC-20-006 | Implement the selected HRIS workforce adapter | Integration engineer | backlog |
| TC-20-007 | Qualify HRIS provider and buyer setup | Integration engineer | backlog |
| TC-20-008 | AWS connection verification and permissions | Integration engineer | backlog |
| TC-20-009 | IAM identity access and credential posture | Integration engineer | backlog |
| TC-20-010 | S3 access encryption and versioning | Integration engineer | backlog |
| TC-20-011 | CloudTrail logging and region coverage | Integration engineer | backlog |
| TC-20-012 | AWS Security Hub findings | Integration engineer | backlog |
| TC-20-013 | AWS sandbox lifecycle and buyer qualification | Integration engineer | backlog |
| TC-20-014 | GitHub connection verification and permissions | Integration engineer | backlog |
| TC-20-015 | GitHub repository inventory | Integration engineer | backlog |
| TC-20-016 | GitHub organizational access | Integration engineer | backlog |
| TC-20-017 | GitHub branch and review policies | Integration engineer | backlog |
| TC-20-018 | GitHub security and Dependabot alerts | Integration engineer | backlog |
| TC-20-019 | GitHub sandbox lifecycle and buyer qualification | Integration engineer | backlog |
| TC-20-020 | Google Workspace connection verification and permissions | Integration engineer | backlog |
| TC-20-021 | Google Workspace users groups and organizational units | Integration engineer | backlog |
| TC-20-022 | Google Workspace authentication posture | Integration engineer | backlog |
| TC-20-023 | Google Workspace administrator roles | Integration engineer | backlog |
| TC-20-024 | Google Workspace sandbox lifecycle and buyer qualification | Integration engineer | backlog |
| TC-20-025 | Google Cloud connection verification and permissions | Integration engineer | backlog |
| TC-20-026 | GCP IAM and service-account posture | Integration engineer | backlog |
| TC-20-027 | GCP audit logging and organization policy | Integration engineer | backlog |
| TC-20-028 | GCP KMS encryption and network logging | Integration engineer | backlog |
| TC-20-029 | GCP Security Command Center findings | Integration engineer | backlog |
| TC-20-030 | Google Cloud sandbox lifecycle and buyer qualification | Integration engineer | backlog |
| TC-20-031 | Microsoft Azure connection verification and permissions | Integration engineer | backlog |
| TC-20-032 | Azure directory roles and authentication | Integration engineer | backlog |
| TC-20-033 | Azure resource and subscription policy | Integration engineer | backlog |
| TC-20-034 | Azure Defender and Key Vault posture | Integration engineer | backlog |
| TC-20-035 | Microsoft Azure sandbox lifecycle and buyer qualification | Integration engineer | backlog |
| TC-20-036 | GitLab connection verification and permissions | Integration engineer | backlog |
| TC-20-037 | GitLab projects members and authentication | Integration engineer | backlog |
| TC-20-038 | GitLab protected branches and merge requirements | Integration engineer | backlog |
| TC-20-039 | GitLab security and container scan results | Integration engineer | backlog |
| TC-20-040 | GitLab sandbox lifecycle and buyer qualification | Integration engineer | backlog |
| TC-20-041 | Okta connection verification and permissions | Integration engineer | backlog |
| TC-20-042 | Okta users groups and app assignments | Integration engineer | backlog |
| TC-20-043 | Okta MFA SSO session and password policy | Integration engineer | backlog |
| TC-20-044 | Okta API credential hygiene | Integration engineer | backlog |
| TC-20-045 | Okta sandbox lifecycle and buyer qualification | Integration engineer | backlog |
| TC-20-046 | Jira connection verification and permissions | Integration engineer | backlog |
| TC-20-047 | Jira security vulnerability incident and risk ingestion | Integration engineer | backlog |
| TC-20-048 | Jira sandbox lifecycle and buyer qualification | Integration engineer | backlog |
| TC-20-049 | Salesforce account OAuth and pipeline setup | Integration engineer | backlog |
| TC-20-050 | Salesforce real incremental deal synchronization | Integration engineer | backlog |
| TC-20-051 | Salesforce end-to-end sync and takeover qualification | Integration engineer | backlog |
| TC-20-052 | HubSpot account OAuth and pipeline setup | Integration engineer | backlog |
| TC-20-053 | HubSpot real incremental deal synchronization | Integration engineer | backlog |
| TC-20-054 | HubSpot end-to-end sync and takeover qualification | Integration engineer | backlog |

## E21

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-21-001 | Licensed versioned framework catalog enablement | Domain / full-stack engineer | merged #8 b0a49e4 |
| TC-21-002 | Legacy and canonical control contract reconciliation | Domain / full-stack engineer | merged #45 c66346c |
| TC-21-003 | Control library lifecycle and evidence verification | Domain / full-stack engineer | merged #61 a53dc7c |
| TC-21-004 | Control evidence content and metadata contracts | Domain / full-stack engineer | backlog |
| TC-21-005 | Human-reviewed framework control mapping overrides | Domain / full-stack engineer | merged #72 6a26d60 |
| TC-21-006 | Explainable compliance gaps and review workflow | Domain / full-stack engineer | merged #76 7b8ad5b |
| TC-21-007 | Reproducible framework coverage denominators | Domain / full-stack engineer | merged #80 fcda1f1 |
| TC-21-008 | Scoped actionable compliance alerts | Domain / full-stack engineer | backlog |
| TC-21-009 | Consistent safe compliance exports | Domain / full-stack engineer | backlog |
| TC-21-010 | Compliance audit settings and webhook controls | Domain / full-stack engineer | backlog |
| TC-21-011 | Reviewable AI mapping suggestions and precedence | Domain / full-stack engineer | backlog |
| TC-21-012 | Accurate AI governance insights and tuning | Domain / full-stack engineer | backlog |
| TC-21-013 | Evidence gap ownership and resolution | Domain / full-stack engineer | open PR #83 |
| TC-21-014 | Qualify SOC2 framework catalog and mapping fixtures | Domain / full-stack engineer | backlog |
| TC-21-015 | Qualify HIPAA framework catalog and mapping fixtures | Domain / full-stack engineer | backlog |
| TC-21-016 | Qualify ISO 27001 framework catalog and mapping fixtures | Domain / full-stack engineer | backlog |
| TC-21-017 | Qualify NIST CSF 2 framework catalog and mapping fixtures | Domain / full-stack engineer | backlog |
| TC-21-018 | Qualify NIST 800-53 revision 5 framework catalog and mapping fixtures | Domain / full-stack engineer | backlog |
| TC-21-019 | Qualify NIST 800-171 revision 3 framework catalog and mapping fixtures | Domain / full-stack engineer | backlog |
| TC-21-020 | Qualify SIG framework catalog and mapping fixtures | Domain / full-stack engineer | backlog |
| TC-21-021 | Qualify CAIQ framework catalog and mapping fixtures | Domain / full-stack engineer | backlog |
| TC-21-022 | Qualify HITRUST framework catalog and mapping fixtures | Domain / full-stack engineer | backlog |

## E22

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-22-001 | Idempotent normalized provider ingestion | Backend / operations engineer | backlog |
| TC-22-002 | Versioned control predicates and truthful evaluation | Backend / operations engineer | backlog |
| TC-22-003 | Repeatable control timeline and snapshots | Backend / operations engineer | backlog |
| TC-22-004 | Durable scheduled monitoring pipeline | Backend / operations engineer | backlog |
| TC-22-005 | Alert acknowledgment suppression and escalation | Backend / operations engineer | backlog |
| TC-22-006 | Deduplicated drift connector stale and digest alerts | Backend / operations engineer | backlog |
| TC-22-007 | Remediation ticket playbook evidence and audit lifecycle | Backend / operations engineer | backlog |
| TC-22-008 | Deterministic effective freshness policy | Backend / operations engineer | backlog |
| TC-22-009 | Persisted provider signal to control mappings | Backend / operations engineer | backlog |
| TC-22-010 | Deadline SLA and business-calendar behavior | Backend / operations engineer | backlog |
| TC-22-011 | Operator work queue claim and resolution | Backend / operations engineer | backlog |
| TC-22-012 | Semantic evidence and control snapshot diffs | Backend / operations engineer | backlog |
| TC-22-013 | Implement approved real remediation with verified postconditions | Backend / operations engineer | backlog |
| TC-22-014 | Derive remediation impact from actual source dependency graph | Backend / operations engineer | backlog |

## E23

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-23-001 | Typed scoped deals rooms and questionnaire links | Domain / full-stack engineer | open PR #96 |
| TC-23-002 | Stored original contracts and amendment lifecycle | Domain / full-stack engineer | backlog |
| TC-23-003 | Editable promise obligations contradiction and expiry lifecycle | Domain / full-stack engineer | backlog |
| TC-23-004 | Stable atomic proof graph and actual artifact integrity | Domain / full-stack engineer | backlog |
| TC-23-005 | Honest proof widgets and resource counters | Domain / full-stack engineer | backlog |
| TC-23-006 | Scoped answer delivery outcome records | Domain / full-stack engineer | backlog |
| TC-23-007 | Replace invented contract clauses with reviewed source-span extraction | Domain / full-stack engineer | backlog |
| TC-23-008 | Make deal risk and influenced-revenue claims scoped and explainable | Domain / full-stack engineer | backlog |

## E24

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-24-001 | Configure buyer-owned Stripe sandbox and webhook trust | Backend / payments engineer | merged #23 e1eb675 |
| TC-24-002 | Complete checkout renewal downgrade cancellation and portal | Backend / payments engineer | backlog |
| TC-24-003 | Make reservations settlement and refunds idempotent | Backend / payments engineer | backlog |
| TC-24-004 | Enforce plan and workspace resource limits everywhere | Backend / payments engineer | backlog |
| TC-24-005 | Reconcile provider events ledger and measured model usage | Backend / payments engineer | backlog |

## E25

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-25-001 | Persisted role-aware dashboard configuration | Full-stack / analytics engineer | backlog |
| TC-25-002 | Reconciled executive reports and date filters | Full-stack / analytics engineer | backlog |
| TC-25-003 | Valid questionnaire benchmarks and turnaround | Full-stack / analytics engineer | backlog |
| TC-25-004 | Transparent ROI assumptions and sensitivity | Full-stack / analytics engineer | backlog |
| TC-25-005 | Consent-backed case study authoring publication | Full-stack / analytics engineer | merged #25 b73be31 |
| TC-25-006 | Validated first-party event ingestion and query contracts | Full-stack / analytics engineer | backlog |
| TC-25-007 | Reconciled reusable-answer analytics | Full-stack / analytics engineer | backlog |
| TC-25-008 | Actual Trust view request and download measurement | Full-stack / analytics engineer | backlog |
| TC-25-009 | Measured service indicators and transparent windows | Full-stack / analytics engineer | backlog |
| TC-25-010 | Actual incident maintenance and vulnerability intake | Full-stack / analytics engineer | backlog |
| TC-25-011 | Evidence-backed demonstration proof summaries | Full-stack / analytics engineer | merged #30 9733c93 |

## E26

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-26-001 | Define traffic metrics event dictionary and privacy boundaries | Frontend / analytics owner | backlog |
| TC-26-002 | Set up dedicated buyer-transferable GA4 properties | Frontend / analytics owner | backlog |
| TC-26-003 | Implement basic opt-in consent with withdrawal | Frontend / analytics owner | backlog |
| TC-26-004 | Track sanitized public SPA page views exactly once | Frontend / analytics owner | backlog |
| TC-26-005 | Add allowlisted marketing CTA and demo events | Frontend / analytics owner | backlog |
| TC-26-006 | Prevent public analytics scripts leaking into private flows | Frontend / analytics owner | backlog |
| TC-26-007 | Separate QA internal bot and production traffic evidence | Frontend / analytics owner | backlog |
| TC-26-008 | Verify GA4 consent dedupe and production collection | Frontend / analytics owner | backlog |
| TC-26-009 | Build buyer-readable traffic acquisition and conversion report | Frontend / analytics owner | backlog |
| TC-26-010 | Add a protected owner analytics page with aggregate traffic | Frontend / analytics owner | backlog |
| TC-26-011 | Configure Search Console and public indexing evidence | Frontend / analytics owner | backlog |
| TC-26-012 | Document and rehearse the analytics transfer procedure | Frontend / analytics owner | backlog |
| TC-26-013 | Publish accurate cookie privacy and measurement notices | Frontend / analytics owner | backlog |
| TC-26-014 | Instrument real private product milestones in first-party ledger | Frontend / analytics owner | backlog |
| TC-26-015 | Report cohort conversion activation and retention honestly | Frontend / analytics owner | backlog |
| TC-26-016 | Reconcile real billing outcomes without false purchase events | Frontend / analytics owner | backlog |
| TC-26-017 | Instrument full-suite outcome events and delivery states | Frontend / analytics owner | backlog |
| TC-26-018 | Add scrubbed frontend errors and web-vitals diagnostics | Frontend / analytics owner | backlog |
| TC-26-019 | Preserve coarse attribution without sending raw referral or campaign input | Frontend / analytics owner | backlog |

## E27

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-27-001 | Make failed backup stages fail loudly and atomically | Platform engineer / QA | backlog |
| TC-27-002 | Back up database objects config and required keys consistently | Platform engineer / QA | backlog |
| TC-27-003 | Restore the full suite onto an empty isolated host | Platform engineer / QA | backlog |
| TC-27-004 | Monitor queues jobs provider spend storage and backup age | Platform engineer / QA | backlog |
| TC-27-005 | Rehearse operational and security incident response | Platform engineer / QA | backlog |
| TC-27-006 | Benchmark supported workload and pressure limits | Platform engineer / QA | backlog |
| TC-27-007 | Publish measured fixed variable and reindex operating costs | Platform engineer / QA | backlog |
| TC-27-008 | Qualify DNS TLS certificate renewal and sender deliverability | Platform engineer / QA | backlog |
| TC-27-009 | Harden hosts containers and storage administration | Platform engineer / QA | backlog |

## E28

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-28-001 | Map every audit finding to maintained failure-first regressions | QA / security / domain reviewers | backlog |
| TC-28-002 | Run fresh-account to evidence to approved workbook acceptance | QA / security / domain reviewers | backlog |
| TC-28-003 | Qualify every expanded feature together | QA / security / domain reviewers | backlog |
| TC-28-004 | Run complete browser accessibility and visual release matrix | QA / security / domain reviewers | backlog |
| TC-28-005 | Exercise cancellation crashes service outages and recovery | QA / security / domain reviewers | backlog |
| TC-28-006 | Produce final immutable release qualification dossier | QA / security / domain reviewers | backlog |

## E29

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-29-001 | Write and independently follow clean-install instructions | Technical writer / product owner | backlog |
| TC-29-002 | Document architecture schemas interfaces and threat boundaries | Technical writer / product owner | backlog |
| TC-29-003 | Write complete end-user and admin guides | Technical writer / product owner | backlog |
| TC-29-004 | Deliver operating upgrade restore security and privacy runbooks | Technical writer / product owner | backlog |
| TC-29-005 | Create repeatable synthetic full-suite demonstration | Technical writer / product owner | backlog |
| TC-29-006 | Assemble redacted buyer diligence and release asset package | Technical writer / product owner | backlog |

## E30

| Id | Title | Owner | Status |
|---|---|---|---|
| TC-30-001 | Provision buyer-owned service configuration and access schedule | Seller / buyer operator / counsel | backlog |
| TC-30-002 | Have buyer independently install and run unfamiliar inputs | Seller / buyer operator / counsel | backlog |
| TC-30-003 | Have buyer restore update and rotate all secrets | Seller / buyer operator / counsel | backlog |
| TC-30-004 | Close exact rights repository domain and artifact transfers | Seller / buyer operator / counsel | backlog |
| TC-30-005 | Agree objective acceptance and capped handover support | Seller / buyer operator / counsel | backlog |
| TC-30-006 | Record final acceptance and remove seller access | Seller / buyer operator / counsel | backlog |
