"""TC-07-001 release gate: exposed signing literals, cookies and traces stay contained.

Every "secret" used here is generated at runtime; this file must never contain a real or
realistic credential literal. It is scanned like every other file (TC-07-001a); the only allowance
is that a block match whose value is a bare f-string placeholder such as "{tok}" is downgraded to
review, so a real value added here still blocks.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import importlib.util
import io
import json
import secrets
import string
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCANNER_PATH = REPO_ROOT / "scripts" / "security" / "secret_inventory.py"


def _load_scanner():
    spec = importlib.util.spec_from_file_location("tc_secret_inventory", SCANNER_PATH)
    assert spec and spec.loader, f"scanner missing at {SCANNER_PATH}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def scanner():
    return _load_scanner()


def _git_available() -> bool:
    try:
        return (
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", "--git-dir"],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
    except FileNotFoundError:
        return False


def _blocks(findings):
    return [f for f in findings if f.severity == "block"]


# ---------------------------------------------------------------------------
# AC: the working tree contains no blocking secret literals (regression gate)
# ---------------------------------------------------------------------------


def test_tree_has_no_blocking_secret_literals(scanner):
    findings = scanner.scan_tree(REPO_ROOT)
    blocks = _blocks(findings)
    # Location-only message: never echo values.
    assert not blocks, "secret literals reintroduced:\n" + "\n".join(
        f"{f.location()} {f.rule} ({f.kind})" for f in blocks
    )


def test_scanner_cli_exit_code_is_zero_on_tree(tmp_path):
    out = tmp_path / "tree.json"
    proc = subprocess.run(
        [sys.executable, str(SCANNER_PATH), "tree", "--root", str(REPO_ROOT), "--json", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:]
    data = json.loads(out.read_text())
    assert data["summary"]["block"] == 0
    # Report contains locations and rule names only, never a value field.
    for f in data["findings"]:
        assert set(f) <= {
            "source",
            "path",
            "line",
            "rule",
            "kind",
            "severity",
            "commit",
            "reason",
        }


# ---------------------------------------------------------------------------
# Scanner detects each class of exposure (synthetic, runtime-generated values)
# ---------------------------------------------------------------------------


def _fake_session_cookie() -> str:
    key = secrets.token_bytes(32)
    payload = base64.urlsafe_b64encode(json.dumps({"uid": 1, "ws": 1}).encode()).decode()
    sig = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _cases() -> list[tuple[str, str, str]]:
    tok = secrets.token_urlsafe(48)
    pw = secrets.token_urlsafe(24)
    pem = (
        "-----BEGIN "
        + "RSA PRIVATE KEY-----\n"
        + base64.b64encode(secrets.token_bytes(48)).decode()
        + "\n"
    )
    return [
        ("signing literal in a test script", "apps/api/tests/x_live.py", f'SECRET = "{tok}"\n'),
        (
            "hmac with literal key",
            "apps/api/tests/x_live2.py",
            f'sig = hmac.new(b"{tok}", payload, hashlib.sha256)\n',
        ),
        (
            "cookie jar line",
            ".curl_cookies.txt",
            f"localhost\tFALSE\t/\tFALSE\t0\ttc_session\t{_fake_session_cookie()}\n",
        ),
        ("env default", "apps/api/app/core/x.py", f'S = os.getenv("SESSION_SECRET", "{tok}")\n'),
        (
            "compose inline DB password",
            "docker-compose.prod.yml",
            f"      DATABASE_URL: postgresql://tc:{pw}@postgres:5432/tc\n",
        ),
        ("compose secret value", "docker-compose.prod.yml", f"      POSTGRES_PASSWORD: {pw}\n"),
        ("pem private key", "deploy/key.pem", pem),
    ]


@pytest.mark.parametrize("label,path,text", _cases(), ids=[c[0] for c in _cases()])
def test_scanner_blocks_synthetic_exposures(scanner, label, path, text):
    findings = scanner.scan_text(text, path)
    assert _blocks(findings), f"scanner missed: {label}"


def test_scanner_scans_trace_archives_in_memory(scanner):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z2:
            z2.writestr(
                "0-trace.network",
                json.dumps(
                    {
                        "headers": [
                            {"name": "Cookie", "value": "tc_session=" + _fake_session_cookie()}
                        ]
                    }
                ),
            )
        zf.writestr("data/trace.zip", inner.getvalue())
    findings = scanner._scan_archive(
        buf.getvalue(), "apps/web/test-results/x/trace.zip", "artifact"
    )
    assert _blocks(findings)


def test_scanner_ignores_references_and_placeholders(scanner):
    py_safe = (
        "\n".join(
            [
                'SESSION_SECRET = os.environ["SESSION_SECRET"]',
                'session_secret: str = os.getenv("SESSION_SECRET", "")',
                "secret = secrets.token_urlsafe(48)",
            ]
        )
        + "\n"
    )
    cfg_safe = (
        "\n".join(
            [
                "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?must be set}",
                "SESSION_SECRET=<generate-me>",
                "SESSION_SECRET=",
                "$env:SESSION_SECRET = [Convert]::ToBase64String($bytes)",
                'PG_PASSWORD="$(openssl rand -hex 24)"',
            ]
        )
        + "\n"
    )
    assert not _blocks(scanner.scan_text(py_safe, "apps/api/app/core/example.py"))
    assert not _blocks(scanner.scan_text(cfg_safe, "docker-compose.prod.yml"))
    assert not _blocks(scanner.scan_text(cfg_safe, "scripts/example.ps1"))
    assert not _blocks(scanner.scan_text(cfg_safe, ".github/workflows/ci.yml"))
    # A real literal next to the substitution is still blocked.
    leak = 'PG_PASSWORD="' + secrets.token_urlsafe(32) + '"\n'
    assert _blocks(scanner.scan_text(leak, ".github/workflows/ci.yml"))


def test_reserved_hosts_and_synthetic_pragma_are_review_only(scanner):
    pw = secrets.token_urlsafe(24)
    # RFC 2606/6761 reserved hosts can never be a real system: review, not block.
    for host in ("db.internal.example", "db.production.invalid", "pg.example.com", "x.test"):
        fake = f'DSN = "postgresql://svc:{pw}@{host}:5432/prod"\n'
        found = scanner.scan_text(fake, "apps/api/tests/test_x.py")
        assert not _blocks(found) and found, host
    # The same credential for a real-looking host still blocks.
    assert _blocks(scanner.scan_text(f"postgresql://svc:{pw}@db.acme.io:5432/p\n", "notes.md"))

    marked = f'DSN = "postgresql://svc:{pw}@db.acme.io:5432/p"  # secret-inventory: synthetic\n'
    found = scanner.scan_text(marked, "apps/api/tests/release/test_x.py")
    assert found and not _blocks(found), "pragma downgrades a test URL credential to review"
    # The pragma is ignored in application code, config/deploy files and non-test paths.
    for path in ("apps/api/app/core/x.py", "docker-compose.prod.yml", "scripts/x.py"):
        assert _blocks(scanner.scan_text(marked, path)), path
    # It only covers its own line.
    two = marked + f'OTHER = "postgresql://svc:{pw}@db.acme.io/p"\n'
    assert _blocks(scanner.scan_text(two, "apps/api/tests/release/test_x.py"))


# ---------------------------------------------------------------------------
# Coordinator conditions on the reserved-host / synthetic-marker relaxation (7e976c5)
# ---------------------------------------------------------------------------

_RESERVED_OK = [
    "invalid",
    "db.invalid",
    "a.b.example",
    "x.test",
    "localhost",
    "api.localhost",
    "example.com",
    "db.example.com",
    "EXAMPLE.NET",
    "pg.example.org",
]
_LOOKALIKE_HOSTS = [
    "example.com.evil.io",
    "notexample.com",
    "test.attacker.com",
    "example.attacker.com",
    "localhost.evil.io",
    "invalid.co",
    "myexample.org",
    "example.co",
    "example.comx",
    "testing",
    "db.acme.io",
]


@pytest.mark.parametrize("host", _RESERVED_OK)
def test_condition_a_reserved_parsed_host_is_review(scanner, host):
    pw = secrets.token_urlsafe(24)
    found = scanner.scan_text(f'DSN = "postgresql://svc:{pw}@{host}:5432/db"\n', "notes.md")
    assert found and not _blocks(found), host
    assert any(
        f.rule == "url-embedded-credential"
        and f.severity == "review"
        and f.reason == scanner.REASON_RESERVED_HOST
        for f in found
    ), host


@pytest.mark.parametrize("host", _LOOKALIKE_HOSTS)
def test_condition_a_lookalike_hosts_still_block(scanner, host):
    pw = secrets.token_urlsafe(24)
    for path in ("notes.md", "apps/api/tests/test_x.py"):
        found = scanner.scan_text(f'DSN = "postgresql://svc:{pw}@{host}:5432/db"\n', path)
        assert any(f.rule == "url-embedded-credential" for f in _blocks(found)), (host, path)


@pytest.mark.parametrize(
    "template",
    [
        # 'example.com' only in the userinfo: the parsed host is the real one.
        "postgresql://example.com:{pw}@db.acme.io:5432/db",
        # 'example.com' only in the path, query or fragment.
        "postgresql://svc:{pw}@db.acme.io:5432/example.com",
        "https://svc:{pw}@db.acme.io/x?next=https://example.com/",
        "https://svc:{pw}@db.acme.io/#example.com",
        # A second '@': urllib.parse takes the last one, so the host is evil.io.
        "https://svc:{pw}@example.com@evil.io/",
        "https://svc:{pw}@db.example.com.evil.io:443/",
    ],
)
def test_condition_a_reserved_name_outside_the_parsed_host_still_blocks(scanner, template):
    url = template.format(pw=secrets.token_urlsafe(24))
    found = scanner.scan_text(f'DSN = "{url}"\n', "notes.md")
    assert any(f.rule == "url-embedded-credential" for f in _blocks(found)), template


def test_condition_a_host_check_uses_urllib_parse(scanner):
    assert scanner._url_host_is_reserved("postgresql://u:p@db.example.com:5432/x")
    assert not scanner._url_host_is_reserved("postgresql://u:p@example.com.evil.io/x")
    assert not scanner._url_host_is_reserved("postgresql://example.com:p@evil.io/x")
    assert not scanner._url_host_is_reserved("https://u:p@[::1/")  # unparsable: fail closed
    assert not hasattr(scanner, "_RESERVED_HOST_RE"), "no substring/regex host matching"


_MARKER = "  # secret-inventory: synthetic"


def _marked_line() -> str:
    """A real-host URL credential carrying the marker as a genuine Python comment."""
    return f'DSN = "postgresql://svc:{secrets.token_urlsafe(24)}@db.acme.io:5432/x"{_MARKER}\n'


@pytest.mark.parametrize(
    "path",
    [
        "apps/api/tests/release/test_x.py",
        "apps/api/tests/test_x.py",
        "tests/x.py",
        "apps/web/e2e/helpers.py",
        "apps/web/__tests__/x_test.py",
        "apps/api/tests/fixtures/sample.py",
        "fixtures/x.py",
    ],
)
def test_condition_b_marker_honored_in_test_e2e_fixture_paths(scanner, path):
    found = scanner.scan_text(_marked_line(), path)
    assert found and not _blocks(found), path


@pytest.mark.parametrize(
    "path",
    [
        # application code
        "apps/api/app/core/x.py",
        "apps/api/app/tests/x.py",
        "apps/web/app/login/page.tsx",
        "apps/web/lib/x.ts",
        "apps/web/contexts/AuthContext.tsx",
        "apps/web/middleware.ts",
        "apps/api/alembic/versions/076_x.py",
        "apps/api/alembic/tests/x.py",
        # '#' is not a comment in these languages: only Python comment tokens count
        "apps/web/e2e/login.spec.ts",
        "apps/web/__tests__/x.test.ts",
        "tests/x.rb",
        "tests/notes.md",
        # never honoured for these file types, even under a test directory
        "tests/main.tf",
        "tests/prod.tfvars",
        "tests/Makefile",
        "tests/GNUmakefile",
        "tests/run.sh",
        "tests/run.bash",
        "tests/run.zsh",
        "tests/seed.sql",
        "tests/.env",
        "tests/.env.test",
        "tests/x.env.py",
        "tests/prod.env",
        # archive members
        "tests/trace.zip!0-trace.py",
        "apps/web/test-results/x/trace.zip!data/test_x.py",
        # look-alike names: path components, not substrings
        "apps/api/app/tests_helper.py",
        "app/attest/x.py",
        "apps/api/latest/x.py",
        "apps/api/tests_helper.py",
        "apps/api/contests/x.py",
        "apps/api/e2e_tools/x.py",
        "apps/api/fixtures_loader.py",
        "scripts/x.py",
        "apps/api/test_x.py",
        # config
        ".env.example",
        "apps/api/.env.example",
        "apps/api/tests/.env.example",
        "config.yml",
        "apps/api/tests/settings.yml",
        "apps/web/next.config.js",
        "apps/web/next.config.mjs",
        "apps/web/e2e/playwright.config.ts",
        "apps/web/tests/fixture.json",
        # deploy / CI
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "tests/docker-compose.test.yml",
        "deploy/run.py",
        "deploy/tests/x.py",
        "infra/tests/x.py",
        "infra/main.tf",
        ".github/workflows/ci.yml",
        ".github/workflows/tests/x.py",
        "tests/Dockerfile",
    ],
)
def test_condition_b_marker_ignored_outside_test_paths(scanner, path):
    found = scanner.scan_text(_marked_line(), path)
    assert _blocks(found), path
    assert not any(f.reason == scanner.REASON_SYNTHETIC for f in found), path


def test_condition_b_marker_in_config_value_still_blocks(scanner):
    pw = secrets.token_urlsafe(24)
    yml = f"      POSTGRES_PASSWORD: {pw}{_MARKER}\n"
    for path in ("docker-compose.yml", ".github/workflows/ci.yml", "deploy/values.yml"):
        assert _blocks(scanner.scan_text(yml, path)), path
    env = f"SESSION_SECRET={pw}{_MARKER}\n"
    assert _blocks(scanner.scan_text(env, ".env.example"))
    js = f'const SESSION_SECRET = "{pw}"; // secret-inventory: synthetic\n'
    assert _blocks(scanner.scan_text(js, "apps/web/next.config.js"))


def _downgrade_fixture(tmp_path):
    pw = secrets.token_urlsafe(24)
    tok = secrets.token_urlsafe(24)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_fake.py").write_text(
        f'URL = "postgresql://svc:{tok}@db.acme.io:5432/x"{_MARKER}\n'
        f'DSN = "postgresql://svc:{pw}@db.example.com:5432/x"\n'
    )
    return pw, tok


def test_condition_c_downgrades_reported_as_review_in_json(scanner, tmp_path, capsys):
    pw, tok = _downgrade_fixture(tmp_path)
    out = tmp_path / "o.json"
    rc = scanner.main(["paths", "tests", "--root", str(tmp_path), "--json", str(out)])
    assert rc == 0
    raw = out.read_text()
    assert pw not in raw and tok not in raw
    data = json.loads(raw)
    reasons = {
        (f["rule"], f["line"], f["severity"], f["reason"]) for f in data["findings"] if f["reason"]
    }
    assert ("url-embedded-credential", 1, "review", scanner.REASON_SYNTHETIC) in reasons
    assert ("url-embedded-credential", 2, "review", scanner.REASON_RESERVED_HOST) in reasons
    assert "synthetic" in scanner.REASON_SYNTHETIC and "downgraded" in scanner.REASON_SYNTHETIC
    assert "reserved-host" in scanner.REASON_RESERVED_HOST
    assert data["summary"]["block"] == 0 and data["summary"]["downgraded"] == 2


def test_condition_c_downgrades_reported_as_review_in_text(scanner, tmp_path, capsys):
    pw, tok = _downgrade_fixture(tmp_path)
    rc = scanner.main(["paths", "tests", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert pw not in out and tok not in out
    lines = out.splitlines()
    syn = [ln for ln in lines if "test_fake.py:1" in ln and "url-embedded-credential" in ln]
    host = [ln for ln in lines if "test_fake.py:2" in ln and "url-embedded-credential" in ln]
    assert syn and syn[0].startswith("REVIEW") and scanner.REASON_SYNTHETIC in syn[0]
    assert host and host[0].startswith("REVIEW") and scanner.REASON_RESERVED_HOST in host[0]


def test_condition_c_downgrade_kept_next_to_a_block_on_the_same_line(scanner):
    pw = secrets.token_urlsafe(24)
    tok = secrets.token_urlsafe(32)
    line = f'DSN = "postgresql://svc:{pw}@db.example.com/x"; TOKEN = "{tok}"\n'
    found = scanner.scan_text(line, "notes.md")
    assert _blocks(found)
    assert any(f.reason == scanner.REASON_RESERVED_HOST and f.severity == "review" for f in found)


# ---------------------------------------------------------------------------
# Coordinator review of e8321b5 (CHANGES REQUIRED): BLOCKING 2/3 and marker scope
# ---------------------------------------------------------------------------


def test_review_dedupe_downgraded_url_cannot_hide_a_blocking_url_on_the_same_line(scanner):
    pw1, pw2 = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    line = f"a=postgresql://svc:{pw1}@db.example.com/x b=postgresql://svc:{pw2}@db.acme.io/x\n"
    for path in ("notes.md", "apps/api/tests/test_x.py", "docker-compose.yml"):
        found = scanner.scan_text(line, path)
        url = [f for f in found if f.rule == "url-embedded-credential"]
        assert any(f.severity == "block" for f in url), path
        assert any(f.reason == scanner.REASON_RESERVED_HOST for f in url), path
    # Order does not matter either.
    swapped = f"b=postgresql://svc:{pw2}@db.acme.io/x a=postgresql://svc:{pw1}@db.example.com/x\n"
    assert any(
        f.rule == "url-embedded-credential" for f in _blocks(scanner.scan_text(swapped, "n.md"))
    )


def test_review_dedupe_marker_cannot_hide_a_second_real_url_on_the_line(scanner):
    pw1, pw2 = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    line = (
        f'X = ("postgresql://svc:{pw1}@db.example.com/x", "postgresql://svc:{pw2}@db.acme.io/x")\n'
    )
    found = scanner.scan_text(line, "apps/api/tests/test_x.py")
    assert any(f.rule == "url-embedded-credential" for f in _blocks(found))


@pytest.mark.parametrize(
    "template",
    [
        # more than one '@' in the authority, in each order
        "postgresql://svc:{pw}@db.acme.io@db.example.com/x",
        "postgresql://svc:{pw}@db.example.com@db.acme.io/x",
        "postgresql://svc@db.acme.io:{pw}@db.example.com/x",
        "postgresql://svc:{pw}@@db.example.com/x",
        # the ':port@' form
        "postgresql://svc:{pw}@db.acme.io:5432@db.example.com/x",
        "postgresql://svc:{pw}@db.acme.io:@db.example.com/x",
        # backslash in the authority
        "postgresql://svc:{pw}@db.acme.io\\@db.example.com/x",
        "postgresql://svc:{pw}@db.acme.io\\.example.com/x",
        "https://svc:{pw}@db.example.com\\x.acme.io/",
        # host text after the matched '@' that is not a plain DNS name
        "postgresql://svc:{pw}@db.acme.io%40x.example.com/x",
        "postgresql://svc:{pw}@[db.example.com]/x",
    ],
)
def test_review_ambiguous_authority_always_blocks(scanner, template):
    url = template.format(pw=secrets.token_urlsafe(24))
    for path in ("notes.md", "apps/api/tests/test_x.py"):
        for text in (f'DSN = "{url}"\n', f"{url}\n", f"DSN = '{url}'\n"):
            found = scanner.scan_text(text, path)
            assert any(f.rule == "url-embedded-credential" for f in _blocks(found)), (
                template,
                path,
            )
            assert not any(f.reason == scanner.REASON_RESERVED_HOST for f in found), template


def test_review_reserved_host_must_match_text_after_the_at_and_urlsplit(scanner):
    pw = secrets.token_urlsafe(24)
    ok = f"postgresql://svc:{pw}@db.example.com:5432/x"
    m = scanner._URL_CRED_RE.search(ok)
    assert m and scanner._url_credential_host_is_reserved(ok, m)
    bad = f"postgresql://svc:{pw}@db.acme.io@db.example.com/x"
    m = scanner._URL_CRED_RE.search(bad)
    assert m and not scanner._url_credential_host_is_reserved(bad, m)


@pytest.mark.parametrize("scheme", ["POSTGRESQL", "Postgres", "HTTPS", "Redis", "AMQP", "MySQL"])
def test_review_uppercase_schemes_detected(scanner, scheme):
    pw = secrets.token_urlsafe(24)
    found = scanner.scan_text(f'DSN = "{scheme}://svc:{pw}@db.acme.io:5432/x"\n', "notes.md")
    assert any(f.rule == "url-embedded-credential" for f in _blocks(found)), scheme
    low = scanner.scan_text(f"{scheme}://svc:postgres@db.acme.io/x\n", "notes.md")
    assert any(f.rule == "url-credential-review" for f in low), scheme
    reserved = scanner.scan_text(f"{scheme}://svc:{pw}@DB.EXAMPLE.COM/x\n", "notes.md")
    assert not _blocks(reserved), scheme


@pytest.mark.parametrize(
    "path",
    [
        "apps/web/contexts/AuthContext.tsx",
        "apps/web/middleware.ts",
        "apps/api/alembic/versions/076_x.py",
        "apps/api/alembic/env.py",
    ],
)
def test_review_new_app_code_paths(scanner, path):
    assert path.startswith(scanner.APP_CODE_PREFIXES)
    # app-secret-literal: any literal (even low entropy) assigned to a secret-named constant.
    found = scanner.scan_text('SESSION_SECRET = "dev"\n', path)
    assert any(f.rule == "app-secret-literal" for f in _blocks(found)), path
    found = scanner.scan_text(_marked_line(), path)
    assert _blocks(found) and not any(f.reason == scanner.REASON_SYNTHETIC for f in found), path


def _key_shaped_lines() -> dict[str, str]:
    """Synthetic, runtime-generated token-format values for each non-URL block rule."""
    up = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    aws = "AKIA" + "".join(secrets.choice(up) for _ in range(16))
    # Bound to a short name so the f-string source never looks like a literal
    # assignment to test_safe_collection's checked-in-credential guard.
    sess = secrets.token_urlsafe(32)
    return {
        "aws-access-key-id": f'AWS = "{aws}"',
        "openai-api-key": f'OPENAI = "sk-{secrets.token_urlsafe(40)}"',
        "stripe-key": f'STRIPE = "sk_live_{secrets.token_hex(16)}"',
        "github-token": f'GH = "ghp_{secrets.token_hex(20)}"',
        "high-entropy-secret-assignment": f'SESSION_SECRET = "{sess}"',
        "private-key-block": '"-----BEGIN ' + 'PRIVATE KEY-----"',
    }


@pytest.mark.parametrize("rule_id", sorted(_key_shaped_lines()))
def test_review_marker_never_downgrades_non_url_rules(scanner, rule_id):
    line = _key_shaped_lines()[rule_id] + _MARKER + "\n"
    for path in ("apps/api/tests/test_x.py", "tests/fixtures/x.py", "apps/web/e2e/x.py"):
        found = scanner.scan_text(line, path)
        assert any(f.rule == rule_id for f in _blocks(found)), (rule_id, path)
        assert not any(f.reason == scanner.REASON_SYNTHETIC for f in found), (rule_id, path)
    assert scanner.MARKER_RULES == frozenset({"url-embedded-credential"})


@pytest.mark.parametrize(
    "fmt",
    [
        # marker text inside a string literal on the same line
        'DSN = "{url}"; NOTE = "{m}"\n',
        "DSN = '{url}  # {m}'\n",
        'DSN = f"{url}  # {m}"\n',
        # inside a triple-quoted string spanning lines
        'DOC = """\n{url}  # {m}\n"""\n',
        # '#' inside a string, marker outside any comment
        'DSN = "{url}" + "#" + "{m}"\n',
        # not a comment at the start
        'DSN = "{url}"  # note: {m}\n',
    ],
)
def test_review_marker_counts_only_as_a_real_comment(scanner, fmt):
    url = f"postgresql://svc:{secrets.token_urlsafe(24)}@db.acme.io:5432/x"
    text = fmt.format(url=url, m="secret-inventory: synthetic")
    found = scanner.scan_text(text, "apps/api/tests/test_x.py")
    assert any(f.rule == "url-embedded-credential" for f in _blocks(found)), fmt
    assert not any(f.reason == scanner.REASON_SYNTHETIC for f in found), fmt


def test_review_marker_in_untokenizable_text_fails_closed(scanner):
    url = f"postgresql://svc:{secrets.token_urlsafe(24)}@db.acme.io:5432/x"
    text = f'DSN = "{url}"{_MARKER}\nbroken = (\n'
    found = scanner.scan_text(text, "apps/api/tests/test_x.py")
    assert any(f.rule == "url-embedded-credential" for f in _blocks(found))


def test_review_marker_on_real_comment_still_downgrades_url_only(scanner):
    found = scanner.scan_text(_marked_line(), "apps/api/tests/test_x.py")
    assert found and not _blocks(found)
    assert any(
        f.rule == "url-embedded-credential" and f.reason == scanner.REASON_SYNTHETIC for f in found
    )


def test_scanner_output_never_contains_values(scanner, capsys, tmp_path):
    tok = secrets.token_urlsafe(48)
    (tmp_path / "leak.py").write_text(f'API_TOKEN = "{tok}"\n')
    rc = scanner.main(
        ["paths", "leak.py", "--root", str(tmp_path), "--json", str(tmp_path / "o.json")]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert tok not in out
    assert tok not in (tmp_path / "o.json").read_text()


# ---------------------------------------------------------------------------
# Cookie jars, Playwright reports and traces are removed and ignored
# ---------------------------------------------------------------------------

REMOVED_ARTIFACTS = [
    ".curl_cookies.txt",
    ".tmp_cookies.txt",
    ".tmp_test_cookies.txt",
    "apps/web/playwright-report",
    "apps/web/test-results",
]
IGNORED_SAMPLES = [
    ".curl_cookies.txt",
    "cookies.txt",
    "x_cookies_y.txt",
    ".tmp_anything.json",
    "apps/web/playwright-report/index.html",
    "apps/web/test-results/a/trace.zip",
    "apps/web/blob-report/report.zip",
    "session.har",
    "apps/api/.seed-credentials.local",
]


@pytest.mark.skipif(not _git_available(), reason="git metadata not available")
def test_cookie_jars_and_traces_not_tracked():
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    bad = [
        p
        for p in tracked
        if any(p == a or p.startswith(a + "/") for a in REMOVED_ARTIFACTS)
        or p.endswith((".har", "trace.zip"))
        or "cookies" in Path(p).name.lower()
        and p.endswith(".txt")
    ]
    assert not bad, f"tracked cookie/trace artifacts: {bad}"


@pytest.mark.skipif(not _git_available(), reason="git metadata not available")
@pytest.mark.parametrize("path", IGNORED_SAMPLES)
def test_sensitive_artifacts_are_gitignored(path):
    rc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--no-index", path],
        capture_output=True,
        check=False,
    ).returncode
    assert rc == 0, f"{path} is not gitignored"


# ---------------------------------------------------------------------------
# Signing secret: no literal fallback; production refuses weak secrets
# ---------------------------------------------------------------------------


def test_no_dev_secret_literal_in_session_module():
    import app.core.session as session_mod

    assert not hasattr(session_mod, "_DEV_SECRET")
    src = Path(session_mod.__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and len(node.value.value) >= 16
        ):
            names = [getattr(t, "id", "") for t in node.targets]
            assert not any(
                "SECRET" in n.upper() for n in names
            ), f"literal secret at line {node.lineno}"


def test_config_has_no_secret_defaults(monkeypatch):
    from app.core.config import Settings

    for var in ("SESSION_SECRET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    for name in ("session_secret", "s3_access_key", "s3_secret_key"):
        assert getattr(s, name) in ("", None), f"{name} has a non-empty default"


@pytest.mark.parametrize(
    "value", ["", "placeholder", "test-secret", "changeme", "a" * 64, "short-but-random-9f"]
)
def test_production_rejects_weak_session_secret(monkeypatch, value):
    from app.core import session as session_mod
    from app.core.config import get_settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", value)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            session_mod.get_session_secret()
    finally:
        get_settings.cache_clear()


def test_production_accepts_generated_secret(monkeypatch):
    from app.core import session as session_mod
    from app.core.config import get_settings

    strong = secrets.token_urlsafe(48)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", strong)
    get_settings.cache_clear()
    try:
        assert session_mod.get_session_secret() == strong
    finally:
        get_settings.cache_clear()


def test_dev_fallback_is_random_per_process(monkeypatch):
    from app.core import session as session_mod
    from app.core.config import get_settings

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SESSION_SECRET", "")
    monkeypatch.setattr(session_mod, "_EPHEMERAL_SECRET", None)
    get_settings.cache_clear()
    try:
        a = session_mod.get_session_secret()
        assert len(a) >= 32 and a == session_mod.get_session_secret()
        monkeypatch.setattr(session_mod, "_EPHEMERAL_SECRET", None)
        assert session_mod.get_session_secret() != a
    finally:
        get_settings.cache_clear()


class _StartedPastSecretCheck(Exception):
    pass


def _stub_worker_runtime(monkeypatch, worker_mod):
    """Make worker.main() stop right after its startup check (no threads, no DB)."""

    def _boom(*a, **k):
        raise _StartedPastSecretCheck()

    monkeypatch.setattr(worker_mod, "HeartbeatThread", _boom)


@pytest.mark.parametrize(
    "value", [None, "", "placeholder", "test-secret", "changeme", "a" * 64, "short-but-random-9f"]
)
def test_worker_refuses_to_start_in_production_with_missing_or_weak_secret(monkeypatch, value):
    import app.worker as worker_mod
    from app.core.config import get_settings

    _stub_worker_runtime(monkeypatch, worker_mod)
    monkeypatch.setenv("APP_ENV", "production")
    if value is None:
        monkeypatch.delenv("SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("SESSION_SECRET", value)
    get_settings.cache_clear()
    try:
        with pytest.raises(
            RuntimeError, match="worker: APP_ENV=production requires SESSION_SECRET"
        ):
            worker_mod.main()
    finally:
        get_settings.cache_clear()


def test_worker_starts_in_production_with_generated_secret(monkeypatch):
    import app.worker as worker_mod
    from app.core.config import get_settings

    _stub_worker_runtime(monkeypatch, worker_mod)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(48))
    get_settings.cache_clear()
    try:
        with pytest.raises(_StartedPastSecretCheck):
            worker_mod.main()
    finally:
        get_settings.cache_clear()


def test_worker_outside_production_does_not_require_a_secret(monkeypatch):
    import app.worker as worker_mod
    from app.core.config import get_settings

    _stub_worker_runtime(monkeypatch, worker_mod)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(_StartedPastSecretCheck):
            worker_mod.main()
    finally:
        get_settings.cache_clear()


def test_api_and_worker_share_the_startup_secret_check():
    api = REPO_ROOT / "apps" / "api" / "app"
    for rel, component in (("main.py", '"api"'), ("worker.py", '"worker"')):
        src = (api / rel).read_text()
        assert f"enforce_production_session_secret({component})" in src, rel
    session_src = (api / "core" / "session.py").read_text()
    assert "config_contract" not in session_src


def _prod_compose_services() -> dict:
    import yaml

    return yaml.safe_load((REPO_ROOT / "docker-compose.prod.yml").read_text())["services"]


@pytest.mark.parametrize("service", ["api", "worker"])
def test_prod_compose_runs_api_and_worker_in_production_with_required_secret(service):
    env = _prod_compose_services()[service]["environment"]
    assert env.get("APP_ENV") == "production", service
    assert str(env.get("SESSION_SECRET", "")).startswith("${SESSION_SECRET:?"), service


def test_dev_compose_comment_does_not_claim_runtime_rejection():
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    assert "the API refuses these defaults" not in text


def test_storage_client_requires_explicit_credentials(monkeypatch):
    from app.core.config import get_settings
    from app.services import storage

    monkeypatch.setenv("S3_ACCESS_KEY", "")
    monkeypatch.setenv("S3_SECRET_KEY", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="S3_"):
            storage.StorageClient()
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Logs/traces: secret material is redacted
# ---------------------------------------------------------------------------


def test_log_redaction_masks_cookies_tokens_and_url_credentials():
    import logging
    from app.core.logging_config import JsonFormatter, redact

    cookie = _fake_session_cookie()
    pw = secrets.token_urlsafe(16)
    for text in (
        f"Cookie: tc_session={cookie}",
        f"Authorization: Bearer {pw}",
        f"postgresql://tc:{pw}@db/tc",
        f"password={pw}",
    ):
        cleaned = redact(text)
        assert cookie not in cleaned and pw not in cleaned
    rec = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "login %s", (f"tc_session={cookie}",), None
    )
    rec.session_secret = pw
    out = JsonFormatter().format(rec)
    assert cookie not in out and pw not in out


# ---------------------------------------------------------------------------
# Live-API helper scripts: no literals, not collected, need explicit env
# ---------------------------------------------------------------------------

LIVE_SCRIPTS = [
    # TC-02-001 (#20) moved every live-API script to scripts/manual_live/ behind _live_guard.py.
    "scripts/manual_live/probe_coverage_api.py",
    "scripts/manual_live/probe_alerts_api.py",
    "scripts/manual_live/fetch_ds5.py",
    "scripts/manual_live/fetch_full_qa.py",
    "scripts/manual_live/run_10dataset_check.py",
    "scripts/manual_live/run_3dataset_check.py",
]
API_ROOT = REPO_ROOT / "apps" / "api"


@pytest.mark.parametrize("rel", LIVE_SCRIPTS)
def test_live_scripts_have_no_module_level_side_effects(rel):
    path = API_ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} not present")
    tree = ast.parse(path.read_text())
    collectable = path.name.startswith("test_") or path.stem.endswith("_test")
    if collectable:
        assert "__test__ = False" in path.read_text(), f"{rel} must opt out of pytest collection"
    for node in tree.body if collectable else []:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            pytest.fail(f"{rel}:{node.lineno} performs a call at import time")
    src = path.read_text()
    assert "_live_guard" in src, f"{rel} must use scripts/manual_live/_live_guard.py"


def test_live_session_helper_requires_env(monkeypatch):
    guard_dir = str(API_ROOT / "scripts" / "manual_live")
    sys.path.insert(0, guard_dir)
    try:
        import _live_guard

        monkeypatch.delenv("TC_SESSION_SECRET", raising=False)
        with pytest.raises(SystemExit):
            _live_guard.forge_session_cookie(1)
        # Synthetic identity only, and the forged cookie is short-lived.
        monkeypatch.setenv("TC_SESSION_SECRET", "x" * 48)
        monkeypatch.setenv("TC_SESSION_EMAIL", "someone@real-company.com")
        with pytest.raises(SystemExit):
            _live_guard.forge_session_cookie(1)
        monkeypatch.delenv("TC_SESSION_EMAIL")
        payload = json.loads(
            base64.urlsafe_b64decode(_live_guard.forge_session_cookie(1).split(".")[0])
        )
        assert 0 < payload["exp"] - time.time() <= 3600
        with pytest.raises(SystemExit):
            monkeypatch.setenv("TC_API", "https://api.production.invalid")
            _live_guard.api_base()
    finally:
        sys.path.remove(guard_dir)


def test_seed_scripts_have_no_password_literals():
    for rel in ("scripts/seed_demo_workspace.py", "scripts/seed_qa_test_data.py"):
        tree = ast.parse((API_ROOT / rel).read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                names = [getattr(t, "id", "") for t in node.targets]
                assert not any("PASSWORD" in n.upper() for n in names), f"{rel}:{node.lineno}"


def test_web_login_bundle_has_no_demo_password_literal():
    src = (REPO_ROOT / "apps/web/app/login/page.tsx").read_text()
    assert "NEXT_PUBLIC_DEMO_LOGIN_PASSWORD" in src
    assert "password: DEMO_LOGIN_PASSWORD" in src


# ---------------------------------------------------------------------------
# Encryption-key consumers (credential store, MFA, Slack) fail closed in production
# (Integrations input: credential store previously fell back to a hardcoded key)
# ---------------------------------------------------------------------------

_KEY_CONSUMERS = [
    ("app.services.credential_store_service", "_get_fernet"),
    ("app.core.mfa", "_fernet"),
    ("app.services.slack_service", "_fernet"),
]


@pytest.mark.parametrize("module,func", _KEY_CONSUMERS)
@pytest.mark.parametrize("value", ["", "placeholder", "changeme"])
def test_encryption_key_consumers_fail_closed_in_production(monkeypatch, module, func, value):
    import importlib
    from app.core.config import get_settings

    mod = importlib.import_module(module)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", value)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="SESSION_SECRET"):
            getattr(mod, func)()
    finally:
        get_settings.cache_clear()


def test_credential_store_has_no_literal_fallback():
    src = (API_ROOT / "app/services/credential_store_service.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", "") in ("getenv", "get")
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
            and "SECRET" in str(node.args[0].value).upper()
        ):
            default = node.args[1]
            assert isinstance(default, ast.Constant) and default.value in (
                "",
                None,
            ), f"credential_store_service.py:{node.lineno} has a literal secret fallback"


def test_credential_store_roundtrip_with_generated_secret(monkeypatch):
    from app.core.config import get_settings
    from app.services import credential_store_service as cs

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(48))
    get_settings.cache_clear()
    try:
        plain = secrets.token_urlsafe(16)
        assert cs.decrypt(cs.encrypt(plain)) == plain
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Compose files: no inline production credentials; dev defaults are overridable
# ---------------------------------------------------------------------------


def test_prod_compose_requires_credentials_from_env():
    text = (REPO_ROOT / "docker-compose.prod.yml").read_text()
    for var in ("POSTGRES_PASSWORD", "POSTGRES_USER", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"):
        assert (
            f"${{{var}:?" in text
        ), f"docker-compose.prod.yml must require {var} (${{{var}:?...}})"
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("DATABASE_URL:") or s.startswith("- DATABASE_URL="):
            pytest.fail("docker-compose.prod.yml must not inline DATABASE_URL")


def test_dev_compose_credentials_are_overridable():
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    for var in ("POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "MINIO_ROOT_USER", "POSTGRES_USER"):
        line = next(ln for ln in text.splitlines() if ln.strip().startswith(f"{var}:"))
        assert "${" + var in line, f"docker-compose.yml {var} must be an overridable variable"
    for line in text.splitlines():
        if line.strip().startswith("DATABASE_URL:"):
            assert "${POSTGRES_PASSWORD" in line


# ---------------------------------------------------------------------------
# Deploy docs: operators generate every secret; committed values are retired
# (AC2 owner statement 2026-10-27). Cheap text checks, no values involved.
# ---------------------------------------------------------------------------

import re  # noqa: E402

DEPLOY_ENTRYPOINTS = ("README.md", ".env.example", "docker-compose.prod.yml")

_CRED_PAIR = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+`?\s*/\s*`[^`\s]+`")
_MD_ASSIGN = re.compile(
    r"(?i)\b[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_KEY|ACCESS_KEY|TOKEN)[A-Z0-9_]*\s*[=:]\s*`?([^\s`|,;)]+)"
)
_PLACEHOLDER = re.compile(
    r"(?i)^(<.*>|\$\{.*|\$[A-Z_]+|\.\.\.|placeholder\S*|changeme|change-me|x+|\*+|\"\"|''|none|null|unset)$"
)
_NOT_A_VALUE = re.compile(
    r"^[\d<>=.,()%+-]+$"
)  # e.g. "SESSION_SECRET: 32)" describes a length, not a value
_REUSE = re.compile(
    r"(?i)\b(re-?use|keep|copy|use)\s+(the\s+)?(same|existing|committed|default|example|old|sample|demo|dev)\s+"
    r"(passwords?|secrets?|keys?|credentials?|tokens?|values?)"
)
_NEGATION = re.compile(r"(?i)\b(never|not|don't|do not|must not|no)\b")


def _deploy_doc_paths() -> list[Path]:
    paths = [REPO_ROOT / p for p in DEPLOY_ENTRYPOINTS]
    paths += [
        REPO_ROOT / "scripts" / "README.md",
        REPO_ROOT / "apps" / "api" / "scripts" / "README.md",
    ]
    for p in sorted((REPO_ROOT / "docs").rglob("*.md")):
        rel = p.relative_to(REPO_ROOT).as_posix()
        if rel.startswith("docs/release/tickets/"):
            continue  # ticket docs describe the exposure inventory (paths only), not deploy steps
        paths.append(p)
    return [p for p in paths if p.exists()]


def deploy_doc_problems(text: str, *, markdown: bool) -> list[str]:
    """Return line-numbered problem descriptions (never the matched value)."""
    problems: list[str] = []
    for n, line in enumerate(text.splitlines(), 1):
        if _CRED_PAIR.search(line):
            problems.append(f"line {n}: login/password literal pair")
        if _REUSE.search(line) and not _NEGATION.search(line):
            problems.append(
                f"line {n}: tells the operator to reuse an existing/committed credential"
            )
        if markdown:
            for m in _MD_ASSIGN.finditer(line):
                if not _PLACEHOLDER.match(m.group(1)) and not _NOT_A_VALUE.match(m.group(1)):
                    problems.append(f"line {n}: credential assignment with a literal value")
    return problems


def test_deploy_entrypoints_require_operator_generated_secrets():
    for rel in DEPLOY_ENTRYPOINTS:
        text = (REPO_ROOT / rel).read_text()
        assert (
            "openssl rand" in text
        ), f"{rel} must tell operators to generate secrets (e.g. openssl rand)"
        flat = re.sub(r"\s*\n\s*#?\s*", " ", text)  # join wrapped comment lines
        assert re.search(
            r"(?i)generate every secret", flat
        ), f"{rel} must say every secret is operator-generated"
        assert re.search(
            r"(?i)\bretired\b", flat
        ), f"{rel} must state previously exposed values are retired"
        assert re.search(
            r"(?i)never be reused", flat
        ), f"{rel} must say retired values must never be reused"


def test_deploy_docs_never_point_at_committed_values():
    failures = []
    for p in _deploy_doc_paths():
        rel = p.relative_to(REPO_ROOT).as_posix()
        for problem in deploy_doc_problems(
            p.read_text(errors="replace"), markdown=p.suffix == ".md"
        ):
            failures.append(f"{rel} {problem}")
    assert not failures, "Deploy docs must not hand out or reuse credentials:\n" + "\n".join(
        failures
    )


@pytest.mark.parametrize(
    "template",
    [
        "- **Demo login:** `ops@example.test` / `{v}` (after seed)",
        "For production, reuse the committed secret from docker-compose.yml.",
        "Copy the example password into .env.production.",
        "Set SESSION_SECRET={v} before deploying.",
        "Use `MINIO_ROOT_PASSWORD: {v}` in production.",
    ],
)
def test_deploy_doc_checker_flags_bad_guidance(template):
    bad = template.format(v="k" + secrets.token_hex(8))  # letter prefix: never all-digit
    assert deploy_doc_problems(bad, markdown=True), "checker must flag this guidance"


@pytest.mark.parametrize(
    "line",
    [
        "Generate every secret with `openssl rand -hex 32`; never reuse a committed value.",
        "Set SESSION_SECRET=<generated> and S3_SECRET_KEY=${S3_SECRET_KEY}.",
        "Do not copy the example password into production.",
        "Credentials shorter than 16 characters (SESSION_SECRET: 32) are refused.",
    ],
)
def test_deploy_doc_checker_allows_good_guidance(line):
    assert deploy_doc_problems(line, markdown=True) == []


# ---------------------------------------------------------------------------
# TC-07-001a follow-ups
# ---------------------------------------------------------------------------

SELF_RELS = (
    "scripts/security/secret_inventory.py",
    "apps/api/tests/release/test_secret_inventory.py",
)


def _aws_canary() -> str:
    return "AKIA" + "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16)
    )


def _real_value_lines() -> list[tuple[str, str]]:
    """(rule, line) pairs carrying runtime-generated values (never placeholders)."""
    tok = secrets.token_hex(24)
    key = secrets.token_urlsafe(32)
    return [
        ("aws-access-key-id", f"AWS_ID = {_aws_canary()!r}"),
        ("openai-api-key", f"client_key = {'sk-' + secrets.token_urlsafe(32)!r}"),
        ("high-entropy-secret-assignment", f'API_TOKEN = "{tok}"'),
        ("hmac-literal-key", f'sig = hmac.new(b"{key}", msg, "sha256")'),
    ]


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.mark.parametrize("rel", SELF_RELS)
def test_self_paths_still_block_real_values(scanner, tmp_path, rel):
    lines = _real_value_lines()
    text = "\n".join(line for _, line in lines) + "\n"
    expected = {rule for rule, _ in lines}
    _write(tmp_path, rel, text)
    for found in (
        scanner.scan_text(text, rel),
        scanner.scan_tree(tmp_path),
        scanner.scan_paths(tmp_path, [rel]),
    ):
        blocked = {f.rule for f in _blocks(found) if f.path == rel and not f.reason}
        assert expected <= blocked, (rel, expected - blocked)


def test_self_path_downgrade_is_limited_to_bare_placeholders(scanner):
    q = '"'
    placeholder = "sig = hmac" + ".new(b" + q + "{tok}" + q + ', msg, "sha256")\n'
    env_default = "os.getenv(" + q + "SESSION_SECRET" + q + ", " + q + "{tok}" + q + ")\n"
    for text, rule in ((placeholder, "hmac-literal-key"), (env_default, "secret-env-default")):
        for rel in SELF_RELS:
            found = [f for f in scanner.scan_text(text, rel) if f.rule == rule]
            assert found and all(f.severity == "review" for f in found), rel
            assert all(f.reason == scanner.REASON_SELF_INTERPOLATION for f in found)
        other = scanner.scan_text(text, "apps/api/tests/test_other.py")
        assert [f for f in _blocks(other) if f.rule == rule], "downgrade must not apply elsewhere"
    # two placeholders, or a placeholder mixed with literal text, is not a bare placeholder
    mixed = "os.getenv(" + q + "SESSION_SECRET" + q + ", " + q + "x{tok}" + q + ")\n"
    assert _blocks(scanner.scan_text(mixed, SELF_RELS[1]))


def test_scanner_and_its_test_have_no_block_findings(scanner):
    for rel in SELF_RELS:
        found = scanner.scan_text((REPO_ROOT / rel).read_text(), rel)
        assert _blocks(found) == [], rel
        for f in found:
            if f.reason == scanner.REASON_SELF_INTERPOLATION:
                assert f.rule in {
                    "hmac-literal-key",
                    "secret-env-default",
                    "app-secret-literal",
                    "high-entropy-secret-assignment",
                    "url-embedded-credential",
                    "libpq-password",
                    "config-secret-value",
                }, f


def test_self_paths_are_no_longer_skipped(scanner):
    for rel in SELF_RELS:
        assert not scanner._should_skip(rel)


@pytest.mark.parametrize(
    "rel",
    [
        "apps/api/tests/../app/core/leak.py",
        "apps/api/tests/./../app/core/leak.py",
        "./apps/api/app/core/leak.py",
        "apps/api/scripts/manual_live/../../app/core/leak.py",
    ],
)
def test_paths_mode_normalizes_traversal(scanner, tmp_path, rel):
    """'..' cannot make application code look like a test/manual path (marker, app-code rules)."""
    q = '"'
    text = (
        "# "
        + scanner.SYNTHETIC_PRAGMA
        + "\n"
        + "SESSION_SECRET = "
        + q
        + "plain"
        + q
        + "\n"
        + "API_TOKEN = "
        + q
        + secrets.token_hex(24)
        + q
        + "  # "
        + scanner.SYNTHETIC_PRAGMA
        + "\n"
    )
    _write(tmp_path, "apps/api/app/core/leak.py", text)
    found = scanner.scan_paths(tmp_path, [rel])
    assert {f.path for f in found} == {"apps/api/app/core/leak.py"}
    rules = {f.rule for f in _blocks(found)}
    assert "app-secret-literal" in rules
    assert "high-entropy-secret-assignment" in rules
    assert not [f for f in found if f.reason == scanner.REASON_SYNTHETIC]
    assert {f.path for f in scanner.scan_text(text, rel)} == {"apps/api/app/core/leak.py"}


def test_scan_text_keeps_archive_member_names(scanner):
    assert scanner._normalize_path("a/../b/x.zip!c/../d.py") == "b/x.zip!c/../d.py"
    assert scanner._normalize_path("./x.py") == "x.py"


def _complex_password(n: int) -> str:
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, "!#%^*-_"]
    chars = [secrets.choice(p) for p in pools]
    rest = [c for c in "".join(pools) if c not in chars]
    while len(chars) < n:
        c = secrets.choice(rest)
        rest.remove(c)
        chars.append(c)
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _with_slash(pw: str) -> str:
    return pw[:3] + "/" + pw[3:]


@pytest.mark.parametrize("host", ["db.internal:5432", "localhost", "127.0.0.1:5432", "example.com"])
def test_url_password_containing_slash_blocks(scanner, host):
    pw = _with_slash(secrets.token_urlsafe(16))
    line = f"DATABASE_URL=postgresql://app:{pw}@{host}/trust\n"
    found = scanner.scan_text(line, "deploy/app.env")
    assert [f for f in _blocks(found) if f.rule == "url-embedded-credential"], host


def test_url_port_and_path_with_at_is_not_a_password(scanner):
    for line in (
        "see https://registry.example.com:8443/@scope/pkg for the build\n",
        "GET http://api.example.com:8080/users/me@team/settings\n",
    ):
        assert not [f for f in scanner.scan_text(line, "docs/x.md") if "url" in f.rule], line


@pytest.mark.parametrize("n", [8, 9, 11])
def test_short_complex_url_password_blocks(scanner, n):
    pw = _complex_password(n)
    found = scanner.scan_text(f"url = 'postgresql://app:{pw}@db.internal:5432/x'\n", "deploy/x.py")
    assert [f for f in _blocks(found) if f.rule == "url-embedded-credential"], n


@pytest.mark.parametrize(
    "pw", ["postgres", "minio123", "minioadmin", "Passpass", "abc12345", "devpass1"]
)
def test_dev_default_url_passwords_stay_review(scanner, pw):
    found = scanner.scan_text(f"postgresql://app:{pw}@db.internal:5432/x\n", "deploy/app.env")
    assert not _blocks(found)
    assert [f for f in found if f.rule == "url-credential-review"]


def test_seven_char_complex_url_password_is_review(scanner):
    pw = _complex_password(7)
    found = scanner.scan_text(f"postgresql://app:{pw}@db.internal:5432/x\n", "deploy/app.env")
    assert not _blocks(found)


def _libpq_lines(pw: str) -> list[str]:
    return [
        f"host=db.internal port=5432 dbname=trust user=app password={pw} sslmode=require",
        f"dsn = 'host=db user=app password={pw}'",
        f"PGDSN=\"dbname=trust password='{pw}' host=db\"",
        f"password={pw} host=db.internal",
        f'conn = psycopg.connect("user=app  password={pw}  dbname=x")',
    ]


def test_libpq_password_blocks(scanner):
    for pw in (secrets.token_urlsafe(18), _complex_password(10)):
        for line in _libpq_lines(pw):
            found = scanner.scan_text(line + "\n", "deploy/run.sh")
            assert [f for f in _blocks(found) if f.rule == "libpq-password"], line


def test_libpq_dev_password_is_review(scanner):
    for line in _libpq_lines("postgres"):
        found = scanner.scan_text(line + "\n", "deploy/run.sh")
        assert not _blocks(found), line
        assert [f for f in found if f.rule == "libpq-password-review"], line


def test_libpq_rule_ignores_env_names_and_kwargs(scanner):
    pw = secrets.token_urlsafe(18)
    q = '"'
    for line in (
        "connect(host=h, user=u, password=pw, dbname=d)",
        "connect(host=h, password=" + q + "x" + q + ")",
        "PGPASSWORD=$PGPASSWORD psql -h db -U app",
        "export POSTGRES_PASSWORD=$(cat /run/secrets/pg) host=db",
        "the password=... field and the host= field are documented below",
        "my.password=" + pw + " host=db",
    ):
        found = scanner.scan_text(line + "\n", "docs/notes.txt")
        assert not [f for f in found if f.rule.startswith("libpq")], line


# --- TC-07-001a item 3: API lifespan checks the secret first, APP_ENV is normalized -------------

_PROD_SPELLINGS = [" production ", "PRODUCTION", "production\n", "\tProduction "]


def _stub_lifespan_io(monkeypatch, main_mod) -> list[str]:
    """Record DB/S3 startup calls; the DB stub stops the lifespan right after the secret check."""
    calls: list[str] = []

    def _db():
        calls.append("db")
        raise _StartedPastSecretCheck()

    class _Storage:
        def __init__(self, *a, **k):
            calls.append("s3")

        def ensure_buckets(self):
            calls.append("s3.ensure_buckets")

    monkeypatch.setattr(main_mod, "_verify_db_connectivity", _db)
    monkeypatch.setattr(main_mod, "StorageClient", _Storage)
    return calls


def _run_lifespan(main_mod):
    import asyncio

    async def _enter():
        async with main_mod.lifespan(main_mod.app):
            pass

    asyncio.run(_enter())


@pytest.mark.parametrize("env", _PROD_SPELLINGS + ["production"])
@pytest.mark.parametrize("value", [None, "", "placeholder", "a" * 64])
def test_api_lifespan_refuses_weak_secret_before_any_db_or_s3_call(monkeypatch, env, value):
    import app.main as main_mod
    from app.core.config import get_settings

    calls = _stub_lifespan_io(monkeypatch, main_mod)
    monkeypatch.setenv("APP_ENV", env)
    if value is None:
        monkeypatch.delenv("SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("SESSION_SECRET", value)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="api: APP_ENV=production requires SESSION_SECRET"):
            _run_lifespan(main_mod)
        assert calls == []
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("env", _PROD_SPELLINGS)
def test_api_lifespan_proceeds_with_generated_secret(monkeypatch, env):
    import app.main as main_mod
    from app.core.config import get_settings

    calls = _stub_lifespan_io(monkeypatch, main_mod)
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("SESSION_SECRET", secrets.token_urlsafe(48))
    get_settings.cache_clear()
    try:
        with pytest.raises(_StartedPastSecretCheck):
            _run_lifespan(main_mod)
        assert calls == ["db"]
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("env", ["development", " development ", "test", ""])
def test_api_lifespan_outside_production_does_not_require_a_secret(monkeypatch, env):
    import app.main as main_mod
    from app.core.config import get_settings

    calls = _stub_lifespan_io(monkeypatch, main_mod)
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(_StartedPastSecretCheck):
            _run_lifespan(main_mod)
        assert calls == ["db"]
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("env", _PROD_SPELLINGS)
def test_app_env_is_stripped_and_detected(monkeypatch, env):
    from app.core import session as session_mod
    from app.core.config import get_settings

    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("SESSION_SECRET", "placeholder")
    get_settings.cache_clear()
    try:
        assert get_settings().app_env == "production"
        assert session_mod.is_production_env()
        with pytest.raises(RuntimeError):
            session_mod.get_session_secret()
    finally:
        get_settings.cache_clear()


def test_lifespan_source_orders_secret_check_before_io():
    src = (REPO_ROOT / "apps" / "api" / "app" / "main.py").read_text()
    body = src[src.index("async def lifespan(") :]
    check = body.index('enforce_production_session_secret("api")')
    assert check < body.index("_verify_db_connectivity()") < body.index("StorageClient()")
    assert check < body.index("get_settings()")
