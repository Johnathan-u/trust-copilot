# Database backup

Operator notes for `scripts/backup_db.sh` (TC-27-001). This page does not cover a
full restore drill. That is TC-27-003. Do not paste `DATABASE_URL`, a password, or
a connection string into a ticket, a log excerpt, or this file.

`docker-compose.prod.yml` does not run the backup. Run the script from cron or a
scheduler on a host that has `pg_dump`, `gzip`, and `sha256sum`. Put `DATABASE_URL`
in the environment for that run. Do not commit it.

```bash
DATABASE_URL="postgresql://..." BACKUP_DIR=/var/backups/trustcopilot scripts/backup_db.sh
```

Optional: `BACKUP_S3_BUCKET`. When it is set and the `aws` CLI is on `PATH`, the
script uploads the published archive after the local publish. The checksum sidecar
stays next to the local archive.

## Success

A successful run exits 0 and prints `Backup written:` and `Checksum:`. It leaves
two files in `BACKUP_DIR`:

- `trustcopilot_<UTC YYYYMMDD_HHMMSS>.sql.gz`
- `trustcopilot_<UTC YYYYMMDD_HHMMSS>.sql.gz.sha256`

The sidecar is a `sha256sum` line: the digest, two spaces, and the archive's base
name. Check it from that directory:

```bash
cd "$BACKUP_DIR" && sha256sum -c trustcopilot_<timestamp>.sql.gz.sha256
```

The script writes the archive to a hidden `.trustcopilot_<timestamp>.sql.gz.partial`
file in the same directory, checks the gzip magic and `gzip -t`, computes the
sha256 twice, writes the sidecar to a partial name, and only then renames the
archive and the sidecar into the names above. The partial names are removed on
the way out.

## Failure

These stages exit nonzero and do not leave a new `trustcopilot_*.sql.gz` or a new
`.sha256` for that attempt. An older published backup in the same directory is
left as it was. Partial files from the failed attempt are removed.

| Stage | When | Exit code |
|---|---|---|
| `config` | `DATABASE_URL` is missing | 1 |
| `dump` | `pg_dump` exits nonzero (for example 42) | that exit code |
| `compress` | `gzip` exits nonzero, including a full disk while the archive is written, or the bytes are not a gzip stream | gzip's exit code, or 1 for a bad stream |
| `checksum` | `sha256sum` fails, the sidecar cannot be written, or the digest does not match | that exit code, or 1 |
| `publish` | the rename fails, or the published bytes no longer match the digest | that exit code, or 1 |
| `upload` | `aws s3 cp` fails after a local publish | that exit code |

`dump`, `compress`, `checksum`, and `publish` delete the partial and do not
rename a new archive into place. `upload` is different: the local archive and
sidecar are already published, and they stay. The script still exits nonzero.

Stderr is one line:

```text
BACKUP_FAILURE stage=<stage> exit_code=<code> message=<message>
```

`message` names the failing tool and a short diagnostic. Tool stderr is kept only
long enough to build that line. `DATABASE_URL`, URL userinfo, passwords, and any
`scheme://...` string are replaced before the line is written. The captured tool
stderr is deleted before the script exits. The line does not include credentials
or a connection string.

A full disk while `gzip` is writing looks like gzip's own error, for example
`gzip: stdout: No space left on device`, and the stage is `compress`. A full disk
while `sha256sum` is writing is stage `checksum`.

If `BACKUP_S3_BUCKET` is set but the `aws` CLI is not installed, the script still
exits 0 after the local publish. That skip is unchanged. Install the CLI or unset
the bucket when an off-host copy is required.
