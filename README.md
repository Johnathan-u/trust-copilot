# Trust Copilot

AI-assisted questionnaire and evidence platform for security and compliance. Upload customer questionnaires (SOC2, ISO, vendor due diligence), parse them, retrieve relevant evidence from uploaded documents, generate AI draft answers with citations, and export completed responses back into XLSX.

## Quick start

**Easiest:** `.\scripts\start.ps1` (Windows) — starts services, runs migrations, seeds demo.

Or manually:

1. **Start services**
   ```bash
   docker compose up -d
   ```

2. **Run migrations** (see [docs/ops/DATABASE_MIGRATIONS.md](docs/ops/DATABASE_MIGRATIONS.md))
   ```bash
   docker compose exec api alembic upgrade head
   ```
   Or locally: `.\scripts\run-migrations.ps1`

3. **Set env** – Copy `.env.example` to `.env`, set `OPENAI_API_KEY` for AI generation and embeddings.

4. **Open** http://localhost:3000 (Caddy serves app and API on port 3000).

## Auth & access

- **Demo login:** `demo@trust.local` / `j` (after seed). See [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).
- **Registration:** `/register` — create account; verification link is sent (email stub in dev). Verify at `/verify-email?token=...`.
- **Password reset:** `/forgot-password` → email link → `/reset-password?token=...`. No auto-sign-in after reset.
- **Workspace switching:** In the dashboard, use the workspace dropdown in the header (when user has multiple workspaces).
- **Roles:** Admin, editor, reviewer, with RBAC on uploads, exports, and Trust Center admin. See [Auth & SSO](docs/security/AUTH_AND_SSO.md).
- **Production:** Set `SESSION_SECRET`, `FRONTEND_URL`; use a real email provider for verification and reset. CSRF uses Origin/Referer; rate limiting on login.

## Workflow

1. **Documents** — Upload evidence (PDF, DOCX, XLSX). Files are parsed, chunked, and embedded for retrieval.
2. **Questionnaires** — Upload questionnaires (XLSX). Questions are parsed and linked to source cells.
3. **Review** — Open a questionnaire, click **Generate answers** (requires `OPENAI_API_KEY`). Edit answers inline, set status, use filters and bulk actions.
4. **Export** — Click **Export XLSX** to produce an XLSX with answers placed in the original layout. Download from Recent exports.

## Architecture

```
┌─────────────┐     ┌──────────┐     ┌─────────────────────────────────────┐
│   Browser   │────▶│  Caddy   │────▶│  Web (Next.js)  │  API (FastAPI)    │
│             │     │  :3000   │     │  :3000          │  :8000            │
└─────────────┘     └──────────┘     └─────────────────────────────────────┘
                           │                    │
                           ▼                    ▼
                    ┌──────────┐          ┌──────────┐
                    │ Postgres │          │  MinIO   │
                    │ pgvector │          │  S3      │
                    └──────────┘          └──────────┘
                           ▲
                           │
                    ┌──────────┐
                    │  Worker  │
                    │ (async)  │
                    └──────────┘
```

- **Caddy** — Reverse proxy; `/api/*` → API, else → Next.js.
- **API** — FastAPI; auth, documents, questionnaires, answers, jobs, exports, search, trust articles.
- **Worker** — Polls jobs; runs `parse_questionnaire`, `index_document`, `generate_answers`, `export`.
- **Postgres** — With pgvector for embeddings.

## Project structure

| Path | Purpose |
|------|---------|
| `apps/api` | FastAPI backend |
| `apps/web` | Next.js frontend |
| `infra/caddy` | Caddy config |
| `scripts/` | Migrations, setup |
| `docs/` | Architecture, client, ops, security, engineering, legal |

## Environment

See `.env.example`. Required: `DATABASE_URL`, `SESSION_SECRET`, `S3_*`. Optional: `OPENAI_API_KEY` (needed for embeddings and answer generation).

## Commands

| Command | Purpose |
|---------|---------|
| `docker compose up -d` | Start all services |
| `docker compose exec api alembic upgrade head` | Run migrations |
| `cd apps/web && npm run dev` | Run web dev server |
| `cd apps/api && uvicorn app.main:app` | Run API |
| `cd apps/api && pytest tests/ -v -m "not integration"` | Run tests (no failures; DB-dependent tests skip without Postgres). See [docs/TESTING.md](docs/TESTING.md) for full suite. |
| `npm run test:e2e` | Run registry lifecycle E2E tests. Starts Postgres, MinIO, migrations, seeds, API, and Web; runs Playwright. Requires Docker and Python. |

## Trust Center

- **Admin** — `/dashboard/trust-center` — Manage trust articles.
- **Public** — `/trust` — Browse published articles (no auth).

## Docs

- **Architecture:** [CODEBASE_MAP](docs/architecture/CODEBASE_MAP.md), [ARCHITECTURE](docs/architecture/ARCHITECTURE.md)
- **Ops:** [Deploy](docs/ops/DEPLOY.md), [Env reference](docs/ops/ENV_REFERENCE.md), [Migrations](docs/ops/DATABASE_MIGRATIONS.md), [Observability](docs/ops/OBSERVABILITY.md), [Backup/restore](docs/ops/BACKUP_RESTORE.md), [Incident response](docs/ops/INCIDENT_RESPONSE.md), [Status page](docs/ops/STATUS_PAGE.md), [Hosted demo](docs/ops/HOSTED_DEMO.md)
- **Client:** [Admin guide](docs/client/CLIENT_ADMIN_GUIDE.md), [SSO setup](docs/client/SSO_SETUP.md), [API auth](docs/client/API_AUTH_AND_INTEGRATIONS.md), [End user guide](docs/client/END_USER_GUIDE.md), [Trial & billing](docs/client/TRIAL_AND_BILLING.md), [Onboarding](docs/client/ONBOARDING.md), [Sample questionnaire](docs/client/SAMPLE_QUESTIONNAIRE.md)
- **Security:** [Overview](docs/security/SECURITY_OVERVIEW.md), [Tenancy](docs/security/TENANCY_AND_ISOLATION.md), [Audit](docs/security/AUDIT_LOGGING.md), [Auth & SSO](docs/security/AUTH_AND_SSO.md)
- **Engineering:** [Contributing](docs/engineering/CONTRIBUTING.md), [Testing](docs/engineering/TESTING.md), [Release process](docs/engineering/RELEASE_PROCESS.md), [Tech debt](docs/engineering/TECH_DEBT.md)
- **Marketing:** [Landing page](docs/marketing/LANDING_PAGE.md), [Positioning](docs/marketing/POSITIONING.md), [Competitors](docs/marketing/COMPETITORS.md), [Cost structure](docs/marketing/COST_STRUCTURE.md)
- **Other:** [Demo script](docs/DEMO_SCRIPT.md), [Enterprise readiness](docs/ENTERPRISE_READINESS.md), [Registry lifecycle](docs/REGISTRY_LIFECYCLE.md)
