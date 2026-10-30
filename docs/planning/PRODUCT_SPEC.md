# TrustCopilot full product objective and scope statement

Version 2 • 27 October 2026, Europe/Kiev. Repository: `https://github.com/Johnathan-u/trust-copilot`, branch `master`, commit `c20f949161ac12a619b396d30904448ffd74d532`. Connected GitHub was rechecked for this request. This specification supersedes the earlier focused-release default. **Every feature family already present or advertised in this application is in the full-suite completion backlog.** Analytics and UI polish requested in this turn are also included. No work is implemented by this document.

## Objective statement

Deliver a complete, coherent, secure and buyer-operable pre-revenue TrustCopilot product: a new authorized user can onboard, connect or upload real evidence, process a questionnaire, obtain useful grounded draft answers with verifiable source support, review and approve revisions, and export correct deliverables. All existing trust, vendor, compliance, integration, remediation, deal, billing and reporting features must work through usable interfaces. The product must install, persist, recover, update and transfer to a buyer's accounts using documented procedures. Its public website must have polished accessible presentation and verifiable consented traffic analytics, without sending private compliance content to Google Analytics.

Completion is established by evidence at one release SHA, including independent security review, real provider sandbox trials, real-model holdout results, original-cell export checks, buyer clean-room installation and restore. It is not established by seeded demonstrations, endpoint names, compile success or a signed sale agreement.

## Scope statement

In scope: all 94 current API route modules and 489 statically declared operations; all 33 existing page files; worker dispatch/schedules and their storage/database/services; the additional management and public workflow surfaces defined in tickets; every registered or advertised provider/action; synthetic framework catalogs replaced with usable legally permitted content; actual public/private analytics instrumentation; UI design system, usability, accessibility, responsive behavior, performance, copy and SEO; security/data handling; release/deployment/backup/restore; documentation, asset/IP inventory, demo, buyer acceptance and capped support.

The backlog is a complete proposed delivery scope for the inspected application, not a guarantee that static analysis found every latent defect. Runtime route enumeration, provider discovery and security qualification can create additional linked tickets. A new finding cannot be ignored because the initial backlog is large or a point budget has been exhausted. Disabling an unfinished feature does not count as delivering this full suite. Any reduced scope requires an explicit owner decision and corresponding changes to the scope, UI, APIs, documentation and listing.

Not implicitly included: mobile-native applications, new unrelated product lines, every future HRIS vendor, multi-region active-active hosting, Kubernetes migration, unlimited scale, SOC2/ISO certification, a legal compliance guarantee, autonomous destructive remediation, purchasing services, contacting buyers or migrating customer data without authorization. Scanned-image OCR is not an established supported capability; text-bearing PDF is the declared PDF input unless a separate OCR feature is approved. Unknown file features fail clearly rather than corrupting data. These boundaries are explicit product limits, not hidden omissions.

## Evidence and current-state rules

The prior audit reproduced authorization, redirect, backend-install, review, parser, workbook, approved-answer overwrite and backup/provider-error defects. The new read-only review additionally identified static provider/CRM/contract/remediation mocks, absent provider wiring, API-only feature families, false status/metric assumptions and concrete UI gaps. These new observations are **static code findings**, not newly reproduced runtime vulnerabilities. Exact path/line research is bundled in `research/`. The source repository remains unchanged.

The current files contain ordinary implementation, partial features and mocks. No customer, revenue, traffic or product-market-fit evidence is inferred from fixtures, analytics schemas, Stripe code, mock CRM deals or generated case studies. A planned analytics integration has no historical traffic until actually installed and collecting. Report the collection start date and empty state honestly.

## Target architecture and interfaces

Retain Next.js/TypeScript web, FastAPI/SQLAlchemy/Alembic API, separate database-backed worker, PostgreSQL with pgvector, private S3-compatible storage, Caddy/TLS and SMTP. Lock supported versions in toolchain tickets. One configured model/embedding provider is sufficient for the existing model integration; changing it requires evaluation. A single Linux x86-64 Docker Compose host is the initial supported deployment. Do not introduce extra infrastructure without a measured need.

These are proposed shared contracts, not types claimed to exist today. Implementer chooses exact idiomatic class layout while preserving field meaning and versioned behavior:

| Contract | Required fields and behavior |
|---|---|
| RequestPrincipal | user_id or service_principal_id; workspace_id; current membership_id; effective permissions; session_id; auth_version; deployment_operator:boolean. Construct server-side from validated credential and current DB state. Deployment authority comes from a separate active operator grant, never a workspace role. |
| ApiError | code:string; message:safe string; request_id:string; retryable:boolean; optional safe field_errors. Preserve compatibility deliberately; raw exception/provider body is never public. |
| SourceLocator | document_version_id; chunk_id; source_type; page/section or sheet/cell range; quote_hash. Immutable original hash and authorized source navigation. |
| QuestionMapping | question_id; original_file_hash; sheet; question_cell; answer_cell; mapping_version. Explicit target, no global offset. Alternate format imports preserve their own locator and output contract. |
| AnswerRevision | question_id; revision; text; citations; status; author_kind; model/prompt/corpus version; approved_by/at; stale reason. Optimistic concurrency and explicit transition audit. |
| Job | job_id; workspace_id; kind; input_version; idempotency_key; status; attempt/max_attempts; lease_owner/expires_at; heartbeat; typed error_code; safe progress. Reconcile side effects; do not promise exactly-once execution. |
| ProviderConnection | connection_id; workspace_id; provider; external_account_id; resource scopes; credential_ref; capability_version; cadence; cursor; last_success/error. Permit multiple explicit connections without source-type-only lookup. |
| ProviderObservation | connection/provider/resource ID; object revision; observed_at; collector_version; normalized value/state; raw-redacted provenance; source version. Unknown/no permission is not compliant or empty success. |
| ProductEvent | event_id; schema_version; occurred_at; workspace/actor derived by server; enum event_type/outcome; safe resource kind; bounded allowlisted metadata; environment; idempotency key. No arbitrary client assertion becomes authoritative completion. |
| TrafficEvent | allowlisted public route/title and fixed enum event/CTA/plan/campaign values after consent. No user/workspace/document identifiers, tokens, form/search text or raw URLs. |
| ReportMetric | name; value; unit; source; time window/timezone; numerator/denominator; measured/estimated flag; currency if applicable; data freshness and exclusions. |

Each ticket lists existing source locations and proposed new test/file paths. API module coverage adds actual router prefixes, handler names and declared request models from static extraction. Existing contracts must be checked in implementation against runtime OpenAPI before changing clients. Schema changes use additive migration/backfill plus fresh/upgrade/restore tests; do not rewrite the repository to match an invented architecture.

## Identity, tenancy and security target

Preserve existing admin/editor/reviewer semantics while introducing explicit owner and viewer roles through a tested migration. Owner manages ownership, deletion and secret custody; admin manages permitted workspace operations; editor edits/reviews/exports; reviewer reviews/approves without general edit/export/admin authority; viewer reads permitted approved data. Custom roles have explicit grants bounded by the creator's authority. Prevent last-owner removal. No runtime cookie claim overrides current membership or policy.

Production registration is invitation-only by default; enabling self-signup creates an isolated workspace after email verification. Implement all existing Google/GitHub/Microsoft/OIDC/ID.me paths and server-enforced SSO/MFA policy; provider sandbox unavailability is a documented blocker rather than evidence of success. Require TOTP for owner/admin and honor configurable tenant policy for others. Recovery, reset, demotion, removal, suspension and policy changes revoke inappropriate sessions immediately.

Every core and extended object is checked on list/detail/create/update/delete/bulk/search/approve/publish/download/export/job action, including indirect IDs in JSON, cache entries, public manifests and presigned URLs. Public grants have narrowly scoped assets, expiry, revocation and terms; public access never inherits a privileged internal principal. API keys are expiring scoped service identities with explicit audit attribution.

Deployment operators are named human accounts provisioned/revoked only through a host-authorized bootstrap/maintenance CLI that updates audited operator grants. The first workspace owner is not automatically a deployment operator. No ordinary signup, membership/custom-role API or API key can grant deployment authority. Global analytics/operations endpoints recheck the active grant and MFA-complete session on every request; workspace owners/admins are denied. Buyer takeover revokes seller operator grants separately from tenant memberships.

Target applicable **OWASP ASVS 5 Level 2 requirements** with a requirement-to-test matrix, independent review and explicit justified not-applicable entries. This is a testing target, not certification. Zero open confirmed critical/high application exposures at release; dependency advisories require exact version and application reachability assessment. Medium/low exceptions require owner, mitigation and known-issues entry. Include credential/history sanitation, independent key purposes and rotation, CSRF/CORS/proxy/host policy, CSP/XSS, SQL/template/command injection, file/container/egress restrictions, SSRF/DNS-rebinding, safe logs, abuse controls, secret custody, rate limits and vulnerability response.

Remediation remote actions need operation-specific authorization, dry-run preview, exact resource identity, least scopes, idempotency and verified remote postcondition. The existing IdP MFA enforcement and GitHub visibility actions must become real integrations with explicit user confirmation; a mock completion or changed local control flag is never sufficient. This planning session authorizes no external action.

## Files, provenance and review policy

Required accepted intake: TXT, DOCX, text-bearing PDF and ordinary XLSX, plus the currently accepted legacy DOC/XLS through a licensed isolated local conversion path. Preserve the original and disclose conversion; normalized DOCX/XLSX must be previewed before processing. TXT and PDF/DOCX questionnaire outputs have explicit generated-report/converted-template semantics; only supported original XLSX promises original-cell round trip. Macro/encrypted/active-content/unsupported-complexity inputs fail preflight honestly. Do not send documents to third-party conversion services.

Proposed initial configurable limits: 50 MiB raw file, 250 MiB expanded archive, 10000 ZIP entries, 500 PDF pages, 100000 workbook cells and 200 questions/questionnaire. Enforce streaming and parser budgets at proxy/API/worker; measure memory/time on the reference host and reduce the published envelope if needed. Proposed host 4 vCPU/8 GiB/100 GiB is a qualification assumption, not a guaranteed sizing recommendation.

Successful indexes are atomically promoted; active authorized document versions alone are retrieved. Archive/replacement invalidates caches and marks dependent approvals stale. Historical approved text remains reviewable after soft archive, but final export requires revalidated active support and a newly approved revision. Hard deletion immediately removes access and, within 24 hours, removes source/derived material and redacts affected answer text/citations/generated exports, even for mixed-source approved answers. Preserve only content-free tombstones; apply deletion ledger before restored backups serve traffic. Backup expiry maximum 30 days is the proposed default; owner/counsel must approve actual retention and erasure handling. No undisclosed legal-hold exception.

Review states distinguish draft/approved/rejected/flagged/insufficient-evidence and provider errors. Save means acknowledged persistence. Concurrent editing returns a conflict without losing local text. Cache hits and generation never replace approved human work. Final workbook export snapshots only approved eligible revisions; unresolved questions remain blank with a companion report. Inserted strings are literal, including leading equals/plus/minus/at-sign. Preserve supported workbook parts semantically; a real viewer must open the result without repair. No silent alternate-format fallback.

## Model quality and evaluation

Evidence is untrusted data and cannot authorize tools, alter system instructions or reveal other context. Structured model output must cite authorized supplied chunks with matching quote/version/locator. A top-k retrieval list alone is not citation support. Confidence is labelled heuristic unless calibrated; source navigation and human review are required.

Separate at least 60 development questions from a frozen 100-question holdout: 50 supported, 20 unsupported, 10 contradictory, 10 prompt-injection and 10 cross-tenant canary cases. Run 3 independent generations. Each run independently requires at least 45/50 substantive relevant supported-question attempts and at least 95% fully grounded/cited answers among attempts, rounding required passes up. Zero critical disclosure, confident unsupported/fabricated compliance assertions or instruction overrides across all 300 outputs. Contradictions need explicit conflict handling or conservative abstention. A second reviewer checks all failures and 20% of passes. Tuning on failed holdout retires affected cases and requires replacements. Report exact denominators/abstentions; no pooling away a failed run or labelling mock output as real quality evidence.

Provider credentials and a finite spend ceiling are required before these later execution tests. No real call is authorized by this backlog. Record model/prompt/embedding versions, actual token/cost/latency, failure classes and budgets. Missing credentials, model HTTP 404, timeout, HTTP 429/5xx, refusal and no evidence are distinct user/job outcomes.

## UI polish and accessibility specification

Use a coherent restrained professional design that fits the existing product rather than a framework rewrite. Suggested design defaults: system sans font stack; 14 px compact labels, 16 px body; 4/8/12/16/24/32/48 px spacing tokens; neutral slate surfaces with teal primary actions and separate semantic warning/error/success tokens. Validate actual contrast; token colors are not proof of compliance. The designer may adjust aesthetic values while preserving semantic roles, readable hierarchy and the acceptance targets.

Every existing and new page needs a useful task hierarchy, consistent header/breadcrumb/actions, readable content density, responsive navigation, server-aware forms, meaningful empty states, stale/loading/error/retry/denied states, safe destructive confirmation, pending/dirty/conflict handling and honest success feedback. No Coming Soon buttons, raw worker commands in ordinary flows, manual numeric-ID lookups as the primary workflow, inaccessible hover-only content or misleading healthy/empty/saved state.

Test 360/768/1440 CSS px screenshots for every screen, plus 320 px reflow and 200% zoom. Tables may have labelled local scrolling and compact detail views; the page itself must not overflow. Shared controls include labelled inputs, correct autocomplete/password-manager support, visible focus, modal focus trap/restore/Escape, semantic live announcements, keyboard navigation, adequate targets, reduced motion, non-color status meanings and chart text/table equivalents. Target applicable WCAG 2.2 AA requirements and record exceptions; automated scans alone cannot prove conformance.

Production-build lab goals on a documented mobile profile: public-page LCP<=2.5 seconds and CLS<=0.1; actual field INP<=200 ms is assessed only once sufficient real samples exist. Bound list rendering, defer heavy charts/source previews and prevent polling/request races. Chromium/Firefox/WebKit core flows must pass; browser/version matrix is delivered. Do not fabricate field-performance scores from synthetic lab runs.

Navigation must expose all enabled user workflows. Current 33 pages plus proposed management/public surfaces are listed individually in the backlog. Related API-only functions may share an accessible page/detail drawer, but each operation has an identifiable interaction and test; a single new page filename is not proof that the whole family works.

## Analytics and buyer traffic evidence

Use **direct GA4 for allowlisted public marketing traffic**, first-party PostgreSQL events for private product workflows and separate operational telemetry. Do not install both direct GA and GTM duplicate loaders. GTM is not required. The owner creates dedicated production/staging properties; Google Ads/Signals/User-ID/session replay and automatic form/search/download measurements are off by default. The product remains usable when analytics is disabled, blocked or unavailable.

Basic consent means no Google script/network request or analytics cookie before explicit grant or after rejection. Provide equally usable accept/reject and persistent withdrawal/settings. Do not replay pre-consent events. Manually send sanitized public page views after consent, with automatic initial/history page views disabled to prevent double-counting. Use a strict route/title/event/parameter allowlist, strip raw query/fragment/referrer and never send private paths, resource IDs, names, emails, tokens, source text or arbitrary UTM values. Keep auth/reset/invite/checkout/private dashboard and bearer-token Trust/buyer/share pages outside GA4. Public Trust engagement is first-party and separately privacy-scoped.

Attribution is deliberately coarse: registered campaign enum values map to the supported GA4 campaign fields; unknown/unregistered UTM values, free-text term/content and advertising click IDs are not forwarded. Incoming referrers are reduced to an allowlisted known search/referral origin/category; unrecognized sources become other/unattributed without their hostname/path. Public responses use a no-referrer policy for outbound requests, and network tests inspect headers as well as event payloads. Preserve accurate registered source/medium/campaign counts without transmitting raw input. Confirm exact vendor field names during implementation against the referenced GA4 documentation.

GA4 runs only in the isolated public marketing layout. Entering auth, private application or tokenized sharing routes disables collection before a full-document navigation into a tracker-free layout with restrictive CSP; removing a script element alone cannot stop an already loaded tracker. Test SPA/back/forward/visibility/unload cases for zero private-page Google requests.

Public reports show actual users/sessions/views, landing pages, source/medium/campaign and explicitly defined CTA conversions, with date/timezone/collection-start/exclusion notes. GA4 coverage excludes consent-denied/ad-blocked users and may include residual bots; it is not a perfect census. Demo/test traffic must remain identifiable and excluded from represented commercial traction. Zero data is shown as zero or unavailable, never backfilled or purchased.

The protected deployment-operator traffic page reads aggregate GA4 data server-side through a read-only configured identity; ordinary workspace owners/admins and API keys cannot access whole-site traffic. Never expose credentials or unrelated properties. A link to direct GA reports remains available when API quota/access fails, with honest error state. Buyer receives dedicated property/report access or a documented new-property transition; exact GA4 access/move restrictions are verified at closing. Do not use Universal Analytics legacy instructions as proof of GA4 transferability.

Private first-party events fire after successful persisted transitions through idempotent/outbox-backed capture. Record acquisition-independent activation, completion, review/edit/approval, exports, provider sync, Trust interactions and billing outcomes with distinct cohort/unique denominators and current-revision semantics. A button click or return URL never counts as paid purchase. Full-suite reports distinguish observed revenue, estimated ROI, generated answers, real users and synthetic data. Search Console adds genuine public indexing/search-performance evidence; private/customer/token pages are noindex and absent from the sitemap.

## Operating reliability and transfer

Jobs use bounded retries, lease/heartbeat recovery, explicit terminal errors and cancellation. Persistent DB/object state survives service/host restarts. Backups cover compatible DB+objects+config+required keys and fail nonzero on any failed stage. Prove clean-host restore with proposed 24-hour RPO/4-hour RTO; publish only achieved values. Upgrade/rollback, key migration, deletion reconciliation, provider outage, full disk and monitoring drills must be executable from runbooks.

Buyer creates its own compute/database/storage/backup/SMTP/model/analytics/monitoring/OAuth/payment accounts; secrets are replaced or migrated safely. Include licenses/assignments/prior grants, domain/brand ownership proof, exact release hashes, SBOM/notices, install/user/architecture/security/privacy/operations docs, realistic cost model, demo, known issues and support terms. Do not transfer seller personal accounts, nonassignable subscriptions, unapproved customer data or unrelated repositories.

Suggested negotiation starting point only: 10 business-day objective acceptance window and up to 12 handover hours within 30 calendar days. Counsel/parties decide actual terms. No promised valuation, sale probability or 30 day closing follows from this plan. The buyer's independent install/workflow/restart/restore/key-rotation and seller-access-revocation drill is the final completion evidence.

## Definition of ready and definition of done

A ticket is ready when its exact scope, role/API/data contracts, listed dependencies, fixtures, acceptance criteria, rights and necessary sandbox access are understood. Points are provisional relative Fibonacci estimates 1/2/3/5/8, not hours/days or dates.8 points indicates high complexity; split before commitment if the implementing team's calibrated capacity makes it too large. No 13-point item remains. The HRIS provider selection spike is explicitly unresolved; it cannot count as implementing HRIS. Proprietary framework licenses, provider approvals, branding/contacts/region and spending caps are owner decisions with named gates, not guessed facts.

Each ticket has its own DoD and verification path. In addition, changed code requires meaningful regression/negative/failure evidence, reviewed migration where applicable, no new secret/PII leakage, updated user/runbook/config contract and reviewer signoff. UI tickets require visual/keyboard/accessibility evidence. Provider tickets require actual authorized sandbox evidence. Legal/docs/closing tasks require their appropriate inventory/rights/independent rehearsal/signature evidence instead of meaningless software tests.

All tickets start NOT STARTED. P0/P1/P2 indicates sequencing/risk, not optional scope. No ticket closes with mock-only evidence for a real-provider promise. The E28 release dossier is a pre-transfer candidate: its evidence covers E02-E28 technical work and E01 scope/claims/licensing decisions/SBOM, not the later dependent demo/data-room/closing tickets. E29 appends final documents/demo and E30 appends buyer/transaction evidence. Final buyer signoff requires all mandatory tickets and 30 epic exits. Root-cause discoveries add/split tickets with traceability; never weaken acceptance or silently drop a feature to make a burndown look complete.

## Authoritative technical references checked for planning

- Google GA4 page-view behavior and duplicate prevention: https://developers.google.com/analytics/devguides/collection/ga4/views
- Google SPA measurement verification: https://developers.google.com/analytics/devguides/collection/ga4/single-page-applications
- Google basic versus advanced consent: https://developers.google.com/tag-platform/security/concepts/consent-mode
- Google Analytics PII guidance: https://support.google.com/analytics/answer/6366371
- Google Analytics access management: https://support.google.com/analytics/answer/9305788
- OWASP ASVS 5: https://asvs.owasp.org/
- W3C WCAG 2.2: https://www.w3.org/TR/WCAG22/

The analytics design and numeric engineering gates above are project decisions informed by these references, not claims that vendor tooling by itself establishes privacy, security or accessibility compliance. Recheck vendor API/version details during implementation. All external references are primary sources; no legal conclusion is made here.
