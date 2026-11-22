#!/usr/bin/env python3
"""Redact Playwright HTML/JSON reports and trace zips before CI upload.

TC-02-009. Stdlib only, so the e2e job can run it with the runner's python3.
The script rewrites text in place. It does not print file contents. Missing
directories are ignored so a job with no browser output still succeeds.

What is rewritten:
- connection URLs that embed a user and a secret
- Bearer and Basic authorization values
- Cookie and Set-Cookie header values
- unquoted password, secret, and access-key assignments

PNG and other binary files, including screenshots inside a trace zip, are
left unchanged. Release specs use synthetic fixtures; this script does not
try to guess customer prose.
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

_TEXT_SUFFIXES = {
    ".css",
    ".har",
    ".htm",
    ".html",
    ".js",
    ".json",
    ".log",
    ".md",
    ".mjs",
    ".network",
    ".svg",
    ".trace",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

_URL = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*://)([^/\s:@]+):([^/\s@]+)@")
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{4,}")
_BASIC = re.compile(r"(?i)(basic\s+)[A-Za-z0-9+/=]{4,}")
_COOKIE = re.compile(r"(?i)((?:set-cookie|cookie)\s*:\s*)([^\r\n\"']+)")
_ASSIGN = re.compile(
    r"(?i)(\b(?:password|passwd|secret|api_key|access_key|client_secret)\b\s*[=:]\s*)"
    r"([^\s\"'&,;]+)"
)


def redact_text(text: str) -> str:
    """Replace credential-shaped text and leave the surrounding document."""
    redacted = _URL.sub(r"\1redacted@", text)
    redacted = _BEARER.sub(r"\1redacted", redacted)
    redacted = _BASIC.sub(r"\1redacted", redacted)
    redacted = _COOKIE.sub(r"\1redacted", redacted)
    redacted = _ASSIGN.sub(r"\1redacted", redacted)
    return redacted


def _text_name(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return True
    lowered = name.lower()
    return lowered.endswith("trace.network") or lowered.endswith("trace.trace")


def _rewrite_zip(path: Path) -> int:
    """Return 1 when a zip member changed, else 0. Non-zip files return 0."""
    raw = path.read_bytes()
    if not raw.startswith(b"PK"):
        return 0
    changed = 0
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw), "r") as source, zipfile.ZipFile(buffer, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if _text_name(info.filename):
                updated = redact_text(data.decode("utf-8", "replace")).encode("utf-8")
                if updated != data:
                    changed = 1
                    data = updated
            entry = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = info.external_attr
            target.writestr(entry, data)
    if changed:
        path.write_bytes(buffer.getvalue())
    return changed


def redact_tree(root: Path) -> tuple[int, int]:
    """Redact one directory. Missing paths contribute nothing."""
    if not root.exists():
        return (0, 0)
    if not root.is_dir():
        raise SystemExit(f"not a directory: {root}")
    files = 0
    zips = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() == ".zip" or path.name.lower().endswith("trace.zip"):
            zips += _rewrite_zip(path)
            continue
        if not _text_name(path.name):
            continue
        original = path.read_text(encoding="utf-8", errors="replace")
        updated = redact_text(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            files += 1
    return (files, zips)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: redact-playwright-artifacts.py DIR [DIR ...]", file=sys.stderr)
        return 2
    files = 0
    zips = 0
    for raw in argv[1:]:
        changed_files, changed_zips = redact_tree(Path(raw))
        files += changed_files
        zips += changed_zips
    print(f"redacted files: {files}")
    print(f"trace zips: {zips}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
