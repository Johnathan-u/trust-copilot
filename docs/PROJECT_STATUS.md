# Trust Copilot — Project Status & Known Issues

**Date**: March 2026
**Verdict**: NOT production-ready. Multiple critical, medium, and low-severity issues remain.

---

## 1. What the Project Is

Trust Copilot is a compliance automation platform. Users upload evidence documents and questionnaires. An AI pipeline tags documents, maps questions to relevant evidence via LLM classification, and generates draft answers. There is an admin governance dashboard, gap analytics, and an export flow.

### Tech Stack

| Layer        | Technology                                             |
|-------------|--------------------------------------------------------|
| Frontend    | Next.js (TypeScript), Tailwind, Recharts               |
| Backend     | FastAPI (Python), SQLAlchemy, Alembic                   |
| Database    | PostgreSQL 16 with pgvector                             |
| Object Store| MinIO (S3-compatible)                                   |
| LLM         | OpenAI API (gpt-4o-mini default)                        |
| Proxy       | Caddy                                                   |
| Worker      | Background job runner (same Docker image as API)        |
| CI/CD       | GitHub Actions (lint, test, build)                      |

---

## 2. Current Architecture (AI Pipeline)

```
Evidence Upload  →  Parse & Chunk  →  LLM auto-tags (frameworks, topics, doc types)
                                          ↓
Questionnaire Upload  →  Parse questions
                                          ↓
Generate Mappings  →  LLM classifies each question (frameworks + subjects)
                   →  Match question tags to document tags
                   →  Store QuestionMappingPreference with preferred_tag_id
                                          ↓
User selects evidence docs  →  Generate Answers (RAG: embed → retrieve → LLM)
                                          ↓
Stats, Gap Analytics, AI Governance (admin-only)
```

---

## 3. Critical Issues (Must Fix Before Production)

### 3.1 No Health Checks on Core Services

**File**: `docker-compose.yml`

Only `web` has a health check. The `api`, `worker`, `postgres`, and `minio` containers have none. This means:
- `api` and `worker` start before Postgres is ready and may crash
- No orchestrator (K8s, ECS, etc.) can determine if services are healthy
- No restart policies are set — if any container crashes, it stays dead

```yaml
# api, worker, postgres, minio all missing:
healthcheck:
  test: [...]
  interval: ...
restart: unless-stopped
```

### 3.2 Hardcoded Dev Credentials Ship as Defaults

**File**: `apps/api/app/core/config.py`

If the production deployment forgets to set environment variables, the app runs with:

| Variable         | Default Value                  | Risk                              |
|-----------------|--------------------------------|-----------------------------------|
| `SESSION_SECRET` | `"change_me_dev_secret"`       | All sessions can be forged        |
| `DATABASE_URL`   | `postgres:postgres@localhost`  | Default credentials               |
| `S3_ACCESS_KEY`  | `"minio"`                      | Default credentials               |
| `S3_SECRET_KEY`  | `"minio123"`                   | Default credentials               |

There is no startup check that forces production to set these. The app boots silently with insecure defaults.

### 3.3 ~~Massive Dead Code: `compliance_hooks.py` (1,515 lines)~~ RESOLVED

The entire heuristic system (`compliance_hooks.py`, `control_catalog.py`, `mapping_llm_rerank.py`, `control_catalog.json`), 6 dead scripts, 10 dead test files, and all associated imports/config were deleted. ~4,200 lines removed.

### 3.4 N+1 Query Pattern in `get_control_evidence`

**File**: `apps/api/app/services/compliance_hooks.py`, lines 1421-1460

For each `link` in a control's evidence links, the code executes:
1. `db.query(EvidenceItem)` — one query per link
2. `db.query(Chunk)` — one query per document
3. `db.query(EvidenceVersion)` — one query per evidence item
4. `db.query(Chunk)` — one query per version

With 100 evidence links, that is 400+ database queries instead of 4 batched queries. This will cause severe latency at scale. Although this path is not in the primary pipeline after the heuristic removal, it is still called by the `/suggest-mappings` endpoint and any code that references control-linked evidence.

### 3.5 Document LLM Tagging Has No Rate-Limit Handling

**File**: `apps/api/app/services/tag_service.py`, lines 255-310

When documents are indexed, the LLM is called to classify them. The retry logic:
- Only 1 retry (2 attempts total)
- Fixed 0.3s sleep between retries (no exponential backoff)
- No detection of HTTP 429 (rate limit) vs. other errors
- On failure, the document gets zero auto-tags silently

If a user uploads 50 documents at once and hits OpenAI rate limits, most will get no tags, and the mapping pipeline will have nothing to match against. There is no retry queue or background recovery.

### 3.6 No `.env` Enforcement for Production

**File**: `.env.example`

The `.env.example` has `SESSION_SECRET=placeholder` and `S3_ACCESS_KEY=placeholder`, but there is no validation at startup that these were changed from placeholder values. A production deployment could ship with `SESSION_SECRET=placeholder` and work fine — completely insecure.

---

## 4. Medium-Severity Issues

### 4.1 ~~`console.log` in Production Frontend Code~~ RESOLVED

The `apps/web/app/dashboard/trust-requests/page.tsx` page was removed as part of product consolidation. Trust Requests are no longer exposed as a standalone dashboard page. The console.log is gone with the deleted file.

### 4.2 Incomplete Fetch Error Handling in Frontend

**File**: `apps/web/app/dashboard/ai-governance/page.tsx`

Multiple API calls in the AI Governance page have no `.catch()` handlers:
- `onDelete`, `onApprove` — failed operations are not surfaced to the user
- `onCreate`, `onSuggest` — network errors can go completely unhandled
- Framework/Controls tabs — failures silently show empty lists with no error toast

This is not isolated to one page. The pattern exists across several dashboard pages where `fetch()` calls optimistically assume success.

### 4.3 TypeScript `any` in Production Code

**File**: `apps/web/app/dashboard/ai-governance/page.tsx`, line 644

```typescript
const update = (key: string, value: any)
```

There is at least one explicit `any` type in production code. While not widespread, it indicates incomplete type safety in the AI Governance page.

### 4.4 Mapping Pipeline Still References Heuristic Timing

**File**: `apps/api/app/api/routes/questionnaires.py`, lines 744-792

The `generate_questionnaire_mappings` endpoint still includes `mapping_timing_enabled()` checks, references to `get_mapping_timing_snapshot()`, and `get_rerank_perf_snapshot()` — all of which report heuristic-era metrics (`heuristic_ms`, `rerank_ms`, `wc_lookup_ms`, `rows_fc_hits`). These values are always zero/empty since heuristics were removed, but the code runs the timing logic anyway.

### 4.5 `compliance_mappings.py` Still Uses Heuristic `question_to_controls`

**File**: `apps/api/app/api/routes/compliance_mappings.py`, line 221

The `/suggest-mappings` endpoint still calls the full heuristic `question_to_controls` pipeline. This is a separate endpoint from the main mapping generation, but it means the old system is still live and accessible via API. This creates an inconsistent user experience — "suggest mappings" uses heuristics while "generate mappings" uses LLM.

### 4.6 LLM Classification Truncates Documents at 6,000 Characters

**File**: `apps/api/app/services/tag_service.py`, line 270

```python
user_content = f"Filename: {filename}\n\nContent (first 6000 chars):\n{text[:6000]}"
```

For large documents (policies, SOC 2 reports), 6,000 characters may only cover the table of contents. Critical compliance content in later sections is never seen by the LLM tagger. There is no chunking strategy or multi-pass approach.

### 4.7 No Resource Limits in Docker Compose

**File**: `docker-compose.yml`

No CPU or memory limits on any container. In development this is fine, but the same compose file structure is used for production (`docker-compose.prod.yml`). A runaway LLM call or memory leak in the worker can consume all host resources.

### 4.8 Missing `.env` Variables Not Documented

The following config variables exist in `config.py` but are not in `.env.example`:
- `MAPPING_MODE` (default: `llm_structured`)
- `MAPPING_CLASSIFICATION_MODEL`
- `MAPPING_CLASSIFICATION_PROMPT_VERSION`
- `MAPPING_LLM_RERANK` / `MAPPING_LLM_RERANK_BULK`
- `MAPPING_RERANK_MODEL` / `MAPPING_RERANK_MIN_CONFIDENCE`
- `CONTROL_CATALOG`
- `USE_PGVECTOR_INDEX`
- `USE_ADAPTIVE_CONCURRENCY`
- `REDIS_URL`
- `RATE_LIMIT_RPM_PER_IP`
- `AUDIT_RETENTION_DAYS`
- `APP_ENV`
- `LOG_LEVEL`
- `SENTRY_DSN` / `SENTRY_ENVIRONMENT` / `SENTRY_RELEASE`
- `OAUTH_MICROSOFT_CLIENT_ID` / `OAUTH_MICROSOFT_CLIENT_SECRET`

An operator deploying this has no idea these exist without reading `config.py`.

---

## 5. Low-Severity Issues

### 5.1 CI Does Not Run E2E Tests

**File**: `.github/workflows/ci.yml`

CI runs linting (ruff), unit tests (pytest), and frontend build. There are no end-to-end tests in CI. Playwright tests exist but are not wired into the pipeline.

### 5.2 Multiple Scripts Reference Deprecated Systems

**Files**:
- `scripts/run_fisman_mapping_refresh.py`
- `scripts/benchmark_control_catalog.py`
- `scripts/validate_mapping_rerank_live.py`

These scripts use the old heuristic `question_to_controls` pipeline. They are not part of normal operation but will break or produce misleading results if run by a developer who doesn't know the heuristic was deprecated.

### 5.3 `OIDC_DEFAULT_WORKSPACE_ID` Defaults to 1

**File**: `apps/api/app/core/config.py`, line 142

When a user logs in via SSO and no workspace claim mapping is configured, they are silently placed in workspace ID 1. If workspace 1 doesn't exist or is the wrong tenant, the user either gets an error or sees another tenant's data.

### 5.4 Silent Failure During Document Indexing

**File**: `apps/api/app/services/index_service.py`, lines 126-147

Two separate try/except blocks in the indexing pipeline swallow errors silently:
1. `auto_tag_document` failure — logged at DEBUG level, indexing continues
2. Corpus version bump / retrieval cache invalidation — caught with bare `pass`

If tagging fails, the document is indexed but has no tags. Mapping will never match it. The user has no way to know.

### 5.5 Answer Generation Swallows Many Exceptions

**File**: `apps/api/app/services/answer_generation.py`

There are 10+ `except Exception` blocks in the answer generation code. While most log the error, several use bare `except Exception:` followed by `pass` or minimal handling. In production, this makes debugging extremely difficult because failures are absorbed rather than surfaced.

### 5.6 ~~Sidebar Includes Pages That May Not Be Functional~~ RESOLVED

The sidebar has been cleaned and standardized. `/dashboard/vendor-requests` was renamed to `/dashboard/requests` (with a redirect in place). `/dashboard/trust-requests` was removed entirely. All sidebar links now point to existing, functional pages grouped into Core, Compliance, and Admin sections with role-based visibility.

### 5.7 Confidence Scores Are Arbitrary Constants

**Files**:
- `apps/api/app/services/tag_service.py`: Document tagging confidence hardcoded at 0.85 (frameworks), 0.80 (topics, doc types)
- `apps/api/app/api/routes/questionnaires.py`: Mapping confidence hardcoded at 0.75 (subject match), 0.70 (framework match)
- `apps/api/app/services/answer_generation.py`: Answer confidence formula `min(95, int(75 + top_score * 20))`

None of these are calibrated. A user sees "75% confidence" and has no basis for what that means. The numbers are constants, not derived from model output or statistical analysis.

### 5.8 `mapping_mode` Config Still Accepts `"heuristic"` But It Won't Work

**File**: `apps/api/app/core/config.py`, line 124

```python
self.mapping_mode: str = _mmode if _mmode in ("llm_structured", "heuristic") else "llm_structured"
```

Setting `MAPPING_MODE=heuristic` is accepted as valid, but the mapping pipeline was rewritten to always do LLM classification + tag matching. Setting this to `"heuristic"` does not actually enable heuristic mapping — it's a dead config path that misleads operators.

---

## 6. Testing Status

### Tests That Pass
- 745 backend unit/integration tests pass (pytest)
- Frontend builds successfully (next build)

### Tests Explicitly Deselected / Skipped
- `test_automate_everything.py::TestEvaluation::test_completed_when_all_sufficient` — requires live DB data
- `test_phase_c_notifications.py::TestNotificationDelivery::test_fire_notification_creates_log_entry` — requires live DB data
- `test_phase_d_slack.py` — requires Slack API credentials
- Multiple compliance foundation tests — require live DB with seeded framework data

### Tests That Exist But Are Not in CI
- Playwright E2E tests exist in `apps/web/e2e/` but are not run in CI
- No integration tests that test the full pipeline end-to-end (upload → parse → tag → map → answer)

---

## 7. What's Missing for Production

| Category | What's Missing | Effort |
|----------|---------------|--------|
| **Security** | Startup validation that SESSION_SECRET != default | Small |
| **Security** | Production secrets management (Vault, AWS Secrets Manager) | Medium |
| **Infrastructure** | Health checks on api, worker, postgres, minio containers | Small |
| **Infrastructure** | Restart policies on all containers | Small |
| **Infrastructure** | Resource limits (CPU/memory) on all containers | Small |
| **Infrastructure** | Redis for rate limiting (currently in-memory, resets on restart) | Medium |
| **Reliability** | Exponential backoff + rate-limit detection for LLM calls | Medium |
| **Reliability** | Retry queue for failed document tagging | Medium |
| **Reliability** | Dead-letter queue for failed answer generation | Medium |
| **Code Quality** | Remove `compliance_hooks.py` heuristic system or clearly isolate it | Large |
| **Code Quality** | Remove dead scripts and config paths | Small |
| **Code Quality** | Fix N+1 queries in `get_control_evidence` | Medium |
| **Code Quality** | Remove `console.log` from frontend | Tiny |
| **Code Quality** | Add proper error toasts for all fetch calls in frontend | Medium |
| **Observability** | Wire up Sentry (DSN config exists but not configured) | Small |
| **Observability** | Structured logging in production (config exists, unclear if active) | Small |
| **Documentation** | Document all environment variables in `.env.example` | Small |
| **Testing** | E2E tests in CI | Medium |
| **Testing** | Full pipeline integration test | Large |
| **Testing** | Fix or remove deselected tests | Medium |
| **UX** | Verify Gmail, Slack, Notifications, Requests, Trust Center pages work | Large |
| **UX** | Surface document tagging failures to users | Medium |
| **UX** | Calibrate or remove confidence scores | Medium |

---

## 8. Summary

The core pipeline (upload → tag → map → answer) works end-to-end in development with LLM-based classification. The frontend builds, backend tests pass, and Docker Compose brings up all services.

But the codebase has the scars of a major architectural pivot — from heuristic control matching to LLM tag-based matching — and the old system was never fully removed. There is 1,500+ lines of dead code that is still importable, config paths that accept deprecated modes, scripts that reference the old system, and timing logic that reports zeroes.

On the infrastructure side, the app can run in Docker but has no health checks, no restart policies, no resource limits, and hardcoded dev credentials as defaults. There is no startup validation for production. Rate limit handling for LLM calls is minimal.

The app is functional for a demo. It is not production-ready.
