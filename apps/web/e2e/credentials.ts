/**
 * E2E seed-account credentials (TC-07-001): never committed.
 * Values come from the same TC_SEED_* variables the API seed scripts use
 * (apps/api/scripts/_seed_credentials.py). scripts/e2e-run.js generates them per run.
 */
function required(name: string): string {
  const v = process.env[name]
  if (!v) {
    throw new Error(
      `${name} is not set. Export the seed passwords (see apps/api/.seed-credentials.local) or run npm run test:e2e.`,
    )
  }
  return v
}

export const DEMO_EMAIL = process.env.TC_SEED_DEMO_EMAIL || 'demo@trust.local'
export const ADMIN_EMAIL = process.env.TC_SEED_ADMIN_EMAIL || 'admin@trust.local'
export const demoPassword = (): string => required('TC_SEED_DEMO_PASSWORD')
export const adminPassword = (): string => required('TC_SEED_ADMIN_PASSWORD')
