#!/usr/bin/env python3
"""Secret inventory scanner (TC-07-001).

Scans the current source tree, reachable git history and release artifact
directories for credential-like literals and reports **locations only**
(path, line, rule, kind). It never prints, stores or returns the matched value,
a hash of it, or any surrounding source text, so its output is safe to attach
to tickets, PRs and CI logs.

Usage (from the repository root):

    python scripts/security/secret_inventory.py tree
    python scripts/security/secret_inventory.py history
    python scripts/security/secret_inventory.py paths <dir-or-file> [...]
    python scripts/security/secret_inventory.py all --json out.json

Exit status: 0 when no ``block`` finding exists, 1 when at least one ``block``
finding exists, 2 on usage error. ``review`` findings are reported but do not
fail the run; they are synthetic test/dev values or public vendor defaults that
are tracked in docs/release/tickets/TC-07-001.md.

The module is stdlib-only so it can run in any CI image.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator

# ---------------------------------------------------------------------------
# Rules. Each rule has an id, a human "kind", a severity and a compiled regex.
# Severity "block" = must never be present; "review" = inventory only.
# ---------------------------------------------------------------------------

_SECRET_NAME = (
    r"[A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|APIKEY|ACCESS_KEY|PRIVATE_KEY"
    r"|SIGNING_KEY|CLIENT_SECRET|WEBHOOK_SECRET|FERNET_KEY)[A-Z0-9_]*"
)
_LIT = r"""(?P<q>["'])(?P<val>[^"'\n]*)(?P=q)"""


@dataclass(frozen=True)
class Rule:
    rule_id: str
    kind: str
    severity: str
    pattern: re.Pattern
    # Optional predicate on the matched value (never reported).
    min_len: int = 0
    min_entropy: float = 0.0
    app_code_only: bool = False
    config_only: bool = False
    multiline: bool = False


RULES: list[Rule] = [
    Rule(
        "private-key-block",
        "PEM private key",
        "block",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"),
    ),
    Rule(
        "aws-access-key-id",
        "AWS access key id",
        "block",
        re.compile(r"\b(?P<val>(?:AKIA|ASIA)[0-9A-Z]{16})\b"),
    ),
    Rule(
        "openai-api-key",
        "OpenAI API key",
        "block",
        re.compile(r"\b(?P<val>sk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,})"),
    ),
    Rule(
        "stripe-key",
        "Stripe secret/restricted key",
        "block",
        re.compile(r"\b(?P<val>(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,})"),
    ),
    Rule(
        "stripe-webhook-secret",
        "Stripe webhook signing secret",
        "block",
        re.compile(r"\b(?P<val>whsec_[0-9A-Za-z]{16,})"),
    ),
    Rule(
        "github-token",
        "GitHub token",
        "block",
        re.compile(r"\b(?P<val>(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,}))"),
    ),
    Rule(
        "slack-token",
        "Slack token",
        "block",
        re.compile(r"\b(?P<val>xox[abposr]-[0-9]{6,}-[A-Za-z0-9\-]{10,})"),
    ),
    Rule(
        "google-api-key",
        "Google API key",
        "block",
        re.compile(r"\b(?P<val>AIza[0-9A-Za-z\-_]{35})"),
    ),
    Rule(
        "jwt",
        "JSON Web Token",
        "block",
        re.compile(
            r"\b(?P<val>eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"
        ),
    ),
    Rule(
        "signed-session-cookie",
        "Signed tc_session cookie (base64 payload + HMAC)",
        "block",
        re.compile(r"(?P<val>eyJ[A-Za-z0-9_\-=]{16,}\.[0-9a-f]{64})\b"),
    ),
    Rule(
        "hmac-literal-key",
        "HMAC computed with a literal key",
        "block",
        re.compile(r"hmac\.new\(\s*b?" + _LIT),
    ),
    # Secret-named constant / env var / mapping key assigned a high-entropy literal:
    # a real credential.
    Rule(
        "high-entropy-secret-assignment",
        "High-entropy literal assigned to a secret-named variable",
        "block",
        re.compile(
            r"(?<![A-Za-z0-9_])(?:\$env:|export\s+|environ\[[\"'])?"
            + _SECRET_NAME
            + r"[\"']?\]?\s*(?:=|:)\s*"
            + _LIT
        ),
        min_len=16,
        min_entropy=3.0,
    ),
    # Literal fallback for a secret-named setting in getenv/environ.get.
    Rule(
        "secret-env-default",
        "Literal default for a secret-named environment variable",
        "block",
        re.compile(r"(?:getenv|environ\.get)\(\s*[\"']" + _SECRET_NAME + r"[\"']\s*,\s*" + _LIT),
        min_len=1,
        multiline=True,
    ),
    # Any literal assigned to a secret-named constant in shipped application code.
    Rule(
        "app-secret-literal",
        "Literal assigned to a secret-named variable in application code",
        "block",
        re.compile(r"(?<![A-Za-z0-9_])" + _SECRET_NAME + r"\s*(?::\s*str\s*)?=\s*" + _LIT),
        min_len=1,
        app_code_only=True,
    ),
    # Credentials embedded in a URL (scheme://user:password@host).
    Rule(
        "url-embedded-credential",
        "Password embedded in a connection URL",
        "block",
        re.compile(r"[a-z][a-z0-9+.\-]*://[^:/@\s\"']+:(?P<val>[^@/\s\"']+)@"),
        min_len=12,
        min_entropy=3.0,
    ),
    Rule(
        "url-credential-review",
        "Low-entropy password embedded in a connection URL (dev default)",
        "review",
        re.compile(r"[a-z][a-z0-9+.\-]*://[^:/@\s\"']+:(?P<val>[^@/\s\"']+)@"),
        min_len=1,
    ),
    # Unquoted secret-named values in YAML / dotenv / shell / PowerShell / Docker files.
    Rule(
        "config-secret-value",
        "High-entropy secret-named value in a config/deploy file",
        "block",
        re.compile(
            r"^\s*(?:-\s*)?(?:export\s+|\$env:)?"
            + _SECRET_NAME
            + r"\s*[:=]\s*(?P<val>[^\s\"'#$<{][^\s#]*)"
        ),
        min_len=12,
        min_entropy=3.0,
        config_only=True,
    ),
    Rule(
        "config-secret-review",
        "Secret-named value in a config/deploy file (dev default)",
        "review",
        re.compile(
            r"^\s*(?:-\s*)?(?:export\s+|\$env:)?"
            + _SECRET_NAME
            + r"\s*[:=]\s*(?P<val>[^\s\"'#$<{][^\s#]*)"
        ),
        min_len=1,
        config_only=True,
    ),
    # Inventory-only: low-entropy secret-named literals in tests/scripts/compose files.
    Rule(
        "secret-literal-review",
        "Low-entropy literal for a secret-named variable (synthetic/dev default)",
        "review",
        re.compile(
            r"(?<![A-Za-z0-9_])(?:\$env:|export\s+|environ\[[\"'])?"
            + _SECRET_NAME
            + r"[\"']?\]?\s*(?:=|:)\s*"
            + _LIT
        ),
        min_len=1,
    ),
]

# Shipped application code (rules with app_code_only apply only here).
APP_CODE_PREFIXES = ("apps/api/app/", "apps/web/app/", "apps/web/components/", "apps/web/lib/")

# Placeholder values that are documentation, not credentials. Compared case-insensitively
# against the matched literal; nothing here is a real value.
_PLACEHOLDER_RE = re.compile(
    r"^(?:|x+|\*+|\.\.\.|<[^>]*>|\$\{[^}]*\}|\$[A-Z_]+|placeholder.*|your[-_ ].*"
    r"|replace[-_ ]?me.*|set[-_ ]?me.*"
    r"|changeme|example.*|redacted|dummy|test|none|null|false|true)$",
    re.IGNORECASE,
)

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".next",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".ruff_cache",
}
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".pdf",
    ".xlsx",
    ".xls",
    ".docx",
    ".doc",
    ".gz",
    ".mp4",
    ".webm",
    ".pyc",
}
SKIP_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
# The scanner and its regression test describe the patterns; they contain no values.
SELF_PATHS = {
    "scripts/security/secret_inventory.py",
    "apps/api/tests/release/test_secret_inventory.py",
}
MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class Finding:
    source: str  # "tree" | "history" | "artifact"
    path: str
    line: int
    rule: str
    kind: str
    severity: str
    commit: str = ""  # first commit (short SHA) where the blob was seen, for history findings

    def location(self) -> str:
        loc = f"{self.path}:{self.line}"
        return f"{loc}@{self.commit}" if self.commit else loc


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _is_placeholder(v: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(v.strip()))


def _looks_like_reference(v: str) -> bool:
    """Values that name something rather than being a credential.

    URLs, paths, env names, cookie names, shell interpolation and command substitution.
    """
    s = v.strip()
    if s.startswith(("http://", "https://", "/", "./", "../")):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", s):  # another env var name
        return True
    if "${" in s:  # shell/compose interpolation; its :- default line is reviewed separately
        return True
    if re.fullmatch(
        r"\$\([^()]*\)", s
    ):  # shell command substitution, e.g. "$(openssl rand -hex 24)"
        return True
    if s.startswith("[") or re.search(r"[A-Za-z_]\w*(\.\w+|::\w+)*\(", s):  # expression / call
        return True
    return False


CONFIG_SUFFIXES = {
    ".yml",
    ".yaml",
    ".env",
    ".sh",
    ".ps1",
    ".toml",
    ".ini",
    ".conf",
    ".cfg",
    ".properties",
}


def _is_config(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        Path(name).suffix.lower() in CONFIG_SUFFIXES
        or name.startswith(".env")
        or name.startswith(("Dockerfile", "Caddyfile"))
        or name.endswith(".env")
    )


def _value_ok(rule: Rule, val: str | None) -> bool:
    if val is None:
        return True
    if len(val) < rule.min_len:
        return False
    if rule.min_len and (_is_placeholder(val) or _looks_like_reference(val)):
        return False
    if rule.min_entropy and _entropy(val) < rule.min_entropy:
        return False
    return True


def scan_text(text: str, path: str, source: str = "tree", commit: str = "") -> list[Finding]:
    findings: list[Finding] = []
    norm = path.replace("\\", "/")
    is_app = norm.startswith(APP_CODE_PREFIXES)
    is_cfg = _is_config(norm)
    seen: set[tuple[int, str]] = set()
    for rule in RULES:
        if (
            not rule.multiline
            or (rule.app_code_only and not is_app)
            or (rule.config_only and not is_cfg)
        ):
            continue
        for m in rule.pattern.finditer(text):
            if not _value_ok(rule, m.groupdict().get("val")):
                continue
            lineno = text.count("\n", 0, m.start()) + 1
            if (lineno, rule.rule_id) not in seen:
                seen.add((lineno, rule.rule_id))
                findings.append(
                    Finding(source, norm, lineno, rule.rule_id, rule.kind, rule.severity, commit)
                )
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 5000:  # minified bundles: only check token formats
            candidates = [
                r
                for r in RULES
                if r.rule_id
                in {
                    "private-key-block",
                    "aws-access-key-id",
                    "openai-api-key",
                    "stripe-key",
                    "stripe-webhook-secret",
                    "github-token",
                    "slack-token",
                    "google-api-key",
                    "jwt",
                    "signed-session-cookie",
                }
            ]
        else:
            candidates = RULES
        for rule in candidates:
            if (
                rule.multiline
                or (rule.app_code_only and not is_app)
                or (rule.config_only and not is_cfg)
            ):
                continue
            for m in rule.pattern.finditer(line):
                if not _value_ok(rule, m.groupdict().get("val")):
                    continue
                key = (lineno, rule.rule_id)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(source, norm, lineno, rule.rule_id, rule.kind, rule.severity, commit)
                )
    # A block finding supersedes a review finding on the same line.
    blocked = {f.line for f in findings if f.severity == "block"}
    return [f for f in findings if not (f.severity == "review" and f.line in blocked)]


def _should_skip(rel: str) -> bool:
    p = Path(rel)
    if any(part in SKIP_DIRS for part in p.parts):
        return True
    if p.suffix.lower() in SKIP_SUFFIXES or p.name in SKIP_FILES:
        return True
    return rel.replace("\\", "/") in SELF_PATHS


def _decode(data: bytes) -> str | None:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    if b"\x00" in data[:4096]:
        return None
    return data.decode("utf-8", "replace")


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return _decode(data)


ARCHIVE_SUFFIXES = {".zip", ".trace"}
MAX_ARCHIVE_BYTES = 50_000_000


def _scan_archive(data: bytes, rel: str, source: str, commit: str = "") -> list[Finding]:
    """Scan text members of a zip archive (e.g. Playwright trace.zip) without extracting to disk."""
    import io
    import zipfile

    out: list[Finding] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return out
    with zf:
        for info in zf.infolist():
            if info.is_dir() or info.file_size > MAX_ARCHIVE_BYTES:
                continue
            member = zf.read(info)
            if info.filename.lower().endswith((".zip",)):
                out.extend(_scan_archive(member, f"{rel}!{info.filename}", source, commit))
                continue
            text = _decode(member)
            if text is not None:
                out.extend(scan_text(text, f"{rel}!{info.filename}", source, commit))
    return out


def _scan_file(path: Path, rel: str, source: str) -> list[Finding]:
    if Path(rel).suffix.lower() in ARCHIVE_SUFFIXES:
        try:
            if path.stat().st_size > MAX_ARCHIVE_BYTES:
                return []
            return _scan_archive(path.read_bytes(), rel, source)
        except OSError:
            return []
    text = _read(path)
    return scan_text(text, rel, source) if text is not None else []


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)


def iter_tree_files(root: Path) -> Iterator[str]:
    res = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if res.returncode == 0:
        for rel in res.stdout.decode("utf-8", "replace").split("\0"):
            if rel:
                yield rel
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            yield str(Path(dirpath, fn).relative_to(root))


def scan_tree(root: Path) -> list[Finding]:
    out: list[Finding] = []
    for rel in iter_tree_files(root):
        if _should_skip(rel):
            continue
        out.extend(_scan_file(root / rel, rel, "tree"))
    return out


def scan_paths(root: Path, paths: Iterable[str]) -> list[Finding]:
    out: list[Finding] = []
    for p in paths:
        base = (root / p) if not Path(p).is_absolute() else Path(p)
        files = (
            [base]
            if base.is_file()
            else [
                Path(d, f)
                for d, ds, fs in os.walk(base)
                for f in fs
                if not (set(Path(d).parts) & SKIP_DIRS)
            ]
        )
        for f in files:
            try:
                rel = str(f.relative_to(root))
            except ValueError:
                rel = str(f)
            if _should_skip(rel):
                continue
            out.extend(_scan_file(f, rel, "artifact"))
    return out


def scan_history(root: Path) -> list[Finding]:
    """Scan every blob reachable from any ref once.

    Each blob is attributed to the first commit that added it.
    """
    res = _git(
        root, "log", "--all", "--reverse", "--format=%h", "--raw", "--no-renames", "--no-abbrev"
    )
    if res.returncode != 0:
        raise RuntimeError("git history is not available")
    blobs: dict[str, tuple[str, str]] = {}
    commit = ""
    for raw in res.stdout.decode("utf-8", "replace").splitlines():
        if not raw:
            continue
        if not raw.startswith(":"):
            commit = raw.strip()
            continue
        meta, _, path = raw.partition("\t")
        parts = meta.split()
        if len(parts) < 5 or parts[4] == "D":
            continue
        sha = parts[3]
        if sha not in blobs and not _should_skip(path):
            blobs[sha] = (path, commit)
    out: list[Finding] = []
    if not blobs:
        return out
    proc = subprocess.Popen(
        ["git", "-C", str(root), "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert proc.stdin and proc.stdout
    for sha, (path, c) in blobs.items():
        proc.stdin.write(f"{sha}\n".encode())
        proc.stdin.flush()
        header = proc.stdout.readline().split()
        if len(header) < 3 or header[1] != b"blob":
            continue
        size = int(header[2])
        data = proc.stdout.read(size)
        proc.stdout.read(1)
        if Path(path).suffix.lower() in ARCHIVE_SUFFIXES:
            out.extend(_scan_archive(data, path, "history", c))
            continue
        if size > MAX_BYTES:
            continue
        text = _decode(data)
        if text is not None:
            out.extend(scan_text(text, path, "history", c))
    proc.stdin.close()
    proc.wait()
    return out


DEFAULT_ARTIFACT_DIRS = ("artifacts", "apps/web/playwright-report", "apps/web/test-results")


def summarize(findings: list[Finding]) -> dict:
    by: dict[str, int] = {}
    for f in findings:
        k = f"{f.source}:{f.severity}"
        by[k] = by.get(k, 0) + 1
    return {
        "total": len(findings),
        "by_source_severity": by,
        "block": sum(1 for f in findings if f.severity == "block"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", choices=["tree", "history", "paths", "all"])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--fail-on", choices=["block", "never"], default="block")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    findings: list[Finding] = []
    if args.mode in ("tree", "all"):
        findings += scan_tree(root)
    if args.mode in ("history", "all"):
        findings += scan_history(root)
    if args.mode == "paths":
        if not args.paths:
            ap.error("paths mode needs at least one path")
        findings += scan_paths(root, args.paths)
    if args.mode == "all":
        findings += scan_paths(root, [d for d in DEFAULT_ARTIFACT_DIRS if (root / d).exists()])
    for f in sorted(findings, key=lambda x: (x.source, x.severity, x.path, x.line)):
        print(f"{f.severity.upper():6} {f.source:8} {f.location()}  {f.rule}  ({f.kind})")
    summary = summarize(findings)
    print(json.dumps(summary, sort_keys=True))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {"summary": summary, "findings": [asdict(f) for f in findings]},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    if args.fail_on == "block" and summary["block"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
