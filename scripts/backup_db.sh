#!/usr/bin/env bash
# Database backup script for Trust Copilot. Run via cron or scheduler.
# Requires: DATABASE_URL in env (or PG* vars). Optional: BACKUP_DIR, BACKUP_S3_BUCKET.
# Do not commit credentials; inject at runtime.

set -e
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/trustcopilot_${TIMESTAMP}.sql.gz"

if [ -n "$DATABASE_URL" ]; then
  pg_dump "$DATABASE_URL" | gzip > "$FILE"
else
  echo "ERROR: DATABASE_URL not set" >&2
  exit 1
fi

echo "Backup written: $FILE"
if [ -n "$BACKUP_S3_BUCKET" ]; then
  if command -v aws >/dev/null 2>&1; then
    aws s3 cp "$FILE" "s3://${BACKUP_S3_BUCKET}/$(basename "$FILE")" --only-show-errors
    echo "Uploaded to s3://${BACKUP_S3_BUCKET}/$(basename "$FILE")"
  fi
fi
