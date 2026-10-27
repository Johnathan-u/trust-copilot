#!/usr/bin/env bash
# Evidence runner for TC-02-003 (runs on the box; writes logs + summary.tsv)
set -u
REPO=/workspace/tc-platform-web
OUT=$REPO/artifacts/acceptance/TC-02-003
mkdir -p "$OUT/logs"
export PATH=/workspace/tools/node-v24.22.1-linux-x64/bin:$PATH NEXT_TELEMETRY_DISABLED=1
: > "$OUT/summary.tsv"
step() { # name dir cmd...
  local name=$1 dir=$2; shift 2
  ( cd "$dir" && bash -o pipefail -c "$*" ) > "$OUT/logs/$name.log" 2>&1
  local rc=$?
  printf '%s\t%s\t%s\t%s\n' "$name" "$rc" "$dir" "$*" >> "$OUT/summary.tsv"
  echo "$name rc=$rc"
}
W=$REPO/apps/web; A=$REPO/apps/api
step 01-npm-ci $W "rm -rf node_modules .next && npm ci --ignore-scripts --no-audit --no-fund"
step 02-typecheck $W "npm run typecheck"
step 03-build $W "npm run build"
step 04-audit-runtime $W "npm audit --omit=dev --audit-level=high"
step 05-audit-all $W "npm audit --audit-level=low"
step 06-pytest-release $A "/workspace/tc-web-venv/bin/python -m pytest tests/release/test_web_lock.py -q -p no:cacheprovider"
step 07-ruff $A "/workspace/tc-web-venv/bin/ruff check tests/release/test_web_lock.py && /workspace/tc-web-venv/bin/ruff format --check tests/release/test_web_lock.py"
step 08-docker-build-production $REPO "sudo -n docker build -f apps/web/Dockerfile --target production -t tc-web-003:evidence . 2>&1 | tail -25"
step 09-docker-build-dev $REPO "sudo -n docker build -f apps/web/Dockerfile --target dev -t tc-web-003-dev:evidence . 2>&1 | tail -8"
step 10-image-contents $REPO "sudo -n docker run --rm --network none --entrypoint sh tc-web-003:evidence -c 'echo user=\$(id -un); echo node=\$(node -v); echo top-level-modules: \$(ls /app/node_modules); for p in typescript vitest playwright @playwright prettier tailwindcss postcss autoprefixer esbuild vite eslint; do if [ -e /app/node_modules/\$p ]; then echo PRESENT \$p; exit 1; else echo absent \$p; fi; done; for b in npm npx corepack; do if command -v \$b; then echo PRESENT \$b; exit 1; else echo absent \$b; fi; done; test ! -e /app/node_modules/next/dist/bin/next && echo absent next-cli; du -sh /app'"
step 11-container-smoke $REPO "sudo -n docker rm -f tc-web-003-smoke >/dev/null 2>&1; sudo -n docker run -d --name tc-web-003-smoke --network none tc-web-003:evidence >/dev/null && sleep 6 && sudo -n docker exec tc-web-003-smoke node -e \"const h=require('http');h.get('http://127.0.0.1:3000/login',r=>{console.log('GET /login',r.statusCode);h.get('http://127.0.0.1:3000/dashboard',s=>{console.log('GET /dashboard',s.statusCode,s.headers.location);process.exit(r.statusCode===200&&s.statusCode===307?0:1)})})\"; rc=\$?; sudo -n docker logs tc-web-003-smoke; sudo -n docker rm -f tc-web-003-smoke >/dev/null; exit \$rc"
step 12-trivy-image $REPO "rm -f /tmp/tc-web-003-ev.tar; sudo -n docker save tc-web-003:evidence -o /tmp/tc-web-003-ev.tar && sudo -n chown box /tmp/tc-web-003-ev.tar && /workspace/tools/trivy image --input /tmp/tc-web-003-ev.tar --scanners vuln --severity HIGH,CRITICAL --format json -o $OUT/trivy-production-image.json -q && /workspace/tools/trivy --version | head -1"
