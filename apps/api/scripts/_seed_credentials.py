"""Seed-account credentials for local/QA/E2E databases (TC-07-001).

Passwords are NEVER committed. Each seeded account reads its password from an environment
variable; when the variable is unset (local development only) a random password is generated
for this run and written to ``apps/api/.seed-credentials.local`` (git-ignored, mode 0600) so the
operator can log in. Nothing is printed to stdout, so console logs never capture credentials.

Seeding is refused outright when APP_ENV=production (TC-03-001; there is no override).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = API_ROOT / ".seed-credentials.local"

_generated: dict[str, str] = {}


def refuse_production_seed() -> None:
    """Demo/QA/E2E seeding is never allowed in production (TC-03-001, no override).

    Production is detected by app.core.session.is_production_env() via the config contract
    (seed scripts put apps/api on sys.path, so ``app`` is always importable here).
    """
    from app.core.config_contract import refuse_demo_seed_in_production

    refuse_demo_seed_in_production()


def seed_password(env_name: str) -> str:
    """Return the password for a seeded account from ``env_name`` or generate one for this run."""
    value = os.environ.get(env_name, "")
    if value:
        return value
    if env_name not in _generated:
        _generated[env_name] = secrets.token_urlsafe(18)
    return _generated[env_name]


def describe(env_name: str) -> str:
    """Human-readable source of a password, without revealing it."""
    if os.environ.get(env_name):
        return f"from ${env_name}"
    return f"generated; see {CREDENTIALS_FILE.name} ({env_name})"


def write_generated_credentials() -> None:
    """Persist generated passwords to a git-ignored, owner-only file (no stdout)."""
    if not _generated:
        return
    existing: dict[str, str] = {}
    if CREDENTIALS_FILE.exists():
        for line in CREDENTIALS_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing[k] = v
    existing.update(_generated)
    fd = os.open(CREDENTIALS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("# Generated local seed passwords (git-ignored). Export these to reuse them.\n")
        for k, v in sorted(existing.items()):
            fh.write(f"{k}={v}\n")


def should_reset_passwords() -> bool:
    """When TC_SEED_RESET_PASSWORDS=1, existing seeded users get the current seed password (local DBs only)."""
    return os.environ.get("TC_SEED_RESET_PASSWORDS") == "1"
