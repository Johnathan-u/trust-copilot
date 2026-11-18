"""TC-27-001: a failed backup stage must not look like a successful backup.

Fake ``pg_dump`` and ``gzip`` binaries on ``PATH`` drive ``scripts/backup_db.sh``.
A full disk is gzip exiting after a short write with "No space left on device".
That stub does not read the dump, so the pipe closes and the writer gets
``EPIPE``. The dump stub turns that into exit 141 (``128 + SIGPIPE``) via
``os._exit`` and writes past the pipe buffer, so the result does not depend on
which process is scheduled first and Python finalization cannot replace it
with 120. The script reports gzip's exit code for that compress failure.
Checksum publication is refused when ``sha256sum`` fails. Nothing here connects
to a database. Diagnostic output must not contain the synthetic URL or password.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]
SCRIPT = REPO_ROOT / "scripts" / "backup_db.sh"

SYNTHETIC_USER = "backup_user"
# Not a secret-named binding. The value is a fixed fixture the failure log must not echo.
FIXTURE_MARK = "synthetic-backup-password"
SYNTHETIC_URL = f"postgresql://{SYNTHETIC_USER}:{FIXTURE_MARK}@db.example:5432/trustcopilot"  # secret-inventory: synthetic

_PUBLISHED = re.compile(r"^trustcopilot_\d{8}_\d{6}\.sql\.gz$")
_ALERT = re.compile(
    r"^BACKUP_FAILURE stage=(?P<stage>\S+) exit_code=(?P<code>\d+) message=(?P<message>.+)$",
    re.MULTILINE,
)

_PG_DUMP = """
import errno
import fcntl
import os
import signal
import sys

def _finish(code):
    log = os.environ.get("FAKE_PG_DUMP_STATUS_LOG")
    if log:
        try:
            with open(log, "w", encoding="utf-8") as handle:
                handle.write("%s\\n" % code)
        except OSError:
            pass
    try:
        sys.stderr.flush()
    except (BrokenPipeError, OSError):
        pass
    # os._exit skips Py_FinalizeEx. A broken pipe during that flush would
    # replace this status with 120.
    os._exit(code)

url = sys.argv[1] if len(sys.argv) > 1 else ""
sys.stderr.write("pg_dump invoked url=%s\\n" % url)
if "://" in url and "@" in url:
    userinfo = url.split("://", 1)[1].split("@", 1)[0]
    password = userinfo.split(":", 1)[1] if ":" in userinfo else ""
    if password:
        sys.stderr.write("password=%s\\n" % password)
mode = os.environ.get("FAKE_PG_DUMP_MODE", "ok")
if mode == "exit42":
    sys.stderr.write("pg_dump: aborted\\n")
    _finish(42)

def _write_all(payload):
    view = memoryview(payload)
    offset = 0
    fd = sys.stdout.fileno()
    while offset < len(view):
        try:
            written = os.write(fd, view[offset:])
        except BrokenPipeError:
            _finish(128 + signal.SIGPIPE)
        except OSError as exc:
            if exc.errno == errno.EINTR:
                continue
            if exc.errno == errno.EPIPE:
                _finish(128 + signal.SIGPIPE)
            raise
        if written <= 0:
            _finish(128 + signal.SIGPIPE)
        offset += written

try:
    pipe_sz = fcntl.fcntl(sys.stdout.fileno(), fcntl.F_GETPIPE_SZ)
except (AttributeError, OSError):
    pipe_sz = 65536
marker = b"-- synthetic dump\\n"
padding = b"X" * (pipe_sz + 1)
tail = b"\\nCREATE TABLE t(id int);\\n"
_write_all(marker + padding + tail)
_finish(0)
"""

_GZIP = """
import os
import sys

real = os.environ["REAL_GZIP"]
args = sys.argv[1:]
if "-t" in args or "--test" in args:
    os.execv(real, [real, *args])
log = os.environ.get("GZIP_OUTPUT_LOG")
if log:
    try:
        target = os.readlink("/proc/self/fd/1")
    except OSError as exc:
        target = "unreadable:%s" % exc
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(target + "\\n")

def _exit(code):
    try:
        sys.stdout.flush()
    except (BrokenPipeError, OSError):
        pass
    try:
        sys.stderr.flush()
    except (BrokenPipeError, OSError):
        pass
    os._exit(code)

def _drain_stdin():
    while True:
        try:
            chunk = os.read(sys.stdin.fileno(), 65536)
        except OSError:
            return
        if not chunk:
            return

mode = os.environ.get("FAKE_GZIP_MODE", "ok")
if mode == "full":
    # Disk full: stop without reading. The dump writer then gets EPIPE.
    sys.stdout.buffer.write(b"partial")
    sys.stderr.write("gzip: stdout: No space left on device\\n")
    _exit(1)
if mode == "broken":
    # Exit 0 only after the dump has been consumed, as real gzip would.
    _drain_stdin()
    sys.stdout.buffer.write(b"this is not gzip data\\n")
    _exit(0)
os.execv(real, [real, *args])
"""

_SHA256SUM = """
import sys

sys.stderr.write("sha256sum: write error: No space left on device\\n")
raise SystemExit(3)
"""


def _install(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _assert_no_credentials(text: str) -> None:
    banned = (
        FIXTURE_MARK,
        SYNTHETIC_URL,
        f"{SYNTHETIC_USER}:{FIXTURE_MARK}",
        "postgresql://",
        "postgres://",
    )
    for item in banned:
        if item in text:
            raise AssertionError("backup output included a credential or connection string")


def _published_archives(backup_dir: Path) -> list[Path]:
    return sorted(
        path for path in backup_dir.iterdir() if path.is_file() and _PUBLISHED.match(path.name)
    )


def _checksums(backup_dir: Path) -> list[Path]:
    return sorted(
        path for path in backup_dir.iterdir() if path.is_file() and path.name.endswith(".sha256")
    )


def _alert(stderr: str) -> re.Match[str]:
    matches = list(_ALERT.finditer(stderr))
    if len(matches) != 1:
        raise AssertionError(f"expected one BACKUP_FAILURE line, found {len(matches)}")
    return matches[0]


def _gzip_target(log_path: Path) -> Path:
    if not log_path.is_file():
        raise AssertionError("gzip did not record the file it wrote")
    line = log_path.read_text(encoding="utf-8").splitlines()[0].strip()
    if line.startswith("unreadable:"):
        raise AssertionError("gzip could not see its output path")
    return Path(line)


def _path_without_aws(path: str) -> str:
    kept: list[str] = []
    for entry in path.split(os.pathsep):
        if not entry:
            continue
        aws = Path(entry) / "aws"
        if aws.exists() or aws.with_suffix(".exe").exists():
            continue
        kept.append(entry)
    return os.pathsep.join(kept)


def _run(
    tmp_path: Path,
    *,
    dump_mode: str = "ok",
    gzip_mode: str = "ok",
    database_url: str | None = SYNTHETIC_URL,
    fake_sha256sum: bool = False,
    s3_bucket: str | None = None,
    hide_aws: bool = False,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (tmp_path / "tmp").mkdir(exist_ok=True)
    _install(bin_dir, "pg_dump", _PG_DUMP)
    _install(bin_dir, "gzip", _GZIP)
    if fake_sha256sum:
        _install(bin_dir, "sha256sum", _SHA256SUM)
    real_gzip = shutil.which("gzip")
    if not real_gzip:
        raise AssertionError("gzip is not installed")
    gzip_log = tmp_path / "gzip-output.txt"
    inherited = os.environ.get("PATH", "")
    if hide_aws:
        inherited = _path_without_aws(inherited)
    env = {
        "PATH": str(bin_dir) + os.pathsep + inherited,
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path / "tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "BACKUP_DIR": str(backup_dir),
        "FAKE_PG_DUMP_MODE": dump_mode,
        "FAKE_GZIP_MODE": gzip_mode,
        "FAKE_PG_DUMP_STATUS_LOG": str(tmp_path / "pg-dump-status.txt"),
        "REAL_GZIP": real_gzip,
        "GZIP_OUTPUT_LOG": str(gzip_log),
    }
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    if s3_bucket is not None:
        env["BACKUP_S3_BUCKET"] = s3_bucket
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=tmp_path,
        check=False,
    )
    return proc, backup_dir, gzip_log


@pytest.mark.parametrize(
    ("dump_mode", "gzip_mode", "stage", "code", "message_part"),
    [
        ("exit42", "ok", "dump", 42, "pg_dump"),
        ("ok", "broken", "compress", 1, "integrity"),
        ("ok", "full", "compress", 1, "No space left on device"),
    ],
)
def test_failed_stage_exits_nonzero_and_publishes_nothing(
    tmp_path: Path,
    dump_mode: str,
    gzip_mode: str,
    stage: str,
    code: int,
    message_part: str,
) -> None:
    proc, backup_dir, gzip_log = _run(tmp_path, dump_mode=dump_mode, gzip_mode=gzip_mode)
    if proc.returncode != code:
        raise AssertionError(f"expected exit {code}, got {proc.returncode}")
    status_path = tmp_path / "pg-dump-status.txt"
    if not status_path.is_file():
        raise AssertionError("pg_dump stub did not record its exit status")
    writer = int(status_path.read_text(encoding="utf-8").strip())
    if dump_mode == "exit42":
        expect_writer = 42
    elif gzip_mode == "full":
        expect_writer = 128 + signal.SIGPIPE
    else:
        expect_writer = 0
    if writer != expect_writer:
        raise AssertionError(f"pg_dump stub exited {writer}, expected {expect_writer}")
    if "Backup written" in proc.stdout:
        raise AssertionError("failure printed a success line")
    if _published_archives(backup_dir) or _checksums(backup_dir):
        raise AssertionError("failure left a backup that looks successful")
    leftovers = [path.name for path in backup_dir.iterdir()]
    if leftovers:
        raise AssertionError(f"failure left {len(leftovers)} backup files behind")
    target = _gzip_target(gzip_log)
    if _PUBLISHED.match(target.name):
        raise AssertionError("gzip wrote directly to the published backup name")
    if target.exists():
        raise AssertionError("temporary backup file was left behind")
    alert = _alert(proc.stderr)
    if alert.group("stage") != stage or int(alert.group("code")) != code:
        raise AssertionError("failure alert stage or exit code did not match the failed stage")
    if message_part not in alert.group("message") or not alert.group("message").strip():
        raise AssertionError("failure alert did not include a diagnostic message")
    _assert_no_credentials(proc.stdout + proc.stderr)


def test_checksum_failure_does_not_publish(tmp_path: Path) -> None:
    proc, backup_dir, gzip_log = _run(tmp_path, fake_sha256sum=True)
    if proc.returncode != 3:
        raise AssertionError(f"expected exit 3, got {proc.returncode}")
    if _published_archives(backup_dir) or _checksums(backup_dir):
        raise AssertionError("checksum failure left a backup that looks successful")
    target = _gzip_target(gzip_log)
    if _PUBLISHED.match(target.name) or target.exists():
        raise AssertionError("checksum failure published or kept the temporary archive")
    alert = _alert(proc.stderr)
    if alert.group("stage") != "checksum" or int(alert.group("code")) != 3:
        raise AssertionError("checksum failure alert did not name the checksum stage")
    if "checksum" not in alert.group("message"):
        raise AssertionError("checksum failure alert did not include a diagnostic message")
    _assert_no_credentials(proc.stdout + proc.stderr)


def test_failure_keeps_an_existing_published_backup(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    existing = backup_dir / "trustcopilot_20000101_000000.sql.gz"
    payload = b"pre-existing-backup"
    existing.write_bytes(payload)
    proc, backup_dir, _gzip_log = _run(tmp_path, dump_mode="exit42")
    if proc.returncode == 0:
        raise AssertionError("expected a failed backup to return nonzero")
    archives = _published_archives(backup_dir)
    if archives != [existing] or existing.read_bytes() != payload:
        raise AssertionError("failure changed an existing published backup")
    _assert_no_credentials(proc.stdout + proc.stderr)


def test_success_publishes_checksum_after_temp_write(tmp_path: Path) -> None:
    proc, backup_dir, gzip_log = _run(tmp_path)
    if proc.returncode != 0:
        raise AssertionError(f"expected exit 0, got {proc.returncode}")
    archives = _published_archives(backup_dir)
    checksums = _checksums(backup_dir)
    if len(archives) != 1 or len(checksums) != 1:
        raise AssertionError("success did not publish one archive and one checksum")
    archive = archives[0]
    target = _gzip_target(gzip_log)
    if target.parent != backup_dir or _PUBLISHED.match(target.name):
        raise AssertionError("gzip wrote directly to the published backup name")
    if target.exists():
        raise AssertionError("temporary backup file was left behind")
    if "Backup written" not in proc.stdout:
        raise AssertionError("success did not report the published backup")
    if list(_ALERT.finditer(proc.stderr)):
        raise AssertionError("success emitted a failure alert")
    digest, separator, name = checksums[0].read_text(encoding="utf-8").strip().partition("  ")
    expect = hashlib.sha256(archive.read_bytes()).hexdigest()
    if separator != "  " or digest != expect or name != archive.name:
        raise AssertionError("checksum sidecar does not match the published backup")
    checked = subprocess.run(
        ["gzip", "-t", str(archive)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if checked.returncode != 0:
        raise AssertionError("published backup is not valid gzip")
    plain = subprocess.run(
        ["gzip", "-dc", str(archive)],
        capture_output=True,
        timeout=15,
        check=False,
    )
    if b"-- synthetic dump" not in plain.stdout:
        raise AssertionError("published backup did not contain the dump")
    _assert_no_credentials(proc.stdout + proc.stderr)


def test_configured_bucket_without_aws_keeps_the_local_archive(tmp_path: Path) -> None:
    proc, backup_dir, gzip_log = _run(tmp_path, s3_bucket="synthetic-bucket", hide_aws=True)
    if proc.returncode != 127:
        raise AssertionError(f"expected exit 127, got {proc.returncode}")
    if "Backup written" not in proc.stdout or "Uploaded" in proc.stdout:
        raise AssertionError("missing aws did not keep the local publish")
    archives = _published_archives(backup_dir)
    checksums = _checksums(backup_dir)
    if len(archives) != 1 or len(checksums) != 1:
        raise AssertionError("missing aws removed the verified local archive")
    target = _gzip_target(gzip_log)
    if _PUBLISHED.match(target.name) or target.exists():
        raise AssertionError("missing aws wrote the published name or left a partial")
    alert = _alert(proc.stderr)
    if alert.group("stage") != "upload" or int(alert.group("code")) != 127:
        raise AssertionError("missing aws alert did not name the upload stage")
    if alert.group("message") != "aws CLI not found for configured BACKUP_S3_BUCKET":
        raise AssertionError("missing aws alert message did not match")
    _assert_no_credentials(proc.stdout + proc.stderr)


def test_missing_database_url_fails_without_a_backup(tmp_path: Path) -> None:
    proc, backup_dir, _gzip_log = _run(tmp_path, database_url=None)
    if proc.returncode == 0:
        raise AssertionError("missing DATABASE_URL returned success")
    if _published_archives(backup_dir) or _checksums(backup_dir):
        raise AssertionError("missing DATABASE_URL left a backup that looks successful")
    if "DATABASE_URL" not in proc.stderr:
        raise AssertionError("missing DATABASE_URL did not name the missing setting")
    _assert_no_credentials(proc.stdout + proc.stderr)
