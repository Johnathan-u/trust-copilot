"""Advertised framework catalog registry.

This module is framework-agnostic metadata only. It does not contain control
text, control descriptions, or a licensable catalog body. Every advertised
framework stays blocked until content rights are decided in TC-01-007.
There is no configuration flag that clears that gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CATALOG_CONTRACT_VERSION = "framework-catalog/v1"
ERROR_CONTRACT_VERSION = "framework-catalog-error/v1"
RIGHTS_TICKET = "TC-01-007"

# Stored in frameworks.version when no licensed content version exists.
# This is a scaffold sentinel, not a standards-body publication version.
UNLICENSED_VERSION = "rights-pending"

RIGHTS_BLOCKED = "blocked_pending_rights"
RIGHTS_DEV = "dev_test_only"
LICENCE_NOT_CLEARED = "not_cleared"
LICENCE_DEV = "dev_test_only"
ENABLEMENT_BLOCKED = "blocked"
ENABLEMENT_DEV = "dev_only"
KIND_ADVERTISED = "advertised_blocked"
KIND_DEV = "dev_synthetic"
KIND_LEGACY = "legacy_unclassified"
CONTENT_NONE = "none"
CONTENT_DEV = "dev_seed"
CONTENT_LEGACY = "legacy"

# Enablement values the database is allowed to persist while TC-01-007 is open.
PERSISTED_ENABLEMENT_STATES = frozenset({ENABLEMENT_BLOCKED, ENABLEMENT_DEV})

ERROR_RIGHTS = "framework_rights_not_cleared"
ERROR_DEV = "framework_dev_catalog_not_production"
ERROR_UNKNOWN = "framework_not_advertised"
ERROR_NAME = "framework_name_required"
ERROR_PARTIAL = "framework_enablement_partial_failure"
ERROR_REQUEST = "framework_request_invalid"


def normalize_catalog_name(value: str | None) -> str:
    """Compare catalog names without case, spaces, or punctuation."""
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def is_synthetic_dev_version(version: str | None) -> bool:
    """True for versions that mark the in-repo synthetic dev catalog."""
    if not version:
        return False
    folded = version.strip().lower()
    if folded in {"csf-dev", "dev-themes"}:
        return True
    if "dev theme" in folded or "dev-theme" in folded:
        return True
    if folded.startswith("dev-") or folded.endswith("-dev"):
        return True
    return False


def is_synthetic_dev_control_key(control_key: str | None) -> bool:
    """True for synthetic DEV keys. The key prefix is an identifier, not control text."""
    if not control_key:
        return False
    token = control_key.strip().upper()
    return (
        token.startswith("HITRUST-DEV-")
        or token.startswith("ISO-DEV-")
        or token.startswith("DEV-")
        or "-DEV-" in token
    )


# Name/version pairs written by scripts/dev_compliance_catalog.py.
# Used only to recognise an already-seeded dev row when it also has controls.
# A matching name and version with no controls is not treated as that seed.
SEED_FINGERPRINTS = frozenset(
    {
        ("soc2", "2024"),
        ("hipaa", "security rule"),
        ("nist", "csf-2.0"),
        ("hitrust", "csf-dev"),
        ("iso27001", "dev-themes"),
    }
)


def is_dev_catalog_row(
    name: str | None, version: str | None, control_keys: list[str] | tuple[str, ...]
) -> bool:
    """True when a persisted row is the synthetic dev/test catalog, not a production catalog."""
    if is_synthetic_dev_version(version):
        return True
    if any(is_synthetic_dev_control_key(key) for key in control_keys):
        return True
    if control_keys:
        fingerprint = (normalize_catalog_name(name), (version or "").strip().lower())
        if fingerprint in SEED_FINGERPRINTS:
            return True
    return False


def is_dev_enable_request(name: str | None, version: str | None) -> bool:
    """True when the caller is asking to enable a synthetic DEV key or dev version as production."""
    return (
        is_synthetic_dev_control_key(name)
        or is_synthetic_dev_version(name)
        or is_synthetic_dev_version(version)
    )


@dataclass(frozen=True)
class AdvertisedCatalog:
    catalog_key: str
    name: str
    aliases: tuple[str, ...]

    def match_norms(self) -> frozenset[str]:
        values = {self.catalog_key, self.name, *self.aliases}
        return frozenset(
            normalize_catalog_name(value) for value in values if normalize_catalog_name(value)
        )


ADVERTISED_CATALOGS: tuple[AdvertisedCatalog, ...] = (
    AdvertisedCatalog("SOC2", "SOC 2", ("SOC2", "SOC 2", "SOC II", "SOC-2")),
    AdvertisedCatalog("HIPAA", "HIPAA", ("HIPAA",)),
    AdvertisedCatalog(
        "ISO27001", "ISO 27001", ("ISO27001", "ISO 27001", "ISO/IEC 27001", "ISO/IEC27001")
    ),
    AdvertisedCatalog(
        "NIST_CSF_2",
        "NIST CSF 2",
        ("NIST CSF 2", "NIST CSF 2.0", "NIST CSF", "CSF 2.0", "NIST Cybersecurity Framework"),
    ),
    AdvertisedCatalog(
        "NIST_800_53_R5",
        "NIST 800-53r5",
        (
            "NIST 800-53r5",
            "NIST 800-53",
            "NIST SP 800-53",
            "NIST SP 800-53 Rev. 5",
            "NIST SP 800-53 Rev 5",
            "800-53",
        ),
    ),
    AdvertisedCatalog(
        "NIST_800_171_R3",
        "NIST 800-171r3",
        (
            "NIST 800-171r3",
            "NIST 800-171",
            "NIST SP 800-171",
            "NIST SP 800-171 Rev. 3",
            "NIST SP 800-171 Rev 3",
        ),
    ),
    AdvertisedCatalog("SIG", "SIG", ("SIG", "Shared Assessments SIG", "Shared Assessments")),
    AdvertisedCatalog("CAIQ", "CAIQ", ("CAIQ", "CSA CAIQ")),
    AdvertisedCatalog("HITRUST", "HITRUST", ("HITRUST", "HITRUST CSF")),
)

ADVERTISED_KEYS = frozenset(spec.catalog_key for spec in ADVERTISED_CATALOGS)


def _assert_disjoint_aliases() -> None:
    seen: dict[str, str] = {}
    for spec in ADVERTISED_CATALOGS:
        for norm in spec.match_norms():
            previous = seen.get(norm)
            if previous is not None and previous != spec.catalog_key:
                raise RuntimeError(
                    f"catalog alias {norm!r} is shared by {previous} and {spec.catalog_key}"
                )
            seen[norm] = spec.catalog_key


_assert_disjoint_aliases()


def resolve_advertised(name: str | None) -> AdvertisedCatalog | None:
    """Resolve a request name to one advertised catalog, or None when it is unknown or ambiguous."""
    norm = normalize_catalog_name(name)
    if not norm:
        return None
    matches = [spec for spec in ADVERTISED_CATALOGS if norm in spec.match_norms()]
    if len(matches) == 1:
        return matches[0]
    return None


def provenance_for(kind: str) -> dict[str, object]:
    """Fixed provenance object. It never carries control text."""
    if kind == KIND_DEV:
        return {
            "kind": "dev_seed",
            "origin": "development-only catalog seed",
            "content_included": False,
            "licensed_text_included": False,
            "dev_test_only": True,
            "production_catalog": False,
            "rights_decision": "pending",
            "rights_ticket": RIGHTS_TICKET,
        }
    if kind == KIND_LEGACY:
        return {
            "kind": "legacy_row",
            "origin": "pre-catalog framework row",
            "content_included": False,
            "licensed_text_included": False,
            "dev_test_only": False,
            "production_catalog": False,
            "rights_decision": "pending",
            "rights_ticket": RIGHTS_TICKET,
        }
    return {
        "kind": "scaffold",
        "origin": "in-repo advertised catalog registry",
        "content_included": False,
        "licensed_text_included": False,
        "dev_test_only": False,
        "production_catalog": False,
        "rights_decision": "pending",
        "rights_ticket": RIGHTS_TICKET,
    }


def provenance_json(kind: str) -> str:
    return json.dumps(provenance_for(kind), sort_keys=True, separators=(",", ":"))


def rights_are_cleared() -> bool:
    """TC-01-007 is unresolved. Database values and environment flags cannot clear rights."""
    return False
