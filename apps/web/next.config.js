const path = require('path')

/** @type {import('next').NextConfig} */
const apiBase = process.env.API_UPSTREAM || 'http://localhost:8000'
const nextConfig = {
  // TC-02-003: emit a self-contained server bundle (.next/standalone) so the
  // production image ships only traced runtime files, not dev/test tooling.
  output: 'standalone',
  // Pin the workspace root to apps/web; the repo root also has a lockfile.
  outputFileTracingRoot: path.join(__dirname),
  turbopack: { root: path.join(__dirname) },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${apiBase}/api/:path*` }]
  },
}

module.exports = nextConfig
