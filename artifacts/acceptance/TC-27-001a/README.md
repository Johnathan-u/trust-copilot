# TC-27-001a: deterministic backup compress failure

The compress cases of `test_failed_stage_exits_nonzero_and_publishes_nothing`
sometimes exited 120. The expected exit code is still 1. This note does not
accept TC-27-001 or TC-27-001a.

## Root cause

`scripts/backup_db.sh` runs `pg_dump | gzip`. The full-disk fake gzip writes a
short stdout and exits 1 without reading the dump. The broken-stream fake gzip
exits 0 without reading it either. Whichever side the scheduler runs first
decides whether the dump stub's stdout flush hits a closed pipe.

The dump stub is Python. Python ignores SIGPIPE and turns the failed flush into
`BrokenPipeError` while the interpreter is shutting down. `Py_FinalizeEx` then
fails and the process exits 120, replacing the `SystemExit(0)` the stub asked
for. That is intermittent: a small write often lands in the pipe buffer before
gzip exits, and the stub exits 0.

The script recorded both `PIPESTATUS` values and treated any nonzero `pg_dump`
status as the dump stage before it looked at gzip. A closed-pipe dump (120 in
the stub, 141 for a native SIGPIPE) therefore hid gzip's exit 1, or skipped the
integrity check when the broken-stream stub had already exited 0. The alert was
`stage=dump exit_code=120`.

Both sides had to change. A stub-only swallow of `EPIPE` would make the test
exit 1 while a real `pg_dump` killed by SIGPIPE would still be reported as a
dump failure. A script-only change would still leave the broken-stream stub
closing the pipe early, so the dump status would keep racing.

## Fix

The fake gzip exits with `os._exit`, so finalization cannot rewrite its code.
Full-disk mode still does not read stdin. Broken-stream mode reads stdin to EOF
before it exits 0, which is what a gzip that accepts the stream does.

The fake pg_dump writes one byte more than the pipe buffer, with `os.write`,
and on `EPIPE` calls `os._exit(141)` (`128 + SIGPIPE`). The full-disk case
therefore always ends with dump status 141 and gzip status 1. The success and
broken-stream cases always finish the write and exit 0. `exit42` still exits 42
before writing.

When gzip's status is nonzero, the script reports `compress` and gzip's code.
`pg_dump`'s status is the dump stage when gzip exits 0. The operator note is in
`docs/ops/BACKUP_RESTORE.md`.

## Reproduction counts

Red runs used master `c902d2ccf8d084398694928fe899be89acfefb08`. Green runs used
the script and stubs in this commit. Logs: `failing-before.txt`,
`passing-after.txt`.

| Case | Before | After |
|---|---|---|
| full disk, natural, 200 runs | 17 exited 120 (`stage=dump`) | 200 exited 1, writer 141, `stage=compress` |
| broken stream, natural, 100 runs | 1 exited 120 (`stage=dump`) | 100 exited 1, writer 0, integrity message |
| full disk, 0.05s delay before the dump write | 25/25 exited 120 | 30/30 exited 1, writer 141 |
| full disk, 8 workers, 40 runs | | 40 exited 1, writer 141 |
| broken stream, 8 workers, 40 runs | | 40 exited 1, writer 0 |
| `pytest --noconftest tests/release/test_backup_failure.py` | | 15 repeats, 8 passed, 0 failed |

Local interpreter: Python 3.12.3, pytest 9.2.0. `--noconftest` skipped the API
fixture module; this test does not use it.
