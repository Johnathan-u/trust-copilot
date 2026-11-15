#!/usr/bin/env bash
# Database backup for Trust Copilot. Run from cron or a scheduler.
# Requires DATABASE_URL. Optional: BACKUP_DIR (default ./backups), BACKUP_S3_BUCKET.
# Do not commit credentials; inject them at runtime.
#
# A backup is published only after pg_dump and gzip both exit 0, the gzip
# stream checks out, and a sha256 sidecar matches. Bytes are written to a
# hidden partial file, verified, then renamed into trustcopilot_*.sql.gz.
# pg_dump, gzip, checksum, or publish failure exits nonzero, deletes the
# partial, and does not leave that new trustcopilot_*.sql.gz or its .sha256.
# The failure line names the stage, the exit code, and a message. It never
# includes DATABASE_URL, a password, or a connection string.
# An S3 upload failure still exits nonzero and logs that stage. The local
# verified archive is already published and is left in place.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
secret_tmp=""
PARTIAL=""
CHECKSUM_PARTIAL=""
FINAL=""
CHECKSUM_FINAL=""

redact() {
  local text="$1"
  local url="${DATABASE_URL-}"
  if [ -n "$url" ]; then
    text=${text//"$url"/[REDACTED_URL]}
    local rest="${url#*://}"
    if [ "$rest" != "$url" ]; then
      local userinfo="${rest%%@*}"
      if [ -n "$userinfo" ] && [ "$userinfo" != "$rest" ]; then
        text=${text//"$userinfo"/[REDACTED]}
        local pass="${userinfo#*:}"
        if [ -n "$pass" ] && [ "$pass" != "$userinfo" ]; then
          text=${text//"$pass"/[REDACTED]}
        fi
      fi
    fi
  fi
  text=$(
    printf '%s' "$text" | sed -E \
      -e 's#[a-zA-Z][a-zA-Z0-9+.-]*://[^[:space:]]+#[REDACTED_URL]#g' \
      -e 's#(password|passwd|pwd)=[^[:space:]]+#\1=[REDACTED]#gi'
  )
  printf '%s' "$text"
}

read_redacted() {
  local file="$1"
  if [ ! -s "$file" ]; then
    printf ''
    return 0
  fi
  redact "$(tr '\n\r' '  ' <"$file")"
}

fail() {
  trap - ERR EXIT
  set +e
  local stage="${1:-unknown}"
  local code="${2:-1}"
  local message="${3:-backup failed}"
  case "$code" in
    '' | *[!0-9]*) code=1 ;;
  esac
  if [ "$code" -lt 1 ] || [ "$code" -gt 255 ]; then
    code=1
  fi
  message=$(redact "$message")
  message=${message//$'\n'/ }
  message=${message//$'\r'/ }
  if [ "${#message}" -gt 300 ]; then
    message="${message:0:300}"
  fi
  if [ -z "${message// /}" ]; then
    message="backup failed"
  fi
  if [ -n "${secret_tmp:-}" ]; then
    rm -rf "$secret_tmp"
    secret_tmp=""
  fi
  if [ -n "${PARTIAL:-}" ]; then
    rm -f "$PARTIAL"
  fi
  if [ -n "${CHECKSUM_PARTIAL:-}" ]; then
    rm -f "$CHECKSUM_PARTIAL"
  fi
  printf 'BACKUP_FAILURE stage=%s exit_code=%s message=%s\n' "$stage" "$code" "$message" >&2
  exit "$code"
}

cleanup() {
  local status=$?
  trap - ERR EXIT
  set +e
  if [ -n "${secret_tmp:-}" ]; then
    rm -rf "$secret_tmp"
  fi
  if [ -n "${PARTIAL:-}" ]; then
    rm -f "$PARTIAL"
  fi
  if [ -n "${CHECKSUM_PARTIAL:-}" ]; then
    rm -f "$CHECKSUM_PARTIAL"
  fi
  exit "$status"
}

# No ERR trap. It would also run for a pg_dump, gzip, or checksum failure and
# exit before that stage and PIPESTATUS are recorded.
trap cleanup EXIT

if [ -z "${DATABASE_URL:-}" ]; then
  fail config 1 "DATABASE_URL not set"
fi

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
FINAL="$BACKUP_DIR/trustcopilot_${TIMESTAMP}.sql.gz"
PARTIAL="$BACKUP_DIR/.trustcopilot_${TIMESTAMP}.sql.gz.partial"
CHECKSUM_FINAL="$BACKUP_DIR/trustcopilot_${TIMESTAMP}.sql.gz.sha256"
CHECKSUM_PARTIAL="$BACKUP_DIR/.trustcopilot_${TIMESTAMP}.sql.gz.sha256.partial"
secret_tmp=$(mktemp -d)

set +e
pg_dump "$DATABASE_URL" 2>"$secret_tmp/dump.err" | gzip 2>"$secret_tmp/gzip.err" >"$PARTIAL"
statuses=("${PIPESTATUS[@]}")
set -e
dump_status=${statuses[0]:-1}
gzip_status=${statuses[1]:-1}

if [ "$dump_status" -ne 0 ]; then
  detail=$(read_redacted "$secret_tmp/dump.err")
  if [ -n "$detail" ]; then
    fail dump "$dump_status" "pg_dump failed: ${detail}"
  fi
  fail dump "$dump_status" "pg_dump failed"
fi
if [ "$gzip_status" -ne 0 ]; then
  detail=$(read_redacted "$secret_tmp/gzip.err")
  if [ -n "$detail" ]; then
    fail compress "$gzip_status" "gzip failed: ${detail}"
  fi
  fail compress "$gzip_status" "gzip failed"
fi

magic=$(od -An -t x1 -N 2 "$PARTIAL" | tr -d '[:space:]')
if [ "$magic" != "1f8b" ]; then
  fail compress 1 "compressed backup failed integrity check"
fi
if ! gzip -t "$PARTIAL" 2>"$secret_tmp/gzip-test.err"; then
  fail compress 1 "compressed backup failed integrity check"
fi

set +e
hash_line=$(sha256sum "$PARTIAL" 2>"$secret_tmp/sha.err")
sha_status=$?
set -e
if [ "$sha_status" -ne 0 ]; then
  detail=$(read_redacted "$secret_tmp/sha.err")
  if [ -n "$detail" ]; then
    fail checksum "$sha_status" "checksum failed: ${detail}"
  fi
  fail checksum "$sha_status" "checksum failed"
fi
hash=${hash_line%% *}
if ! printf '%s' "$hash" | grep -Eq '^[0-9a-f]{64}$'; then
  fail checksum 1 "checksum generation failed"
fi

base=$(basename "$FINAL")
set +e
printf '%s  %s\n' "$hash" "$base" >"$CHECKSUM_PARTIAL"
write_status=$?
set -e
if [ "$write_status" -ne 0 ]; then
  fail checksum "$write_status" "checksum sidecar write failed"
fi
read -r got_hash got_name <"$CHECKSUM_PARTIAL"
if [ "$got_hash" != "$hash" ] || [ "$got_name" != "$base" ]; then
  fail checksum 1 "checksum sidecar unreadable"
fi

set +e
hash2=$(sha256sum "$PARTIAL" 2>"$secret_tmp/sha2.err" | awk '{print $1}')
sha2_status=$?
set -e
if [ "$sha2_status" -ne 0 ] || [ "$hash2" != "$hash" ]; then
  fail checksum 1 "checksum mismatch"
fi

set +e
mv -f "$PARTIAL" "$FINAL"
mv_status=$?
set -e
if [ "$mv_status" -ne 0 ]; then
  fail publish "$mv_status" "rename of backup failed"
fi
set +e
mv -f "$CHECKSUM_PARTIAL" "$CHECKSUM_FINAL"
mv_status=$?
set -e
if [ "$mv_status" -ne 0 ]; then
  rm -f "$FINAL"
  fail publish "$mv_status" "rename of checksum failed"
fi

set +e
published=$(sha256sum "$FINAL" 2>"$secret_tmp/sha3.err" | awk '{print $1}')
pub_status=$?
set -e
if [ "$pub_status" -ne 0 ] || [ "$published" != "$hash" ]; then
  rm -f "$FINAL" "$CHECKSUM_FINAL"
  fail publish 1 "published backup checksum mismatch"
fi

printf 'Backup written: %s\n' "$FINAL"
printf 'Checksum: %s  %s\n' "$hash" "$base"

if [ -n "${BACKUP_S3_BUCKET:-}" ]; then
  if command -v aws >/dev/null 2>&1; then
    set +e
    aws s3 cp "$FINAL" "s3://${BACKUP_S3_BUCKET}/$(basename "$FINAL")" --only-show-errors \
      2>"$secret_tmp/aws.err"
    aws_status=$?
    set -e
    if [ "$aws_status" -ne 0 ]; then
      detail=$(read_redacted "$secret_tmp/aws.err")
      if [ -n "$detail" ]; then
        fail upload "$aws_status" "s3 upload failed: ${detail}"
      fi
      fail upload "$aws_status" "s3 upload failed"
    fi
    printf 'Uploaded to s3://%s/%s\n' "$BACKUP_S3_BUCKET" "$(basename "$FINAL")"
  fi
fi
