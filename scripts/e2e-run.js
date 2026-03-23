/**
 * E2E test runner: starts Postgres, MinIO, migrations, seeds, API+Web, then runs Playwright.
 *
 * Uses deterministic alternate ports (18080, 13000) to avoid conflicts with dev servers.
 * Single command: npm run test:e2e
 * Requires: Docker (for postgres, minio), Node, Python, npm.
 */
const { spawn } = require('child_process');
const http = require('http');
const net = require('net');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..');
const API_DIR = path.join(REPO_ROOT, 'apps/api');
const WEB_DIR = path.join(REPO_ROOT, 'apps/web');
const POSTGRES_PORT = 5432;
const MINIO_PORT = 9000;
const DB_URL = 'postgresql://postgres:postgres@localhost:5432/trustcopilot';
const WAIT_RETRIES = 60;
const WAIT_MS = 1000;

// E2E-only ports: avoid conflicts with dev servers on 8000/3000
const E2E_API_PORT = 18080;
const E2E_WEB_PORT = 13000;

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, {
      cwd: opts.cwd || REPO_ROOT,
      stdio: opts.inherit ? 'inherit' : 'pipe',
      shell: opts.shell ?? true,
      env: { ...process.env, ...(opts.env || {}) },
      ...opts,
    });
    if (!opts.inherit && p.stdout) p.stdout.pipe(process.stdout);
    if (!opts.inherit && p.stderr) p.stderr.pipe(process.stderr);
    p.on('error', reject);
    p.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`Exit ${code}`))));
  });
}

function killProcessOnPort(port) {
  return run('npx', ['--yes', 'kill-port', String(port)], { inherit: false }).then(
    () => true,
    () => false
  );
}

function waitForPort(host, port, label) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    function tryConnect() {
      const socket = new net.Socket();
      socket.setTimeout(2000);
      socket.on('connect', () => {
        socket.destroy();
        console.log(`[e2e] ${label} ready (${host}:${port})`);
        resolve();
      });
      socket.on('error', () => {
        socket.destroy();
        attempts++;
        if (attempts >= WAIT_RETRIES) {
          reject(new Error(`${label} did not become ready`));
          return;
        }
        setTimeout(tryConnect, WAIT_MS);
      });
      socket.on('timeout', () => {
        socket.destroy();
        attempts++;
        if (attempts >= WAIT_RETRIES) {
          reject(new Error(`${label} did not become ready`));
          return;
        }
        setTimeout(tryConnect, WAIT_MS);
      });
      socket.connect(port, host);
    }
    tryConnect();
  });
}

function waitForHttp(url, label) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    function tryFetch() {
      const req = http.get(url, (res) => {
        if (res.statusCode >= 200 && res.statusCode < 500) {
          console.log(`[e2e] ${label} ready (${url})`);
          resolve();
        } else {
          next();
        }
      });
      req.on('error', () => next());
      req.setTimeout(3000, () => {
        req.destroy();
        next();
      });
    }
    function next() {
      attempts++;
      if (attempts >= WAIT_RETRIES) {
        reject(new Error(`${label} did not become ready`));
        return;
      }
      setTimeout(tryFetch, WAIT_MS);
    }
    tryFetch();
  });
}

async function ensurePortFree(port, label) {
  const killed = await killProcessOnPort(port);
  if (killed) {
    console.log(`[e2e] Killed process on port ${port}`);
    await new Promise((r) => setTimeout(r, 1500));
  }
  const portInUse = await new Promise((resolve) => {
    const s = new net.Socket();
    s.setTimeout(800);
    s.on('connect', () => { s.destroy(); resolve(true); });
    s.on('error', () => { s.destroy(); resolve(false); });
    s.on('timeout', () => { s.destroy(); resolve(false); });
    s.connect(port, '127.0.0.1');
  });
  if (portInUse) {
    throw new Error(`[e2e] Port ${port} (${label}) still in use after kill. Stop the process manually and retry.`);
  }
}

async function main() {
  console.log('[e2e] Starting Postgres and MinIO...');
  await run('docker', ['compose', 'up', '-d', 'postgres', 'minio'], { inherit: false });

  console.log('[e2e] Waiting for Postgres and MinIO...');
  await Promise.all([
    waitForPort('127.0.0.1', POSTGRES_PORT, 'Postgres'),
    waitForPort('127.0.0.1', MINIO_PORT, 'MinIO'),
  ]);

  console.log('[e2e] Running migrations...');
  await run('python', ['-m', 'alembic', 'upgrade', 'head'], {
    cwd: API_DIR,
    env: { DATABASE_URL: DB_URL, S3_ENDPOINT: 'http://localhost:9000' },
  });

  console.log('[e2e] Seeding demo workspace (demo@trust.local / j)...');
  await run('python', ['-m', 'scripts.seed_demo_workspace'], {
    cwd: API_DIR,
    env: { DATABASE_URL: DB_URL, S3_ENDPOINT: 'http://localhost:9000' },
  });

  console.log('[e2e] Seeding E2E registry data...');
  await run('python', ['-m', 'scripts.seed_e2e_registry'], {
    cwd: API_DIR,
    env: { DATABASE_URL: DB_URL, S3_ENDPOINT: 'http://localhost:9000' },
  });

  console.log(`[e2e] Ensuring E2E ports free: API ${E2E_API_PORT}, Web ${E2E_WEB_PORT}`);
  await Promise.all([
    ensurePortFree(E2E_API_PORT, 'API'),
    ensurePortFree(E2E_WEB_PORT, 'Web'),
  ]);

  const apiUrl = `http://127.0.0.1:${E2E_API_PORT}`;
  const webUrl = `http://127.0.0.1:${E2E_WEB_PORT}`;
  // CSRF / cookie Domain alignment: browser Origin must be in trusted_origins (SEC-201).
  const trustedForE2e = [
    webUrl,
    `http://localhost:${E2E_WEB_PORT}`,
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost',
    'http://127.0.0.1',
  ].join(',');
  console.log(`[e2e] Starting API on ${E2E_API_PORT}, Web on ${E2E_WEB_PORT}`);
  const apiProc = spawn(
    'uvicorn',
    ['app.main:app', '--host', '0.0.0.0', '--port', String(E2E_API_PORT)],
    {
      cwd: API_DIR,
      env: {
        ...process.env,
        TRUST_COPILOT_E2E_RUNNER: '1',
        DATABASE_URL: DB_URL,
        S3_ENDPOINT: 'http://localhost:9000',
        RATE_LIMIT_RPM_PER_IP: '0',
        FRONTEND_URL: webUrl,
        APP_BASE_URL: webUrl,
        TRUSTED_ORIGINS: trustedForE2e,
      },
      stdio: 'inherit',
      shell: true,
    }
  );
  const webProc = spawn('npm', ['run', 'dev', '--', '-p', String(E2E_WEB_PORT)], {
    cwd: WEB_DIR,
    env: {
      ...process.env,
      API_UPSTREAM: apiUrl,
    },
    stdio: 'inherit',
    shell: true,
  });

  const cleanup = () => {
    apiProc.kill('SIGTERM');
    webProc.kill('SIGTERM');
  };
  process.on('SIGINT', cleanup);
  process.on('SIGTERM', cleanup);

  console.log('[e2e] Waiting for API and Web to be ready...');
  await Promise.all([
    waitForHttp(`${apiUrl}/healthz`, 'API'),
    waitForHttp(`${webUrl}/`, 'Web'),
  ]);
  // Pre-compile /login so Playwright setup does not race cold Next builds (avoids flaky auth.setup).
  await waitForHttp(`${webUrl}/login`, 'Web /login');

  const pwExtra = process.argv.slice(2);
  const pwArgs = ['playwright', 'test', ...pwExtra];
  console.log('[e2e] Running Playwright:', pwArgs.join(' '));
  const pwExit = await new Promise((resolve) => {
    const pw = spawn('npx', pwArgs, {
      cwd: WEB_DIR,
      env: {
        ...process.env,
        E2E_SERVER_RUNNING: '1',
        E2E_WEB_PORT: String(E2E_WEB_PORT),
        E2E_API_PORT: String(E2E_API_PORT),
        API_UPSTREAM: apiUrl,
      },
      stdio: 'inherit',
      shell: true,
    });
    pw.on('close', (code) => resolve(code ?? 0));
  });

  cleanup();
  process.exit(pwExit);
}

main().catch((err) => {
  console.error('[e2e]', err.message);
  process.exit(1);
});
