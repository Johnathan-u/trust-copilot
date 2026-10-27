#!/usr/bin/env bash
# Evidence runner for TC-02-006 (runs on the box; writes logs + summary.tsv).
# Baseline = the TC-02-003 commit this ticket is stacked on ($BASE, checked out in a
# temporary worktree). Head = the working tree of tc/platform/TC-02-006.
set -u
REPO=/workspace/tc-platform-web
OUT=$REPO/artifacts/acceptance/TC-02-006
BASE=${BASE:?set BASE to the TC-02-003 commit}
BW=/tmp/tc006-baseline
PY=/workspace/tc-web-venv/bin
mkdir -p "$OUT/logs"
export PATH=/workspace/tools/node-v24.22.1-linux-x64/bin:$PY:$PATH NEXT_TELEMETRY_DISABLED=1
: > "$OUT/summary.tsv"
step() { # name dir cmd...
  local name=$1 dir=$2; shift 2
  ( cd "$dir" && bash -o pipefail -c "$*" ) > "$OUT/logs/$name.log" 2>&1
  local rc=$?
  printf '%s\t%s\t%s\t%s\n' "$name" "$rc" "${dir/#$BW/<baseline-worktree>}" "$*" >> "$OUT/summary.tsv"
  echo "$name rc=$rc"
}
W=$REPO/apps/web; A=$REPO/apps/api

# ---- baseline (TC-02-003 commit) ------------------------------------------------
git -C "$REPO" worktree remove --force $BW 2>/dev/null; rm -rf $BW
git -C "$REPO" worktree add --detach $BW "$BASE" >/dev/null 2>&1
cp "$A/tests/release/test_web_quality.py" $BW/apps/api/tests/release/
step 00a-baseline-npm-ci $BW/apps/web "npm ci --ignore-scripts --no-audit --no-fund"
step 00b-baseline-pytest-quality $BW/apps/api "python -m pytest tests/release/test_web_quality.py -q -rs -p no:cacheprovider"
step 00c-baseline-npm-run-lint $BW/apps/web "npm run lint"
step 00d-baseline-unit $BW/apps/web "npm run test:unit"
step 00e-baseline-format-check $BW/apps/web "npm run format:check 2>&1 | tail -n 3; npx prettier --check '**/*.{ts,tsx,js,jsx,json,md}' 2>&1 | grep -c '^\[warn\] [^C]'"
step 00f-baseline-eslint-with-006-config $BW/apps/web "$W/node_modules/.bin/eslint -c $W/eslint.config.mjs . -f json -o $OUT/baseline-eslint.json; python3 -c \"import json,collections;d=json.load(open('$OUT/baseline-eslint.json'));c=collections.Counter(m['ruleId'] for f in d for m in f['messages']);print('files',sum(1 for f in d if f['messages']),'errors',sum(f['errorCount'] for f in d),'warnings',sum(f['warningCount'] for f in d));[print(n,r) for r,n in c.most_common()]\""
step 00g-baseline-eslint-with-006-config-plus-set-state-in-effect $BW/apps/web "$W/node_modules/.bin/eslint -c $W/eslint.config.mjs . --rule \"react-hooks/set-state-in-effect: error\" -f json -o $OUT/baseline-eslint-strict.json; python3 -c \"import json,collections;d=json.load(open('$OUT/baseline-eslint-strict.json'));c=collections.Counter(m['ruleId'] for f in d for m in f['messages']);print('files',sum(1 for f in d if f['messages']),'errors',sum(f['errorCount'] for f in d),'warnings',sum(f['warningCount'] for f in d));[print(n,r) for r,n in c.most_common()]\""
git -C "$REPO" worktree remove --force $BW; rm -rf $BW

# ---- head (TC-02-006) ----------------------------------------------------------
step 01-npm-ci $W "rm -rf node_modules .next && npm ci --ignore-scripts --no-audit --no-fund"
step 02-versions $W "node --version; npm --version; npx --no-install tsc --version; npx --no-install eslint --version; npx --no-install prettier --version; npx --no-install vitest --version; npx --no-install next --version"
step 03-typecheck $W "npm run typecheck"
step 04-lint $W "npm run lint"
step 05-format-check $W "npm run format:check"
step 06-unit $W "npm run test:unit && npx vitest run --reporter=json --outputFile=$OUT/vitest-results.json >/dev/null"
step 07-build $W "npm run build"
step 08-audit-runtime $W "npm audit --omit=dev --audit-level=high"
step 09-audit-all $W "npm audit --audit-level=low"
step 10-pytest-release $A "TC_REQUIRE_WEB_TOOLCHAIN=1 python -m pytest tests/release/test_web_quality.py tests/release/test_web_lock.py -q -rs -p no:cacheprovider"
step 11-ruff $A "ruff check tests/release/ && ruff format --check tests/release/"
step 12-pre-commit-changed $REPO "pre-commit run --files \$(git diff --name-only --diff-filter=d $BASE HEAD | grep -v '^artifacts/acceptance/TC-02-006/')"
step 13-quality-script $W "npm run quality"
step 14-tested-inputs $REPO "git ls-files apps/web/package.json apps/web/package-lock.json apps/web/eslint.config.mjs apps/web/vitest.config.ts apps/web/.prettierignore apps/web/tests .pre-commit-config.yaml .github/workflows/ci.yml apps/api/tests/release | xargs sha256sum > $OUT/tested-inputs.sha256 && wc -l < $OUT/tested-inputs.sha256 && git rev-parse HEAD"
git -C "$REPO" checkout -- apps/web/tsconfig.tsbuildinfo apps/web/next-env.d.ts 2>/dev/null
true
