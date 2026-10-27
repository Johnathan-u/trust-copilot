# syntax=docker/dockerfile:1
# Trust Copilot web image (TC-02-003).
# - Node version is pinned and must match apps/web/.nvmrc and package.json "engines".
# - Dependencies install strictly from package-lock.json (npm ci) with lifecycle
#   scripts disabled; no locked package needs an install script on Linux.
# - The production stage ships only Next.js standalone output (traced runtime
#   files): no dev server tooling, test runners, type checker, formatter or npm.
ARG NODE_IMAGE=node:24.22.1-trixie-slim@sha256:43b9ba1142b8dcf33fa8f922ca1be85714adc444e0586c7cf7726daaeabc1bea

# Stage: deps (locked install, shared by builder and dev)
FROM ${NODE_IMAGE} AS deps
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package.json apps/web/package-lock.json apps/web/.npmrc ./
RUN npm ci --ignore-scripts --no-audit --no-fund

# Stage: builder (production build)
FROM deps AS builder
COPY apps/web ./
# TC-03-001: production images never enable the one-click demo login, even if an .env file in the
# build context sets it (process env takes precedence over .env files in Next.js).
ENV NEXT_PUBLIC_DEMO_LOGIN_EMAIL="" \
    NEXT_PUBLIC_DEMO_LOGIN_PASSWORD=""
# Avoid stale .next causing "Cannot find module './161.js'" (server chunk path mismatch)
RUN rm -rf .next && npm run build

# Stage: production (standalone server only, non-root, with healthcheck)
FROM ${NODE_IMAGE} AS production
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
# The runtime never installs packages: drop npm/npx/corepack from the image.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
      /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "require('http').get('http://127.0.0.1:3000/', (r) => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))" || exit 1

# Stage: dev (default target for local docker compose; hot reload)
# Uses the lockfile as-is (npm ci) so a bind-mounted checkout never rewrites it.
FROM deps AS dev
COPY apps/web /app
CMD ["sh", "-c", "npm ci --ignore-scripts --no-audit --no-fund && npm run dev -- -H 0.0.0.0 -p 3000"]
