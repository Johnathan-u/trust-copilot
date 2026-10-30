"""Synthetic key-format transition regressions; no stored production material."""

import base64
import hashlib
import hmac
import secrets

import pytest
from cryptography.fernet import Fernet

from app.core.keys import (
    KeyErrorSafe,
    PURPOSE_ENV,
    open_sealed,
    seal,
    sign_with_purpose,
    verify_with_purpose,
)
from app.core.mfa import mfa_reenrol_pending

ROOT = secrets.token_urlsafe(32)
REPLACEMENT = secrets.token_urlsafe(32)
PLAINTEXT = "synthetic example recoverable secret"


@pytest.mark.parametrize("purpose", ["mfa", "connector"])
def test_default_prefixed_ciphertext_survives_explicit_retained_legacy_key(purpose):
    stored = seal(purpose, PLAINTEXT, {"SESSION_SECRET": ROOT})
    rotated = {
        "SESSION_SECRET": secrets.token_urlsafe(32),
        PURPOSE_ENV[purpose]: f"new:{REPLACEMENT},v0-legacy:{ROOT}",
    }
    assert open_sealed(purpose, stored, rotated) == PLAINTEXT


@pytest.mark.parametrize("purpose", ["mfa", "connector"])
def test_original_and_prefixed_sha256_ciphertext_use_retained_legacy_material(purpose):
    token = Fernet(base64.urlsafe_b64encode(hashlib.sha256(ROOT.encode()).digest()))
    legacy = token.encrypt(PLAINTEXT.encode()).decode()
    env = {
        "SESSION_SECRET": secrets.token_urlsafe(32),
        PURPOSE_ENV[purpose]: f"new:{REPLACEMENT},v0-legacy:{ROOT}",
    }
    assert open_sealed(purpose, legacy, env) == PLAINTEXT
    # Preserve ciphertext written by the previous explicit-v0 implementation.
    assert open_sealed(purpose, f"v0-legacy.{legacy}", env) == PLAINTEXT
    with pytest.raises(KeyErrorSafe):
        open_sealed(purpose, legacy, {**env, PURPOSE_ENV[purpose]: f"new:{REPLACEMENT}"})


@pytest.mark.parametrize("purpose", ["session", "oauth_state"])
def test_default_prefixed_signature_survives_explicit_legacy_configuration(purpose):
    signed = sign_with_purpose(purpose, "synthetic-payload", {"SESSION_SECRET": ROOT})
    explicit = {"SESSION_SECRET": ROOT, PURPOSE_ENV[purpose]: f"v0-legacy:{ROOT}"}
    assert (
        verify_with_purpose(purpose, signed, accept_retired=False, env=explicit)
        == "synthetic-payload"
    )


@pytest.mark.parametrize("purpose", ["session", "oauth_state"])
def test_old_prefixed_sha256_signature_requires_explicit_allowed_legacy_entry(purpose):
    signature = hmac.new(
        hashlib.sha256(ROOT.encode()).digest(), b"synthetic-payload", "sha256"
    ).hexdigest()
    signed = f"v0-legacy.synthetic-payload.{signature}"
    assert (
        verify_with_purpose(purpose, signed, accept_retired=True, env={"SESSION_SECRET": ROOT})
        is None
    )
    env = {PURPOSE_ENV[purpose]: f"new:{REPLACEMENT},v0-legacy:{ROOT}"}
    assert verify_with_purpose(purpose, signed, accept_retired=False, env=env) is None
    assert verify_with_purpose(purpose, signed, accept_retired=True, env=env) == "synthetic-payload"


@pytest.mark.parametrize(
    "ring,accept_retired,expected",
    [
        (None, False, "synthetic-payload"),
        (f"v0-legacy:{ROOT}", False, "synthetic-payload"),
        (f"new:{REPLACEMENT}", False, None),
        (f"new:{REPLACEMENT}", True, None),
        (f"new:{REPLACEMENT},v0-legacy:{ROOT}", False, None),
        (f"new:{REPLACEMENT},v0-legacy:{ROOT}", True, "synthetic-payload"),
    ],
)
def test_unprefixed_signatures_obey_legacy_key_presence_and_retirement(
    ring, accept_retired, expected
):
    signature = hmac.new(ROOT.encode(), b"synthetic-payload", "sha256").hexdigest()
    env = {"SESSION_SECRET": ROOT}
    if ring:
        env["SESSION_KEYRING"] = ring
    assert (
        verify_with_purpose(
            "session", f"synthetic-payload.{signature}", accept_retired=accept_retired, env=env
        )
        == expected
    )


def test_explicit_legacy_signature_does_not_use_unrelated_session_secret():
    signature = hmac.new(ROOT.encode(), b"synthetic-payload", "sha256").hexdigest()
    env = {"SESSION_SECRET": REPLACEMENT, "SESSION_KEYRING": f"v0-legacy:{ROOT}"}
    assert (
        verify_with_purpose(
            "session", f"synthetic-payload.{signature}", accept_retired=False, env=env
        )
        == "synthetic-payload"
    )


def test_reenrol_marker_cannot_conflict_with_a_valid_mfa_key_id():
    env = {"MFA_KEYRING": f"reenrol-pending:{ROOT}"}
    stored = seal("mfa", PLAINTEXT, env)
    assert not mfa_reenrol_pending(stored)
    assert open_sealed("mfa", stored, env) == PLAINTEXT
