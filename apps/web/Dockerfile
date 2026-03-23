# Stage: builder (production build)
FROM node:20 AS builder
WORKDIR /app
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web ./
# Avoid stale .next causing "Cannot find module './161.js'" (server chunk path mismatch)
RUN rm -rf .next
RUN npm run build

# Stage: production (run built app, with healthcheck)
FROM node:20 AS production
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app /app
EXPOSE 3000
CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "require('http').get('http://127.0.0.1:3000/', (r) => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))" || exit 1

# Stage: dev (default target for local docker compose; hot reload)
FROM node:20 AS dev
WORKDIR /app
COPY apps/web/package*.json ./
COPY apps/web /app
CMD ["sh", "-c", "npm install && npm run dev -- -H 0.0.0.0 -p 3000"]
