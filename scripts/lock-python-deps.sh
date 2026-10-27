#!/usr/bin/env bash
# TC-02-002: regenerate the API dependency locks from apps/api/pyproject.toml.
#   apps/api/requirements.lock      runtime dependencies only (Docker image, production)
#   apps/api/requirements-dev.lock  runtime + the `dev` extra, constrained to the runtime pins
# Both are universal (any OS) for Python 3.11 and carry hashes, so installs use --require-hashes.
# Existing pins are kept unless pyproject.toml needs a change; pass --upgrade to re-resolve all.
# Needs uv (https://docs.astral.sh/uv/). Run from anywhere; commit both files together.
set -euo pipefail
cd "$(dirname "$0")/../apps/api"
common=(--universal --python-version 3.11 --generate-hashes --quiet
  --custom-compile-command "scripts/lock-python-deps.sh")
uv pip compile pyproject.toml "${common[@]}" "$@" -o requirements.lock
uv pip compile pyproject.toml --extra dev --constraint requirements.lock "${common[@]}" "$@" \
  -o requirements-dev.lock
echo "Wrote apps/api/requirements.lock and apps/api/requirements-dev.lock"
