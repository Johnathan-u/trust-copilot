/**
 * One command to start: Postgres (+ MinIO) → API + Web + Worker.
 * 1. Starts postgres and minio via Docker Compose (detached).
 * 2. Waits for Postgres (and MinIO) to be ready.
 * 3. Runs API, Web, and Worker with concurrently (same as dev:full).
 * Ctrl+C stops API/Web/Worker; Postgres and MinIO keep running (stop with: docker compose stop postgres minio).
 */
const { spawn } = require('child_process');
const net = require('net');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..');
const POSTGRES_PORT = 5432;
const MINIO_PORT = 9000;
const WAIT_RETRIES = 30;
const WAIT_MS = 1000;

function waitForPort(host, port, label) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    function tryConnect() {
      const socket = new net.Socket();
      const timeout = 2000;
      socket.setTimeout(timeout);
      socket.on('connect', () => {
        socket.destroy();
        console.log(`[dev-all] ${label} is ready (${host}:${port}).`);
        resolve();
      });
      socket.on('error', () => {
        socket.destroy();
        attempts++;
        if (attempts >= WAIT_RETRIES) {
          reject(new Error(`${label} did not become ready after ${WAIT_RETRIES} attempts.`));
          return;
        }
        setTimeout(tryConnect, WAIT_MS);
      });
      socket.on('timeout', () => {
        socket.destroy();
        attempts++;
        if (attempts >= WAIT_RETRIES) {
          reject(new Error(`${label} did not become ready after ${WAIT_RETRIES} attempts.`));
          return;
        }
        setTimeout(tryConnect, WAIT_MS);
      });
      socket.connect(port, host);
    }
    tryConnect();
  });
}

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(cmd, args, {
      cwd: opts.cwd || REPO_ROOT,
      stdio: opts.inherit ? 'inherit' : 'pipe',
      shell: opts.shell ?? true,
      ...opts,
    });
    if (!opts.inherit && p.stdout) p.stdout.pipe(process.stdout);
    if (!opts.inherit && p.stderr) p.stderr.pipe(process.stderr);
    p.on('error', reject);
    p.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`Exit ${code}`))));
  });
}

async function main() {
  console.log('[dev-all] Starting Postgres and MinIO (Docker)...');
  await run('docker', ['compose', 'up', '-d', 'postgres', 'minio'], { inherit: false });

  console.log('[dev-all] Waiting for Postgres and MinIO...');
  await Promise.all([
    waitForPort('127.0.0.1', POSTGRES_PORT, 'Postgres'),
    waitForPort('127.0.0.1', MINIO_PORT, 'MinIO'),
  ]);

  // Free 8000 and 3000 so API and Web can bind (best-effort; may not work from all sessions)
  console.log('[dev-all] Freeing ports 8000 and 3000 if in use...');
  try {
    await Promise.all([
      run('npx', ['--yes', 'kill-port', '8000'], { inherit: false }).catch(() => {}),
      run('npx', ['--yes', 'kill-port', '3000'], { inherit: false }).catch(() => {}),
    ]);
    await new Promise((r) => setTimeout(r, 2000));
  } catch (_) {}

  console.log('[dev-all] Starting API, Web, and Worker...');
  const child = spawn('npm', ['run', 'dev:full'], {
    env: {
      ...process.env,
      SKIP_PORT_CHECK: '1',
      DATABASE_URL: 'postgresql://postgres:postgres@localhost:5432/trustcopilot',
    },
    cwd: REPO_ROOT,
    stdio: 'inherit',
    shell: true,
  });

  function kill() {
    child.kill('SIGTERM');
    process.exit(0);
  }
  process.on('SIGINT', kill);
  process.on('SIGTERM', kill);

  child.on('close', (code) => {
    process.exit(code ?? 0);
  });
}

main().catch((err) => {
  console.error('[dev-all]', err.message);
  process.exit(1);
});
