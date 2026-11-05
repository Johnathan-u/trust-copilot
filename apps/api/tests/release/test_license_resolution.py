"""TC-01-003: licence resolution stays true (docs/acceptance/license-resolution.md).

* The production Compose stack bundles no MinIO (AGPL-3.0) and takes its S3 endpoint from the
  environment; every image it ships is listed with its licence in the resolution doc.
* Every API runtime pin that installs on this interpreter and every web runtime lock entry has a
  licence on a permissive allowlist, or is a documented, complied-with exception. Anything else
  (copyleft, source-available, proprietary, unrecognised or missing) fails. No AGPL, GPL, SSPL,
  BUSL or proprietary licence appears in any web lock entry, dev or runtime.

The compose and npm checks are static. The Python check reads the installed metadata of the
runtime pins; CI installs requirements-dev.lock, which contains all of them. Pins whose
environment marker does not apply are not installed (and not shipped) and are not checked.
"""

from __future__ import annotations

import json
import re
from email.message import Message
from importlib import metadata
from pathlib import Path

import pytest
import yaml
from packaging.markers import Marker

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]
DOC = REPO_ROOT / "docs" / "acceptance" / "license-resolution.md"
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
RUNTIME_LOCK = API_ROOT / "requirements.lock"
NPM_LOCK = REPO_ROOT / "apps" / "web" / "package-lock.json"
DOCKERFILES = (API_ROOT / "Dockerfile", REPO_ROOT / "apps" / "web" / "Dockerfile")

# Plainly permissive SPDX ids accepted without review.
PERMISSIVE = {
    "MIT",
    "MIT-0",
    "Apache-2.0",
    "ISC",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "0BSD",
    "BlueOak-1.0.0",
    "PSF-2.0",
    "Python-2.0",
    "Unlicense",
    "Zlib",
}
# Python trove classifiers and short ``License`` names accepted as plainly permissive.
PERMISSIVE_CLASSIFIERS = {
    "License :: OSI Approved :: MIT License",
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)",
    "License :: OSI Approved :: BSD License",
    "License :: OSI Approved :: Apache Software License",
    "License :: OSI Approved :: ISC License (ISCL)",
    "License :: OSI Approved :: Python Software Foundation License",
    "License :: OSI Approved :: The Unlicense (Unlicense)",
    "License :: OSI Approved :: zlib/libpng License",
}
PERMISSIVE_NAME = re.compile(
    r"^(?:MIT|BSD|Apache|ISC|PSF|Python Software Foundation|0BSD|Unlicense|Zlib)\b(?![- ]?Commons)",
    re.IGNORECASE,
)

# Documented exceptions (license-resolution.md §2): name pattern -> licence that must match.
PY_EXCEPTIONS = {
    "psycopg2-binary": re.compile(r"LGPL|Lesser General Public", re.IGNORECASE),
    "certifi": re.compile(r"MPL|Mozilla Public", re.IGNORECASE),
}
NPM_EXCEPTIONS = {
    re.compile(r"^@img/sharp-libvips-[a-z0-9-]+$"): {"LGPL-3.0-or-later"},
    re.compile(r"^@img/sharp-(?:wasm32|win32-[a-z0-9]+)$"): {
        "Apache-2.0",
        "LGPL-3.0-or-later",
        "MIT",
    },
    re.compile(r"^caniuse-lite$"): {"CC-BY-4.0"},
}

# Never allowed anywhere, dev or runtime, exception or not.
FORBIDDEN = re.compile(
    r"\bAGPL|Affero|\bSSPL|Server Side Public|\bBUSL|Business Source|Commons[- ]Clause"
    r"|\bGPL|(?<!Lesser )General Public License"
    r"|Proprietary|Commercial|\bElastic|PolyForm|\bRSAL|Redis Source Available",
    re.IGNORECASE,
)
# Copyleft or restrictive families that need a documented exception in the runtime set.
RESTRICTED = re.compile(
    r"GPL|General Public|\bMPL\b|Mozilla Public|\bEUPL\b|\bCDDL\b|\bEPL\b|Eclipse Public"
    r"|\bSSPL\b|\bBUSL\b|\bCC-BY|Creative Commons",
    re.IGNORECASE,
)


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _prod_compose() -> dict:
    return yaml.safe_load(PROD_COMPOSE.read_text(encoding="utf-8"))


def _spdx_ids(expr: str) -> set[str]:
    return {t for t in re.split(r"[\s()]+|\bAND\b|\bOR\b|\bWITH\b", expr) if t}


# --- production stack -------------------------------------------------------------------------


def test_prod_compose_bundles_no_minio():
    compose = _prod_compose()
    services = compose["services"]
    assert not any("minio" in name.lower() for name in services), "MinIO service in prod compose"
    for name, svc in services.items():
        assert "minio" not in str(svc.get("image", "")).lower(), f"{name} uses a MinIO image"
        assert not any("minio" in str(d).lower() for d in svc.get("depends_on") or []), name
    assert not any("minio" in v.lower() for v in compose.get("volumes") or {}), "MinIO volume"
    text = PROD_COMPOSE.read_text(encoding="utf-8")
    for svc in ("api", "worker"):
        endpoint = str(services[svc]["environment"]["S3_ENDPOINT"])
        assert endpoint.startswith("${S3_ENDPOINT:?"), f"{svc} must require an external S3_ENDPOINT"
    assert "http://minio" not in text


def _shipped_images() -> set[str]:
    images = {str(svc["image"]) for svc in _prod_compose()["services"].values() if svc.get("image")}
    for dockerfile in DOCKERFILES:
        text = dockerfile.read_text(encoding="utf-8")
        args = dict(re.findall(r"^ARG\s+(\w+)=(\S+)", text, re.MULTILINE))
        for ref in re.findall(r"^FROM\s+(\S+)", text, re.MULTILINE):
            m = re.fullmatch(r"\$\{(\w+)\}", ref)
            ref = args.get(m.group(1), ref) if m else ref
            if "/" in ref or ":" in ref:  # a registry image, not a build stage name
                images.add(ref.split("@", 1)[0])
    return images


def test_shipped_images_are_licence_reviewed():
    images = _shipped_images()
    assert {"caddy:2", "pgvector/pgvector:pg16", "python:3.11-slim"} <= images, images
    section = _doc().split("## 3. Production images", 1)[1].split("\n## ", 1)[0]
    for image in images:
        assert f"`{image}`" in section, f"{image} is not listed in license-resolution.md §3"


# --- API runtime dependencies -----------------------------------------------------------------


def _runtime_lock() -> list[tuple[str, str]]:
    """Runtime pins that install on this interpreter; pins whose environment marker does not
    apply (for example ``python_full_version < '3.11.3'``) are not installed and not shipped."""
    pins = re.findall(
        r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)[ \t]*(?:;[ \t]*([^\\\n]*?))?[ \t]*\\?$",
        RUNTIME_LOCK.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert pins, "no pins parsed from requirements.lock"
    return [(n, v) for n, v, marker in pins if not marker or Marker(marker).evaluate()]


def licence_problem(name: str, md) -> str | None:
    """None when the metadata ``md`` shows a permissive licence or the documented exception;
    otherwise the reason. Allowlist only: unrecognised or missing licences fail."""
    expr = (md.get("License-Expression") or "").strip()
    raw = (md.get("License") or "").strip()
    first = raw.splitlines()[0][:200] if raw else ""
    classifiers = [c for c in (md.get_all("Classifier") or []) if c.startswith("License ::")]
    described = " | ".join(p for p in (expr, first, *classifiers) if p)
    if not described:
        return "declares no licence"
    if FORBIDDEN.search(described):
        return f"forbidden licence {described!r}"
    norm = re.sub(r"[-_.]+", "-", name).lower()
    if norm in PY_EXCEPTIONS:
        if PY_EXCEPTIONS[norm].search(described):
            return None
        return f"licence {described!r} no longer matches its documented exception"
    if expr:
        bad = _spdx_ids(expr) - PERMISSIVE
        return f"{expr!r} has non-permissive ids {sorted(bad)}" if bad else None
    specific = [c for c in classifiers if c != "License :: OSI Approved"]
    if specific:
        bad = [c for c in specific if c not in PERMISSIVE_CLASSIFIERS]
        return f"non-permissive classifiers {bad}" if bad else None
    if PERMISSIVE_NAME.match(first):
        return None
    return f"licence {described!r} is not recognised as permissive"


@pytest.mark.parametrize("name,version", _runtime_lock())
def test_python_runtime_licences(name, version):
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        pytest.fail(f"{name}=={version} from requirements.lock is not installed")
    problem = licence_problem(name, dist.metadata)
    assert problem is None, f"{name}: {problem}; it needs a path in license-resolution.md §2"


def test_python_exceptions_are_current_and_documented():
    locked = {re.sub(r"[-_.]+", "-", n).lower() for n, _ in _runtime_lock()}
    doc = _doc()
    for name in PY_EXCEPTIONS:
        assert name in locked, f"stale exception {name}: remove it from the test and the doc"
        assert name in doc, f"{name} exception missing from license-resolution.md"


# --- web dependencies -------------------------------------------------------------------------


def _npm_packages() -> list[tuple[str, dict, str]]:
    packages = json.loads(NPM_LOCK.read_text(encoding="utf-8"))["packages"]
    out = []
    for path, info in packages.items():
        if not path:
            continue
        lic = info.get("license")
        lic = lic.get("type") if isinstance(lic, dict) else lic
        out.append((path.rsplit("node_modules/", 1)[-1], info, str(lic or "")))
    return out


def test_web_runtime_licences():
    problems = []
    for name, info, lic in _npm_packages():
        if info.get("dev"):
            continue
        ids = _spdx_ids(lic)
        if not ids:
            problems.append(f"{name}: no licence")
            continue
        allowed = set(PERMISSIVE)
        for pattern, extra in NPM_EXCEPTIONS.items():
            if pattern.match(name):
                allowed |= extra
        if not ids <= allowed:
            problems.append(f"{name}@{info.get('version')}: {lic}")
    listing = "\n".join(problems)
    assert not problems, f"runtime licences need a path in license-resolution.md §2:\n{listing}"


def test_no_forbidden_licence_in_any_web_package():
    bad = [f"{n}: {lic}" for n, _, lic in _npm_packages() if FORBIDDEN.search(lic)]
    assert not bad, bad


def test_web_exceptions_are_current_and_documented():
    names = [n for n, info, _ in _npm_packages() if not info.get("dev")]
    doc = _doc()
    for pattern in NPM_EXCEPTIONS:
        assert any(pattern.match(n) for n in names), f"stale exception {pattern.pattern}"
    for label in ("sharp-libvips", "caniuse-lite"):
        assert label in doc, f"{label} exception missing from license-resolution.md"


# --- guards on the checks themselves ----------------------------------------------------------


@pytest.mark.parametrize(
    "licence",
    [
        "AGPL-3.0-only",
        "GPL-3.0-or-later",
        "GPL-2.0-only",
        "SSPL-1.0",
        "BUSL-1.1",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
    ],
)
def test_forbidden_pattern_catches_strong_copyleft(licence):
    assert FORBIDDEN.search(licence)


@pytest.mark.parametrize(
    "licence",
    [
        "LGPL-3.0-or-later",
        "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)",
        "MPL-2.0",
        "MIT",
        "Apache-2.0 AND LGPL-3.0-or-later",
    ],
)
def test_forbidden_pattern_allows_weak_copyleft_and_permissive(licence):
    assert not FORBIDDEN.search(licence)


def _md(**fields) -> Message:
    msg = Message()
    for key, value in fields.items():
        for item in value if isinstance(value, list) else [value]:
            msg[key.replace("_", "-")] = item
    return msg


@pytest.mark.parametrize(
    "md",
    [
        _md(License_Expression="MIT"),
        _md(License_Expression="Apache-2.0 OR BSD-3-Clause"),
        _md(License="MIT", Classifier="License :: OSI Approved :: MIT License"),
        _md(License="Dual License", Classifier=["License :: OSI Approved :: BSD License"]),
        _md(License="BSD-3-Clause"),
        _md(
            License="Copyright (c) 2026 Someone\n\nPermission...",
            Classifier=[
                "License :: OSI Approved :: Apache Software License",
            ],
        ),
    ],
)
def test_licence_allowlist_accepts_permissive_metadata(md):
    assert licence_problem("somepkg", md) is None


@pytest.mark.parametrize(
    "md",
    [
        _md(),
        _md(License_Expression="Elastic-2.0"),
        _md(License_Expression="LicenseRef-Proprietary"),
        _md(License_Expression="MIT AND OSL-3.0"),
        _md(License="Proprietary", Classifier="License :: Other/Proprietary License"),
        _md(License="Commercial"),
        _md(Classifier="License :: OSI Approved :: Eclipse Public License 2.0 (EPL-2.0)"),
        _md(License="Copyright (c) 2026 Someone. All rights reserved."),
        _md(
            License="LGPL",
            Classifier="License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)",
        ),
        _md(License_Expression="MPL-2.0"),
    ],
)
def test_licence_allowlist_rejects_everything_else(md):
    assert licence_problem("somepkg", md) is not None


def test_documented_exceptions_still_need_their_licence_family():
    assert licence_problem("psycopg2-binary", _md(License="LGPL with exceptions")) is None
    assert licence_problem("certifi", _md(License_Expression="MPL-2.0")) is None
    assert licence_problem("certifi", _md(License_Expression="MIT")) is not None
    assert licence_problem("psycopg2-binary", _md(License_Expression="GPL-3.0-only")) is not None
