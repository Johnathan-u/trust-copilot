# Trust Copilot

AI-assisted questionnaire and evidence platform for security and compliance. Upload customer questionnaires (SOC2, ISO, vendor due diligence), parse them, retrieve relevant evidence from uploaded documents, generate AI draft answers with citations, and export completed responses back into XLSX.

## Quick start

**Easiest:** `.\scripts\start.ps1` (Windows) — starts services, runs migrations, seeds demo.

Or manually:

1. **Start services**
   ```bash
   docker compose up -d
   ```

2. **Run migrations**
   ```bash
   docker compose exec api alembic upgrade head
   ```
   Or locally: `.\scripts\run-migrations.ps1`

3. **Set env** – Copy `.env.example` to `.env`, set `OPENAI_API_KEY` for AI generation and embeddings.

4. **Open** http://localhost:3000 (Caddy serves app and API on port 3000).

## Auth & access

- **Demo login:** `demo@trust.local` / `j` (after seed; local development seed data only).
- **Registration:** `/register` — create account; verification link is sent (email stub in dev). Verify at `/verify-email?token=...`.
- **Password reset:** `/forgot-password` → email link → `/reset-password?token=...`. No auto-sign-in after reset.
- **Workspace switching:** In the dashboard, use the workspace dropdown in the header (when user has multiple workspaces).
- **Roles:** Admin, editor, reviewer, with RBAC on uploads, exports, and Trust Center admin.
- **Production:** Set `SESSION_SECRET`, `FRONTEND_URL`; use a real email provider for verification and reset. CSRF uses Origin/Referer; rate limiting on login.

## Workflow

1. **Documents** — Upload evidence (PDF, DOCX, XLSX). Files are parsed, chunked, and embedded for retrieval.
2. **Questionnaires** — Upload questionnaires (XLSX). Questions are parsed and linked to source cells.
3. **Review** — Open a questionnaire, click **Generate answers** (requires `OPENAI_API_KEY`). Edit answers inline, set status, use filters and bulk actions.
4. **Export** — Click **Export XLSX** to produce an XLSX with answers written back into the uploaded workbook. Download from Recent exports. (Exact placement in the original layout is not yet verified; see TC-13-001/TC-13-002.)

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
| `cd apps/api && pytest tests/ -v -m "not integration"` | Run tests (DB-dependent tests skip without Postgres). |
| `npm run test:e2e` | Run registry lifecycle E2E tests. Starts Postgres, MinIO, migrations, seeds, API, and Web; runs Playwright. Requires Docker and Python. |

## Trust Center

- **Admin** — `/dashboard/trust-center` — Manage trust articles.
- **Public** — `/trust` — Browse published articles (no auth).

## Docs

- **Release acceptance:** [`docs/acceptance/`](docs/acceptance/) — claims register, scope and release decisions.
- Operations, client, security, and engineering guides are being rewritten (TC-29-001 to TC-29-004). Earlier links pointed to documents that are not in this repository and have been removed (TC-01-005).
