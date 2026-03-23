/**
 * Stop all dev stack: Docker Compose down (Postgres, MinIO).
 * Does not kill Node/uvicorn on 3000/8000; stop those with Ctrl+C in the dev:all terminal.
 */
const { spawnSync } = require('child_process')
const path = require('path')

const REPO_ROOT = path.resolve(__dirname, '..')

const r = spawnSync('docker', ['compose', 'down'], {
  cwd: REPO_ROOT,
  stdio: 'inherit',
  shell: true,
})
process.exit(r.status ?? 0)
