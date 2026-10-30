# Expanded-suite feature and contract research

Baseline: `/workspace/scratch/fd2d342d4263/audit-source`, SHA `c20f949161ac12a619b396d30904448ffd74d532`. Read-only source inspection; no application scripts/tests executed, no services contacted. Paths below are relative to this immutable checkout. “Code-present” means implementation text exists, not that its runtime behavior passed qualification. This is full existing-suite completion scope; none of the items below is proposed for removal.

## 1. Cross-suite facts and completion contracts

- Expanded APIs are registered unconditionally in `apps/api/app/main.py:368-428`, including billing, credits, source registry, credentials, analytics, every connector, remediation, contracts/promises, buyer portal and proof graph. Their absence from navigation is not an exclusion boundary.
- Current navigation has core, Coverage/Trust Center/Proof chain, members/notifications/Slack/Gmail/activity/AI Insights/settings only (`apps/web/components/layout/Sidebar.tsx:108-140`). A repository search of application TypeScript/TSX found no callers for CRM, cloud connectors, connector wizard, buyer portal, shareable spaces, deals, contracts/promises, proof widgets, executive dashboard, benchmarks, case studies, ROI, auto-publish, FAQ or credits APIs; billing has callers in checkout/settings. Full-suite work must explicitly build the user journeys for those API-only families and their role/error/loading/empty/disabled states. This absence observation is a static search result, not a claim about uninspected deployed UI.
- Define common typed envelope, paginated lists, ISO-8601 UTC timestamps, bounded bodies/lists, enums, tenant ownership, nested-ID ownership, current role, optimistic revision, stable external ID, source revision, `unknown` versus failing versus unavailable, job progress, partial failures, retry and idempotency contracts before implementing providers.
- Many features store foreign references in JSON/text (`apps/api/app/models/shareable_space.py:21-23`, `apps/api/app/models/deal.py:23-26`, `apps/api/app/models/trust_promise.py:41-48`), bypassing ordinary FK enforcement. Require validate-on-write AND validate-on-read against tenant, active object/version and current sharing eligibility; migrations must reconcile invalid references and preserve audit tombstones.
- Domain freshness/state vocabulary is inconsistent: workspace-control statuses are `not_implemented/in_progress/implemented/verified` (`apps/api/app/models/workspace_control.py:9`); control engine emits `passing/stale/not_assessed/failing` (`apps/api/app/services/control_engine_service.py:47-58`); auto-publish accepts `implemented/passed/verified` (`apps/api/app/services/trust_center_publish_service.py:22`). Define lifecycle state separately from measured evaluation result and publication approval.

## 2. Exact integration provider/action inventory

### Shared connection, credentials and ingestion

Catalog/setup/status APIs: `/api/connector-wizard/catalog`, `/catalog/{connector_type}`, POST `/start`, `/validate`, `/disable` (`apps/api/app/api/routes/connector_wizard.py:18-50`); registry `/api/sources` list/detail/update/seed/health (`apps/api/app/api/routes/source_registry.py:20-65`); credentials list/store/delete/rotation-due/expiring (`apps/api/app/api/routes/credentials.py:24-69`); connector health (`apps/api/app/services/connector_health_service.py:10-98`); ingestion single/batch/stats (`apps/api/app/api/routes/ingestion.py:26-51`).

Concrete gaps:

- Wizard validation does no provider request or credential lookup; it sets `status="available"`, `enabled=True` (`apps/api/app/services/connector_wizard_service.py:185-201`). Complete real validation of identity, resource scope, least required scopes and representative API operation; failed/partial validation cannot mark connected.
- Wizard catalog includes AWS, GitHub, Google Workspace, Okta, Azure, GitLab, Slack, Gmail (`apps/api/app/services/connector_wizard_service.py:15-125`), missing GCP, Jira, HRIS and CRM entries although other code claims them. Catalog/registry/actions must derive from one versioned capability registry.
- Registry advertises sources and object types beyond collector implementations (`apps/api/app/services/source_registry_service.py:13-102`). It includes Jira but not HRIS/CRM. Authentication identifiers also differ between catalog and registry (`iam_role` vs `iam_role_assumption`, GitHub App vs `oauth2_app`). Define one source/connection schema, multiple connection support, provider account/resource identity, scopes, credential reference, region, cadence, cursor, last success/error and capability versions.
- Source model has no unique workspace/source constraint in its definition (`apps/api/app/models/source_registry.py:13-28`); credentials similarly lack workspace/source/type uniqueness (`apps/api/app/models/credential_store.py:13-24`). Add race-safe connection identity and explicit cardinality.
- Raw ingestion updates the first registry row matching source type without a workspace filter (`apps/api/app/services/ingestion_pipeline_service.py:36-41`); it creates an evidence row per call, with no stable external-object/version identity (`:17-34`). Fix tenant-scoped health and idempotent ingest/upsert/content persistence, input ownership, retry checkpoints and failure accounting.
- “Daily monitoring scheduler” is a synchronous function that evaluates controls and reads registry health (`apps/api/app/services/monitoring_scheduler_service.py:14-52`). Static call-site search finds its caller at POST `/monitoring/run` only (`apps/api/app/api/routes/monitoring.py:13-18`); connector sync call sites are routes, not a durable scheduler. Complete cadence-aware jobs, one active lease per connection, restart/retry, cursors and distributed rate-limit handling.

### AWS

Actions: POST `/connectors/aws/authenticate`, GET `/iam`, `/s3`, `/logging`, POST `/sync` (`apps/api/app/api/routes/aws_connector.py:21-59`). Authentication accepts access key/secret/region/role ARN (`:14-19`). Wizard promises IAM-role setup and permissions for IAM users/policies/account authorization details, S3 list/policy/encryption, CloudTrail trail configuration/status (`apps/api/app/services/connector_wizard_service.py:16-31`). Registry additionally advertises IAM roles and Security Hub findings (`apps/api/app/services/source_registry_service.py:39-44`).

Actual boundary: nonempty key/secret returns authenticated true without AWS verification or assume-role (`apps/api/app/services/aws_collector_service.py:17-32`). All posture functions return static `check_required` rows: IAM MFA, password policy, root access key (`:35-48`); S3 public access/encryption/versioning (`:51-62`); CloudTrail enabled/multi-region (`:65-75`). Sync just concatenates those arrays (`:78-93`), stores nothing, and takes no credential reference.

Acceptance: STS identity and cross-account role/external-ID flow; account/region identity; paginated IAM users/roles/policies, root credential/MFA signals; per-bucket policy/public-access/encryption/versioning; trail existence/status/region coverage; Security Hub findings; access denied/unsupported feature/disabled service produce unknown or actionable partial failures. Each observation must persist raw redacted provenance and normalized signal value, observed time, resource ID and collector version; re-sync must update stable evidence and registry health. Test revoked credentials, region failure, paginator interruption, resource deletion and account mismatch in buyer-owned AWS sandbox.

### GitHub

Actions GET `/connectors/github/repos`, `/access`, `/protection`; POST `/sync` (`apps/api/app/api/routes/github_connector.py:13-30`). Registry adds teams/security alerts/Dependabot (`apps/api/app/services/source_registry_service.py:47-52`). Wizard says GitHub App installation and selected repositories/org (`apps/api/app/services/connector_wizard_service.py:33-47`).

Actual boundary: static signals for repo count/private ratio/archived count (`apps/api/app/services/github_collector_service.py:13-24`), 2FA/outside collaborators/SSO (`:27-38`), protection/reviews/vulnerability alerts/secret scanning (`:41-53`); sync combines arrays (`:56-69`). No installation token or HTTP request.

Acceptance: app registration/install callback, installation-token renewal, selected org/repos, permissions and private-resource access; paginated repos/teams/collaborators/protection/review rules/security and Dependabot alerts; feature unavailable vs no findings; app uninstall/repository removal invalidate access. Persist snapshots and resource IDs; avoid treating GitHub login OAuth as collector authorization. Buyer sandbox tests for selected-repo access, private repo, no protection, archived repo, restricted security-alert permissions and token expiry.

### Google Workspace

Actions GET `/connectors/google/users`, `/mfa`, `/admin-roles`, POST `/sync` (`apps/api/app/api/routes/google_connector.py:12-28`). Wizard promises Admin Directory, Reports and Roles read permissions (`apps/api/app/services/connector_wizard_service.py:49-63`). Registry additionally promises groups and org units (`apps/api/app/services/source_registry_service.py:79-84`).

Actual boundary: static user/suspended/SSO, MFA/password policy, role/super-admin checks (`apps/api/app/services/google_workspace_collector_service.py:12-65`). No admin consent, API call or data persistence.

Acceptance: domain/admin authorization, account scoping, consent and renewal, users/groups/org units/admin roles plus MFA/login observations, pagination and deleted/suspended-user handling. Do not infer enforcement from enrollment. Missing privileges/API disabled/domain mismatch must be visible and retryable where appropriate; observations feed evidence, signal mappings and health.

### GCP

Actions GET `/connectors/cloud/gcp?project_id=...`, POST `/connectors/cloud/sync/gcp` (`apps/api/app/api/routes/cloud_connectors.py:11-13,36-42`). Static signals IAM audit, service-account key rotation, VPC flow logs, CMEK encryption (`apps/api/app/services/cloud_connector_service.py:9-21`). Registry service-account auth promises IAM policies/audit logs/org policies/KMS/SCC (`apps/api/app/services/source_registry_service.py:55-60`). Sync route accepts no project/config body, so the collector receives no project ID (`apps/api/app/api/routes/cloud_connectors.py:36-38`).

Acceptance: setup/credential/project-org selection, real per-project and org collectors for all listed objects/signals, stable provenance and pagination, partial permissions/API disabled handling, role-scoped credential verification, resource lifecycle and background sync. Implement all advertised registry objects rather than only four stub names.

### Azure

Actions GET `/connectors/cloud/azure?tenant_id=...`, POST `/connectors/cloud/sync/azure` (`apps/api/app/api/routes/cloud_connectors.py:16-18,36-42`). Static MFA/conditional access/Security Center/Key Vault checks (`apps/api/app/services/cloud_connector_service.py:24-36`). Wizard requires service principal, Reader and Graph Directory.Read.All and promises resource config/AD users+groups/policy assignments (`apps/api/app/services/connector_wizard_service.py:77-88`); registry adds AD roles/Defender findings/resource policies (`apps/api/app/services/source_registry_service.py:63-68`).

Acceptance: tenant/subscription/cloud identity, secret/certificate renewal and least scopes; actual Graph/Azure pagination and all advertised observations; unsupported license/permission distinguished from noncompliance. Connect sync to selected tenant/subscriptions and persist evidence; no arbitrary tenant strings treated as validation.

### GitLab

Actions GET `/connectors/cloud/gitlab?group=...`, POST `/connectors/cloud/sync/gitlab` (`apps/api/app/api/routes/cloud_connectors.py:21-23,36-42`). Static protected branches/MR approvals/2FA/container scanning (`apps/api/app/services/cloud_connector_service.py:39-51`). Wizard promises instance URL/token and project/member metadata (`apps/api/app/services/connector_wizard_service.py:90-100`), registry adds security scans (`apps/api/app/services/source_registry_service.py:95-100`).

Acceptance: define cloud/self-hosted supported versions, validate instance URL with egress constraints, token scopes, group/project discovery, paginated memberships/protection/MR policies/security scans; token rotation, errors and resource deletion; no source-code collection unless explicitly covered by product contract. Implement registered scope including the unrepresented security-scan actions.

### Okta

Actions GET `/connectors/cloud/okta?domain=...`, POST `/connectors/cloud/sync/okta` (`apps/api/app/api/routes/cloud_connectors.py:26-28,36-42`). Static MFA/session/password/API-token-hygiene checks (`apps/api/app/services/cloud_connector_service.py:54-66`). Wizard promises users/groups/app assignments (`apps/api/app/services/connector_wizard_service.py:65-75`); registry promises MFA/SSO/auth policies (`apps/api/app/services/source_registry_service.py:71-76`).

Acceptance: validate tenant/domain and scoped auth; implement all listed users/groups/apps/MFA/SSO/policies/token observations with pagination; distinguish enrolled, required and currently enforced; support expiry/revocation and reconnect. IdP identity and permitted remedial MFA action must share a reviewed resource/permission contract.

### HRIS

Actions GET `/connectors/cloud/hris?provider=...`, POST `/connectors/cloud/sync/hris` (`apps/api/app/api/routes/cloud_connectors.py:31-38`); static offboarding/background check/security-training checks (`apps/api/app/services/cloud_connector_service.py:69-80`). No named vendor, auth, schema, registry/wizard entry or external calls.

Acceptance discovery requirement: specify the actual supported HRIS vendor(s), versions, scopes and legal data minimization before estimates. This is an undefined provider family in existing scope, not authorization to silently drop HRIS or claim every vendor. Implement employee identity/status/termination dates, offboarding reconciliation, background-check outcome and training completion as permitted, with restricted PII, retention and deletion. Validate against approved vendor sandbox fixtures and real sandbox API.

### Jira (registry-only provider)

Registry explicitly claims OAuth2, hourly cadence, security tickets/vulnerability tracking/incident records/risk items (`apps/api/app/services/source_registry_service.py:87-92`). Static application search found no Jira adapter/route/wizard.

Acceptance: add Jira setup/OAuth/refresh, site/project selection, issue-type/field mapping, paginated incremental issue ingestion with updates/deletions and stable identity, permission changes and error handling. Declare cloud/data-center support and read vs remediation-ticket-write actions; current declaration promises reads, not unbounded Jira administration.

### Salesforce and HubSpot

Actions POST `/crm/sync/salesforce`, `/crm/sync/hubspot`, GET `/crm/status` (`apps/api/app/api/routes/crm_connectors.py:13-28`). Both are explicitly mocks (`apps/api/app/services/crm_connector_service.py:1-4`): Salesforce upserts two fixed opportunities (`:18-65`), HubSpot one fixed deal (`:68-106`). Status counts local CRM-sourced rows (`:109-113`). Mock records contain close dates, but neither insert/update persists them. External-ID lookup omits provider namespace (`:42-45,83-86`), and DB model has no unique CRM key (`apps/api/app/models/deal.py:25-26`).

Acceptance per provider: connect OAuth/refresh/revoke, select account/pipeline, discovery/field mapping for external IDs/company/buyer contact/amount/currency/stage/expected and actual close date/owner; paginated incremental reads and deletion policy; database uniqueness `(workspace,connection,provider,external_id)`; defined manual vs CRM conflict resolution; no fixed demo data in runtime. Retry without duplicate deals, retain cursor and source revisions, reconcile counts, test expired permission and partial page failure. Add CRM administration and sync-history UI.

### Gmail

Actions status/connect/disconnect, available-label list, approved-label list/add/remove, run ingestion, evidence list, suggest controls, suggestion list/approve/dismiss (`apps/api/app/api/routes/gmail.py:44-300`). Connection accepts raw access and optional refresh token, stores encrypted values, and uses profile response without rejecting an API error (`:28-30,61-96`).

Real HTTP adapter exists (`apps/api/app/services/gmail_service.py:72-130`), but default provider is `ConsoleGmailProvider` (`:133-145`), and static application search found no call installing HTTP provider. Stub returns fake labels/messages/PDF metadata/profile (`:35-69`). HTTP adapter swallows transport errors into dicts; label/message methods convert them into empty lists (`:77-95`), fetches only one page, uses snippet as body and top-level MIME parts only (`:97-127`). Refresh token is stored but application search finds no refresh use. Ingestion creates metadata-only email/attachment EvidenceItems, neither storing body nor retrieving attachment bytes (`apps/api/app/services/gmail_ingest_service.py:64-145`).

Acceptance: full OAuth consent/callback/refresh/revoke and account binding; explicit production adapter startup; label approvals; paginated history/incremental sync; full MIME recursion/body extraction and bounded attachment download through normal parse/index pipeline; stable message+attachment revision identity/dedup; real versus empty versus error states; disconnection clears credentials/jobs and respects evidence-retention policy; control suggestions require review. Confirm catalog disclosure matches collected contents (wizard currently says metadata only at `apps/api/app/services/connector_wizard_service.py:114-124`).

### Slack

Actions status/connect/configure/disconnect/test/channels (`apps/api/app/api/routes/slack.py:32-201`); approved channel list/add/revoke/run, evidence list, control suggestions/review (`apps/api/app/api/routes/slack_ingest.py:38-235`). HTTP adapter supports `chat.postMessage`, `conversations.list` (one page) and `auth.test` (`apps/api/app/services/slack_service.py:69-108`); default is Console (`:118-127`) with no application installation call found.

Ingest calls nonexistent provider `fetch_messages`; both shown providers lack it, and `AttributeError` falls back to synthetic messages with new timestamps (`apps/api/app/services/slack_ingest_service.py:140-145,184-193`). Registry promises realtime messages/threads/files (`apps/api/app/services/source_registry_service.py:23-28`), while wizard says message metadata and no files (`apps/api/app/services/connector_wizard_service.py:102-112`).

Acceptance: production adapter selection; app OAuth/install/reinstall/revoke and workspace identity; required history/replies/files scopes; approved channel-only ingestion; paginated channels/history/thread replies and bounded files if retaining registry promise; event signature/replay verification for realtime flow; stable event id and dedup across restarts; edits/deletions/current membership; send-test notification and event notification failures/retries must reflect actual remote effect; redact tokens and retain audit. Never fabricate evidence on missing method or provider error.

### Login OAuth (separate from data connectors)

Google/Microsoft/GitHub authorize URLs and HTTP exchanges are code-present (`apps/api/app/services/oauth_service.py:13-59,62-121,133-192,196-230`). Microsoft uses common tenant endpoints and requests only `openid profile email`, then calls Graph `/me` (`:17-19,40-49,196-219`); provider-approved scope compatibility must be tested. OAuth identity default-tenant provisioning is already F03 (`apps/api/app/api/routes/auth.py:859-879`).

Acceptance each provider: bind single-use state to browser flow, validate callback/redirect, verified immutable provider subject, account-linking proof and tenant policy; first identity gets isolated onboarding or explicit invite, never default tenant editor; handle denial, timeout, absent/unverified email, duplicate/link conflict, session expiry, MFA/SSO requirements. Consumer login permission must never imply Workspace/Graph/Gmail/repo collection consent. Cover reconnect/link/unlink and revoked provider account.

## 3. Billing, credits and commercial entitlements

Code-present Stripe actions: checkout/subscription/customer portal/webhook (`apps/api/app/api/routes/billing.py:39-186`). Real SDK creates Customer/Checkout/Portal objects (`:73-100,143-147`). Hooks process checkout completed, subscription updated/deleted and invoice payment failed (`:175-182,189-279`). No event-ID ledger/order fence is present in this file; checkout completion forcibly sets active (`:205-215`), an earlier update for an unknown subscription is ignored (`:237-240`), and absent annual price falls back to monthly (`:48-50`).

Concrete backlog:

1. Scope checkout/portal to current authorized workspace and billing-owner role. `workspace_id` is arbitrary optional body input and is used without membership validation (`apps/api/app/api/routes/billing.py:34-36,59-66`); both operations depend only on `require_session` (`:42,129`). Isolate Stripe customers per workspace; current reuse looks up a subscription by user (`:68-71`). Test foreign workspace, ordinary member and removed/demoted owner.
2. Define complete subscription state machine, signed price/currency/interval catalog, trials, grace periods, cancel-at-period-end, reactivation and paid/failed/refunded/chargeback handling. Replace fixed expired trial date (`apps/api/app/api/routes/billing.py:16,82-89`) with configurable documented policy. Reject unavailable annual price instead of silently billing monthly. Reconcile server price configuration with UI pricing.
3. Durable verified webhook inbox keyed by Stripe event ID; idempotent monotonic processing, out-of-order recovery/provider reconciliation, atomic entitlement updates, retry/dead-letter and observability. Verify actual status/payment from provider; checkout redirect alone confers no entitlement.
4. Model subscription/customer ownership and plan entitlement mapping; reconcile duplicate checkout races and customer creation retries; customer portal allowed operations consistent with app policy. Test sandbox lifecycle through cancellation and transfer to buyer-owned Stripe keys/products/webhooks.
5. Credit operations balance/history/add/allocation/reset/check (`apps/api/app/api/routes/credits.py:23-106`). Any workspace admin can mint a transaction labeled purchase, change allowance and reset cycle (`:48-90`). Separate operator-authorized adjustments from tenant self-service paid purchases; paid credits require verified billing event. Audit the actor/reason.
6. Credit consumption is read/compare/decrement with no row lock/idempotency key (`apps/api/app/services/credit_service.py:66-87`); reset uses 30 days and overwrites balance (`:107-133`). Specify reservation/commit/refund per job, concurrent balance safety, retry safety, cycle timezone/renewal, purchased balance rollover, rejected/failed/cancelled generation treatment. Reconcile ledger with provider invoices and usage; negative or duplicate charges fail tests.
7. Complete billing/usage/credit UI: prices/selected interval, checkout cancellation, pending provider confirmation, billing portal, balance/transactions, limits/top-up request, renewal/cancellation and permission states. Checkout/settings callers exist (`apps/web/app/checkout/page.tsx:158`, `dashboard/settings/page.tsx:18-34`), but no credits caller found in application TS/TSX search.

## 4. Trust Center, public sharing and buyer experience

### Articles and policy acknowledgments

Existing article list/detail/create/update/delete and acknowledge actions (`apps/api/app/api/routes/trust_articles.py:50-200`) are code-present; public list requires published-only plus workspace ID, public detail checks publication (`:59-75,103-113`). Define draft/publish/withdraw, slug uniqueness, revisions, author/reviewer, safe Markdown/links, workspace branding and authenticated visitor behavior across tenants. Policy acknowledgment must reference exact policy revision and re-acknowledgment policy on edits. Acceptance covers all anonymous/authenticated/other-workspace combinations, unpublish invalidation, caching and public URL consistency.

Auto-publish selects workspace controls in implemented/passed/verified, generates generic “evaluated” articles and skips already-published rows (`apps/api/app/services/trust_center_publish_service.py:15-67`). Complete evidence-backed publication approvals, mapping to control revisions, drift/expiry withdrawal/review; avoid overwriting hand-authored content and stale public claims. Idempotence must preserve approved text while reacting safely to control regression.

### NDA access

Request/list/approve/reject/revoke/validate routes (`apps/api/app/api/routes/nda_access.py:22-93`). Service stores NDA accepted bool/timestamp, issues 30-day bearer token, and checks status/expiry (`apps/api/app/services/nda_access_service.py:16-41,44-60,84-103`). Approval/reject/revoke query by request ID alone (`:51,65,75`)—F01 includes reproduced cross-tenant approval. No signed NDA version/content hash or requester identity verification shown.

Acceptance: tenant-bound transitions and single actor audit; exact NDA terms/version and agreement proof; verified requester/email; request dedup and anti-abuse; explicit authorized document/article/answer scope, expiring/revocable hashed tokens, token rotation and access logs. Validate permission at every file fetch; approving a request must deliver an actual authenticated/gated download journey, with no direct-object bypass. Test revoked/expired/foreign grant and replaced/deleted artifact.

### Shareable spaces

Create/list/deactivate/token access (`apps/api/app/api/routes/shareable_spaces.py:26-65`). IDs are blindly JSON stored (`apps/api/app/services/shareable_space_service.py:15-45`); access checks active/expiry then returns metadata and IDs (`:69-85`), not a resolved content/download manifest. Deactivate/get by ID lack workspace filter (`:55-66`). Token included in every serialized space (`:88-99`).

Acceptance: tenant-owned content picker and validated references; scope/version/publication/NDA rules; complete buyer page with articles/approved answers/gated docs; optional buyer identity binding; expiry, revoke, rotate, edit scope and audit; no token leakage in logs/referrers; each artifact re-authorized at download. Browser tests must exercise shared content rather than simply checking token-valid JSON.

### Buyer portal

Internal actions: create/list portals, capture/list snapshots, list/update escalations, list subscriptions (`apps/api/app/api/routes/buyer_portal.py:21-116`). Public actions under `/public/buyer-portal/{token}`: manifest, instant-match, changes, escalation, satisfaction, subscribe (`:134-238`). Model/service has active bearer-token lookup, no expiry in lookup (`apps/api/app/services/buyer_portal_service.py:61-66`). Manifest advertises instant match, browse, gated NDA docs, changes, escalation, satisfaction and subscriptions true (`:69-85`). Public router has no document/browse/approval download handler in inspected file; full-suite work must connect these capabilities.

Snapshots only count answers/evidence/control statuses (`apps/api/app/services/buyer_portal_service.py:88-100`); changes only subtract counts (`:138-164`). Matching fetches all approved GoldenAnswers, uses lexical overlap/substring and returns best answer even when `need_seller_review=True` (`:184-231`). Framework filter is returned from manifest but not passed to matcher (`:82-84`, `apps/api/app/api/routes/buyer_portal.py:150-153`).

Acceptance: seller create/configure/revoke/rotate/expire portal and buyer browse; constrained disclosure scope by artifacts/framework/deal; approved current answers only, low score/review-required never auto-disclosed as accepted; evidence freshness/citations and named match-quality holdout tests; framework filter actually enforced. Versioned snapshots/change detail and subscriptions with verified email, unsubscribe and delivered changes; escalation ownership/SLA/notifications/resolution; validated tenant-linked satisfaction inputs and bounded public payload/rate limits. Demonstrate browser-to-API-to-DB-to-delivery journey per capability.

### Public security/status/analytics

- `apps/api/app/services/security_page_service.py:24-47` hardcodes SOC 2 audit underway, GDPR compliant, planned ISO, AES-256, daily backups/7-day recovery, DPA/subprocessor availability and seller contact. Require buyer-owned configurable, reviewed, evidence-backed facts; no generated compliance/operational claim without evidence. FAQ list/create/update/delete/seed exists (`apps/api/app/api/routes/security_faq.py:28-117`); version/review/publish and authoring UI must connect.
- Status is always operational for API/DB/storage/AI/Trust Center with empty incidents (`apps/api/app/services/incident_page_service.py:33-47`). Vulnerability submission returns received/reference/24-hour acknowledgment but does not persist or send (`:54-72`); policy hardcodes seller domains/contact/SLA (`:10-30`). Complete measured component health, incident/maintenance lifecycle and history, persisted vulnerability case plus reliable notification and acknowledgment. Test dependency outage and submission retry; declared SLA must be owner-approved.
- Trust analytics claims viewed/requested/downloaded per buyer/opportunity, but only counts articles/categories/NDA request statuses (`apps/api/app/services/trust_center_analytics_service.py:1-4,18-62`). Add privacy-reviewed view/download/request events tied to grant/portal/deal and resource revision, bot/retry dedup, retention, meaningful time ranges and export; acceptance reconciles known visitor actions to counts.

## 5. Compliance controls, evidence, mappings and monitoring

Complete operations already exposed:

- Framework list/enable (`apps/api/app/api/routes/compliance_frameworks.py:19-37`). Control stats/list/create/detail/update/verify, suggest/accept evidence and link CRUD (`apps/api/app/api/routes/compliance_controls.py:126-683`). Evidence create/detail/metadata get/update (`apps/api/app/api/routes/compliance_evidence.py:27-115`). Control mapping list/confirm/override/suggest (`apps/api/app/api/routes/compliance_mappings.py:47-193`). Gaps/list/scan-notify (`apps/api/app/api/routes/compliance_gaps.py:199-222`), coverage and active alerts (`apps/api/app/api/routes/compliance_coverage.py:12`, `apps/api/app/api/routes/compliance_alerts.py:16`), CSV exports controls/gaps/evidence summary (`apps/api/app/api/routes/compliance_export.py:69-154`), audit/list/export/actors/settings (`apps/api/app/api/routes/compliance_audit.py:54-178`).
- Engine evaluate one/all/timeline/drift (`apps/api/app/api/routes/control_engine.py:13-46`); signal map/coverage/evaluate (`apps/api/app/api/routes/signal_mapping.py:20-33`); monitoring run (`apps/api/app/api/routes/monitoring.py:13`); alerts acknowledge/list (`apps/api/app/api/routes/alert_management.py:22-39`); drift/connector/stale/all/email digest (`apps/api/app/api/routes/alerting_engine.py:13-33`); evidence cards/list/detail (`apps/api/app/api/routes/evidence_cards.py:13-21`), timeline (`apps/api/app/api/routes/control_timeline.py:13`), snapshot/evidence diff (`apps/api/app/api/routes/evidence_diff.py:13-24`), freshness create/list/effective/evaluate/delete (`apps/api/app/api/routes/freshness_policies.py:20-42`), evidence approve/reject/reset/pending/approved/bulk (`apps/api/app/api/routes/evidence_approval.py:22-59`).
- AI mapping CRUD+approve for framework-controls, control-evidence, evidence-tags and question-preferences; suggestions for first three (`apps/api/app/api/routes/ai_mappings.py:83-418`). Keep human acceptance and precedence distinct from model suggestions.

Concrete completion requirements:

1. Establish canonical framework IDs/version/content provenance/licensing, framework enable/disable/version migration and complete production catalog imports. Classifier recognizes SOC2/HIPAA/ISO27001/NIST CSF2/NIST 800-53r5/NIST800-171r3/SIG/CAIQ (`apps/api/app/services/framework_metadata.py:46-55`); dev catalog only has representative SOC2/HIPAA/NIST/HITRUST/ISO themes, explicitly not production attestation, with HITRUST/ISO synthetic DEV keys (`apps/api/scripts/dev_compliance_catalog.py:1-9`). Tag vocabulary adds HITRUST. Do not confuse classification support or synthetic seeds with a complete usable compliance library. Resolve canonical names and NIST subtype keys in mappings and UI.
2. Shared control/evidence lifecycle, tenant-bound owner/member assignment, transactional verified links, evidence file/blob/content provenance and approval history; distinguish evidence presence, relevance, approval, freshness and actual test outcome. Model `ControlEvidenceLink` has no workspace or unique pair constraint (`apps/api/app/models/control_evidence_link.py:13-19`), so enforce both parents and unique pair.
3. Current engine passes with one evidence link created within 180 days, ignoring approval/verified link/content/expiration, and confidence is `50+15*fresh_count` (`apps/api/app/services/control_engine_service.py:31-58`). Implement versioned control-specific predicates using observed signals and approved evidence requirements; unknown/error not pass; freshness policy from central rules; deterministic explainable evaluation and retained input revision. `failing` branch is unreachable for normal nonnegative link counts with threshold 1: no evidence=>not_assessed, fresh=>passing, otherwise any evidence=>stale.
4. Signal map contains limited mostly NIST-style keys (`apps/api/app/services/signal_mapping_service.py:11-38`) and claims update while only returning affected rows (`:57-92`). Add reviewed framework/version-specific mappings for every provider observation; persist observations and evaluation, not indiscriminate “true signal => verified control.” Evidence-to-control suggestions require explicit adjudication and rollback with audit.
5. Tie durable schedule to provider collection→ingestion→approval/classification→evaluation→drift→alert→remediation. Current monitoring reads local rows only. Use snapshots with input/rule version, repeatable as-of result, meaningful drift cause and unique alert key; duplicate schedule/retry cannot duplicate notifications/tickets. Test failure/recovery/stale/late observation/clock boundary and retracted evidence.
6. Complete UI for control library/framework enablement, owners/status/verification with explanations, evidence review, cross-framework mappings/overrides, cards/timeline/diff, freshness policy and monitoring/alert operations. Coverage page alone does not exercise those API-only capabilities. Export must use the same definitions, preserve tenant/time filters and escape spreadsheet formulas; audit export must show actor/revision and changes.
7. Domain acceptance dataset: each enabled framework has passing/failing/unknown/expired/revoked/partially supported cases; independent reviewer validates expected coverage and mappings. No certification or regulatory conformity inferred from green controls.

## 6. Remediation and safe external actions

API operations: playbook create/list/builtins/seed; ticket create/list/status; auto-create/stats; post-remediation evidence/impact; automation list/enable/run; audit (`apps/api/app/api/routes/remediation.py:54-174`). Three catalog actions: `mfa_re_enable` (IdP enforce MFA), `policy_review_stamp` (internal review metadata), `public_repo_private` (GitHub repository visibility) (`apps/api/app/services/remediation_loop_service.py:18-34`). Live branch only logs and returns completed with “Mock execution” (`:163-200`).

Requirements:

- Ticket lifecycle with valid owned control/deal/evidence/owner/playbook refs, severity/deadline, state guards, assignments/comments, idempotent drift-triggered creation, dedup, notification and full UI.
- Post-remediation evidence currently directly sets control status/verified_at and adds verified links without independently evaluating evidence (`apps/api/app/services/remediation_loop_service.py:58-90`). Require evidence capture, validation and reviewer approval before passing; scoped lookup at every node. Impact currently samples arbitrary low-confidence draft/flagged answers across workspace rather than proven dependency paths (`:97-126`); derive impact from validated proof graph and label uncertainty.
- Define exact provider/resource/payload per action and implement real adapter only after reviewed dry run. MFA action must name supported IdP(s) and administrative scopes; repo privacy action must target explicit org/repo. Operation-specific confirmation/approval, permission checks, idempotency, before/after snapshots, rollback/recovery, concurrency and interruption handling; verify remote postcondition before completed. Failed partial action creates actionable audit/alert and never a green control. Policy review stamp must not represent substantive review without authorized human attestation.

## 7. Deals, promises, contracts and business outcomes

### Deals and deal rooms

Deals expose CRUD, questionnaire link, analytics/revenue-unblocked/risk ranking/deadlines/overdue/this-week risk, per-deal risk/room (`apps/api/app/api/routes/deals.py:42-129`). Single object calls pass ID without tenant to services (`:85-130`); services query IDs alone (`apps/api/app/services/deal_service.py:25-27,37-74`). Questionnaire link validates neither questionnaire existence nor tenant (`:65-74`). Risk traverses arbitrary linked questionnaire IDs (`apps/api/app/services/revenue_risk_service.py:26-42`). Treat as code-supported authorization gap requiring negative tests, not a runtime reproduction in this review.

Contract issues: create accepts `close_date: str` (`apps/api/app/api/routes/deals.py:24`) passed directly into DateTime model (`apps/api/app/models/deal.py:22`, `apps/api/app/services/deal_service.py:14-21`); stage is unconstrained str despite defined stages (`apps/api/app/models/deal.py:9`), amount float lacks currency (`:20`); update schema omits close date/frameworks/owner though service can update some (`apps/api/app/api/routes/deals.py:29-35`, `apps/api/app/services/deal_service.py:41-51`).

Acceptance: typed dates/stages/nonnegative decimal currency amounts, expected versus actual close dates and ownership; deal/questionnaire linking/unlinking with tenant checks and source provenance; CRM conflict/version policy; room assembled only from authorized current documents/approved answers/required frameworks and scope; shared buyer path integrated with NDA/portal; deadline timezone/reopened/closed behavior; product UI and observable save/errors. Delete/archive must handle linked promises/rooms/subscriptions without leaks.

Risk calls rejected evidence “stale,” counts it across whole workspace, tests answer confidence against 50, and treats no-questionnaire deal risk as zero (`apps/api/app/services/revenue_risk_service.py:39-51`). Define normalized confidence scale and true linked stale/expired/unsupported exposure, unknown assessment for unassessed deals, transparent factor weights, and closed-deal policy. Test fixture with identical deal/questionnaire but irrelevant workspace evidence must not change risk.

### Contracts and promises

Contract ingest/list only (`apps/api/app/api/routes/contracts.py:14-33`). It accepts title/body text/original filename, writes clause JSON and automatically active promises with arbitrary +365 expiry/+180 review (`apps/api/app/services/contract_service.py:14-57`). Keyword mock fabricates “90 days” and “72 hours” clauses regardless of actual source values (`:74-86`); contract model has no original body/blob/source locator (`apps/api/app/models/trust_promise.py:21-31`).

Acceptance: actual supported document upload/storage/parser; exact source span/page/text and source hash, structured obligation/topic/party/timing/exception extraction; draft review and correction before activation; contract revision/supersession and source deletion semantics; source dates instead of fixed invented expiry. Holdout tests must include conflicting amounts, negation, alternatives, absent clauses and amendments. No legal interpretation/compliance assertion from fabricated clauses.

Promise API create/list/dashboard/contradictions/expiring/get/coverage/map-controls (`apps/api/app/api/routes/promises.py:14-88`). Model advertises source types questionnaire_answer/trust_article/contract_clause/sla/security_addendum/verbal/sales_commitment and statuses active/expired/contradicted/fulfilled/superseded (`apps/api/app/models/trust_promise.py:9-18`). API creation omits expires/review/status while service supports them; `update_promise` exists with no exposed update route (`apps/api/app/services/promise_service.py:187-200`, `apps/api/app/api/routes/promises.py:14-88`). Single get/map/coverage query ID alone (`apps/api/app/services/promise_service.py:44-79`). Coverage checks only control status; contradiction detection compares first numeric day/month/year per topic using regex (`:93-126`).

Acceptance: complete edit/review/assign/expire/supersede/resolve lifecycle and API/UI fields; validate all referenced source/deal/control/evidence/owner tenants; revisioned source links for every declared source type; backing based on approved current evidence and rule state; contradiction candidates with exact source quotations, temporal/customer scope and human adjudication. Expiry/review reminders and scheduled state transitions, provenance and audit; distinguish guessed topic/heuristic conflict from verified contradiction.

### Analytics, ROI, case studies, executive dashboard

Code-present aggregate functions must be connected and checked against event definitions; no fabricated business proof:

- Deal analytics uses local stage/value sums and expected close date minus local created date; “revenue unblocked” simply sums every won deal (`apps/api/app/services/deal_analytics_service.py:17-67`). Record actual lifecycle events and attribution assumptions; separate influenced revenue from claimed causal revenue. Multi-currency and missing dates must not silently contaminate totals.
- Benchmark coverage counts Answer rows / Questions and includes every answer revision; average turnaround is generation/export job execution only (`apps/api/app/services/benchmark_service.py:31-103`). Use selected current answer state, distinct questions, valid denominator/date window and true questionnaire cycle definition. Tests prevent >100% coverage from revisions and exclude failed jobs where required.
- Proof widgets estimate saved time as answers ×0.08 hours, count all documents as indexed and all export records as delivered (`apps/api/app/services/proof_widgets_service.py:14-54`). Derive indexed/delivered from actual completed states; show measured vs assumed estimates and method. Distinguish created, downloaded and sent.
- ROI hardcodes TrustCopilot 0.5 hour/questionnaire; question-count input unused beyond echo (`apps/api/app/services/roi_calculator_service.py:4-46`). Expose assumption/input, validate zero/negative inputs and compute sensitivity without claiming measurement. Align price with billing catalog.
- Case-study template/CRUD exists (`apps/api/app/api/routes/case_studies.py:41-93`); implement authoring/preview/publication workflow, consent/provenance for organization quotes/results and clear synthetic demo labels. No buyer-generated outcome is factual merely because stored.
- Executive dashboard/reuse analytics endpoints exist (`apps/api/app/api/routes/executive_dashboard.py:13-14`, `apps/api/app/api/routes/reuse_analytics.py:13-14`); full suite requires UI, date/filter contract, metric definitions, export and reconciliation to audited source events. Do not mark complete from static aggregate endpoint alone.

## 8. Proof graph, integrity and reuse provenance

API sync/nodes/edges/answer chain/node freshness/hash record+verify/diffs/reuse record+list (`apps/api/app/api/routes/proof_graph.py:16-191`). Graph service rebuilds by deleting all workspace edges/nodes (`apps/api/app/services/proof_graph_service.py:33-40`), then writes generated graph; sync-with-diff snapshots before/after (`:485-496`). Artifact hash API hashes caller-supplied content against latest recorded hash (`:326-377`), rather than automatically verifying persisted authoritative file bytes. This is useful integrity functionality but not independently authenticated proof of truth.

Acceptance:

- Stable semantic node/edge identity and source revision/version; tenant-bound references, no dangling graph after deletion/replacement, dedup and bounded traversal; rebuild atomicity under failure/concurrent edits; identical semantic graph must produce no spurious diff due to regenerated database IDs/timestamps.
- Event-driven graph updates or explicit freshness/version warning; answer→source/control→evidence edges reflect actual citations and approved revisions, not mere label similarity. Verify revoked/stale/deleted evidence handling and propagate affected downstream reviews without overwriting approved human text.
- Hash actual stored artifact bytes plus immutable version/size/content type; verify download/export payload; access control for recording and verify; tamper tests; define content-fingerprint vs byte-hash and disclose no signature/time-stamp assurance unless implemented.
- Reuse provenance records source answer/version, target answer/version, evidence set, reason/model or human actor/time, later corrections and withdrawal; attach only valid tenant-owned references. UI chain must show exact source support/freshness and missing/unknown states. Concurrent sync/record and cross-tenant ID tests required.

## 9. Mandatory full-suite acceptance dependencies

Each provider action above needs separate owned backlog line, sandbox qualification and buyer-owned configuration; do not collapse all providers into a single “integrations verified” task. Per provider: connection+validation, credential lifecycle, actual data action, normalized/persisted observation, sync/retry/cursor, downstream use, UI, security negatives, operational runbook and transfer smoke. Shared work may be one reusable platform package, but provider behavior remains independently accepted.

Every domain requires contract-level tests with current production schemas, a fresh PostgreSQL stack, UI→API→DB effects, restart persistence, current membership/role and cross-tenant negatives, documented empty/error/partial flows, and exported/delivered artifact verification. Static/mock unit tests remain useful but must be labeled and cannot close real-provider gates. Qualification should include one integrated scenario joining actual provider observation→evidence approval→control evaluation→drift→remediation→fresh evidence→approved answer/proof chain→deal room/NDA buyer access→audited analytics and billing/credit accounting, while preserving the independently accepted behavior of each module.
