/**
 * Run API with correct DATABASE_URL for local dev (Postgres on localhost).
 * Ensures env is set before uvicorn starts, regardless of npm/concurrently behavior.
 */
const { spawn } = require('child_process');
const path = require('path');

const apiDir = path.resolve(__dirname, '../apps/api');
const env = {
  ...process.env,
  DATABASE_URL: 'postgresql://postgres:postgres@localhost:5432/trustcopilot',
};

const child = spawn('uvicorn', ['app.main:app', '--host', '0.0.0.0', '--port', '8000', '--reload'], {
  cwd: apiDir,
  env,
  stdio: 'inherit',
  shell: true,
});

child.on('close', (code) => process.exit(code ?? 0));
