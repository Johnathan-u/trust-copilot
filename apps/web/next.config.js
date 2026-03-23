/** @type {import('next').NextConfig} */
const apiBase = process.env.API_UPSTREAM || 'http://localhost:8000'
const nextConfig = {
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${apiBase}/api/:path*` },
    ]
  },
}

module.exports = nextConfig
