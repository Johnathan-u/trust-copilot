"""TC-02-003 release checks: frontend dependencies are supported, patched and locked.

Acceptance:
  TC-02-003-AC1  Build and type checks pass with supported patched runtime packages.
  TC-02-003-AC2  Production image excludes dev servers/test tools and unresolved
                 reachable high vulnerabilities.

These tests are static and deterministic: they read repository files only (no
network, no database, no npm/docker invocation). The build, type-check, npm audit
and image-scan results that complement them are recorded under
artifacts/acceptance/TC-02-003/. Each policy check is also exercised against
synthetic bad inputs (denial/failure cases) so a check cannot pass vacuously.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
WEB = REPO_ROOT / "apps" / "web"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# Supported, patched release lines for runtime packages (policy as of 2026-10-27).
# Next.js <16.4.3 and every 14.x/15.x release carry open critical/high advisories;
# React 19 is required by Next 16; Node 24 is the Active LTS line.
SUPPORTED_RUNTIME = {
    "next": (16, (16, 4, 3)),
    "react": (19, (19, 3, 1)),
    "react-dom": (19, (19, 3, 1)),
}
SUPPORTED_NODE_MAJOR = 24
MIN_NODE = (24, 11, 0)  # first Node 24 LTS release

# Packages that must never be reachable from the production image.
DEV_ONLY_TOOLS = {
    "typescript",
    "vitest",
    "playwright",
    "@playwright/test",
    "prettier",
    "eslint",
    "tailwindcss",
    "postcss",
    "autoprefixer",
    "vite",
    "esbuild",
}
# Locked packages allowed to declare install scripts (we install with --ignore-scripts).
INSTALL_SCRIPT_ALLOWLIST = {"node_modules/fsevents"}  # macOS-only optional dependency

EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


# --------------------------------------------------------------------------- helpers


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _ver(text: str) -> tuple[int, int, int]:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", text.strip())
    if not m:
        raise ValueError(f"not a semantic version: {text!r}")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def unpinned_dependencies(pkg: dict) -> list[str]:
    """Return 'name@spec' for every direct dependency not pinned to an exact version."""
    bad = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, spec in (pkg.get(section) or {}).items():
            if not EXACT_VERSION.match(spec):
                bad.append(f"{name}@{spec}")
    return bad


def lock_mismatches(pkg: dict, lock: dict) -> list[str]:
    """Return problems where package-lock.json does not lock exactly what package.json pins."""
    problems = []
    if lock.get("lockfileVersion") != 3:
        problems.append(f"lockfileVersion={lock.get('lockfileVersion')} (expected 3)")
    packages = lock.get("packages") or {}
    root = packages.get("", {})
    for section in ("dependencies", "devDependencies"):
        want = pkg.get(section) or {}
        have = root.get(section) or {}
        if want != have:
            problems.append(f"lock root {section} differs from package.json")
        for name, spec in want.items():
            entry = packages.get(f"node_modules/{name}")
            if entry is None:
                problems.append(f"{name} missing from lock")
            elif entry.get("version") != spec:
                problems.append(f"{name} locked at {entry.get('version')} not {spec}")
    for path, entry in packages.items():
        if not path or entry.get("link"):
            continue
        resolved = entry.get("resolved", "")
        if not resolved.startswith("https://registry.npmjs.org/"):
            problems.append(f"{path} resolved from non-registry source {resolved!r}")
        if not str(entry.get("integrity", "")).startswith("sha512-"):
            problems.append(f"{path} lacks sha512 integrity")
    return problems


def unsupported_runtime(pkg: dict) -> list[str]:
    problems = []
    deps = pkg.get("dependencies") or {}
    for name, (major, minimum) in SUPPORTED_RUNTIME.items():
        spec = deps.get(name)
        if spec is None:
            problems.append(f"{name} missing")
            continue
        v = _ver(spec)
        if v[0] != major or v < minimum:
            problems.append(f"{name}@{spec} not in supported patched line {major}.x >= {minimum}")
    return problems


def install_script_packages(lock: dict) -> set[str]:
    return {
        path
        for path, entry in (lock.get("packages") or {}).items()
        if entry.get("hasInstallScript")
    }


def dockerfile_stages(text: str) -> dict[str, str]:
    """Split a Dockerfile into {stage_name: body}."""
    stages: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^FROM\s+\S+\s+AS\s+(\S+)", line, re.IGNORECASE)
        if m:
            current = m.group(1).lower()
            stages[current] = ""
            continue
        if current:
            stages[current] += line + "\n"
    return stages


def production_stage_problems(dockerfile: str) -> list[str]:
    stages = dockerfile_stages(dockerfile)
    prod = stages.get("production")
    if prod is None:
        return ["no production stage"]
    problems = []
    code = "\n".join(ln for ln in prod.splitlines() if not ln.lstrip().startswith("#"))
    if re.search(r"COPY\s+--from=builder[^\n]*\s/app\s+/app", code):
        problems.append("copies the whole builder workspace (node_modules, sources, tools)")
    if ".next/standalone" not in code:
        problems.append("does not ship Next standalone output")
    if re.search(r"\bnpm\s+(install|ci|i)\b", code):
        problems.append("installs packages in the production stage")
    flat = re.sub(r'["\[\],]', " ", code)  # normalise exec-form CMD/RUN arrays
    if re.search(r"\bnext\s+dev\b|\bnpm\s+run\s+dev\b", flat):
        problems.append("starts a dev server")
    if 'CMD ["node", "server.js"]' not in code:
        problems.append("does not start the standalone server")
    if not re.search(r"^USER\s+(?!root\b|0\b)\S+", code, re.MULTILINE):
        problems.append("runs as root")
    if "/usr/local/lib/node_modules/npm" not in code:
        problems.append("keeps npm in the runtime image")
    for tool in DEV_ONLY_TOOLS:
        if re.search(rf"node_modules/{re.escape(tool)}\b", code):
            problems.append(f"copies dev tool {tool}")
    return problems


def node_image_version(dockerfile: str) -> tuple[int, int, int]:
    m = re.search(
        r"^ARG\s+NODE_IMAGE=node:(\d+\.\d+\.\d+)-[\w.-]+@sha256:[0-9a-f]{64}$",
        dockerfile,
        re.MULTILINE,
    )
    if not m:
        raise ValueError("NODE_IMAGE must be an exact node:<x.y.z>-<variant>@sha256 digest")
    return _ver(m.group(1))


def node_version_problems(nvmrc: str, pkg: dict, dockerfile: str, ci: str) -> list[str]:
    problems = []
    pinned = _ver(nvmrc)
    if pinned[0] != SUPPORTED_NODE_MAJOR or pinned < MIN_NODE:
        problems.append(
            f".nvmrc {nvmrc.strip()} is not a supported Node {SUPPORTED_NODE_MAJOR} LTS"
        )
    engines = (pkg.get("engines") or {}).get("node", "")
    if f"<{SUPPORTED_NODE_MAJOR + 1}" not in engines or f">={MIN_NODE[0]}." not in engines:
        problems.append(f"engines.node {engines!r} does not bound Node to {SUPPORTED_NODE_MAJOR}.x")
    try:
        if node_image_version(dockerfile) != pinned:
            problems.append("Dockerfile NODE_IMAGE differs from .nvmrc")
    except ValueError as exc:
        problems.append(str(exc))
    if "node-version-file: apps/web/.nvmrc" not in ci:
        problems.append("CI does not take the Node version from apps/web/.nvmrc")
    return problems


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def pkg() -> dict:
    return _load_json(WEB / "package.json")


@pytest.fixture(scope="module")
def lock() -> dict:
    return _load_json(WEB / "package-lock.json")


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (WEB / "Dockerfile").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ci() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


# --------------------------------------------------------------- AC1: supported + locked


def test_all_direct_dependencies_are_exact_pins(pkg):
    assert unpinned_dependencies(pkg) == []


def test_lockfile_locks_exactly_the_pinned_versions_from_the_registry(pkg, lock):
    assert lock_mismatches(pkg, lock) == []


def test_runtime_packages_are_on_supported_patched_lines(pkg):
    assert unsupported_runtime(pkg) == []


def test_npmrc_enforces_engines_and_exact_saves():
    lines = {ln.strip() for ln in (WEB / ".npmrc").read_text().splitlines()}
    assert "engine-strict=true" in lines
    assert "save-exact=true" in lines


def test_node_version_is_single_sourced_and_supported(pkg, dockerfile, ci):
    nvmrc = (WEB / ".nvmrc").read_text(encoding="utf-8")
    assert node_version_problems(nvmrc, pkg, dockerfile, ci) == []


def test_ci_installs_from_lock_and_runs_typecheck_build_and_audit(ci):
    assert "npm ci --ignore-scripts" in ci
    assert re.search(r"^\s+run: npm install\s*$", ci, re.MULTILINE) is None
    assert "npm run typecheck" in ci
    assert "npm run build" in ci
    assert "npm audit --omit=dev --audit-level=high" in ci


def test_typecheck_script_generates_route_types_before_tsc(pkg):
    assert pkg["scripts"]["typecheck"] == "next typegen && tsc --noEmit -p ."


def test_only_allowlisted_packages_declare_install_scripts(lock):
    assert install_script_packages(lock) <= INSTALL_SCRIPT_ALLOWLIST


# ------------------------------------------------------- AC2: production image contents


def test_next_emits_standalone_server():
    cfg = (WEB / "next.config.js").read_text(encoding="utf-8")
    assert re.search(r"output:\s*'standalone'", cfg)


def test_production_stage_ships_only_standalone_runtime(dockerfile):
    assert production_stage_problems(dockerfile) == []


def test_build_stages_install_from_lock_without_scripts(dockerfile):
    stages = dockerfile_stages(dockerfile)
    assert "npm ci --ignore-scripts" in stages.get("deps", "")
    code = [ln for ln in dockerfile.splitlines() if not ln.lstrip().startswith("#")]
    assert not any(re.search(r"\bnpm\s+(install|i)\b", ln) for ln in code)


def test_dev_tools_are_dev_dependencies_only(pkg):
    runtime = set(pkg.get("dependencies") or {})
    assert runtime.isdisjoint(DEV_ONLY_TOOLS)


def test_dockerignore_keeps_local_state_out_of_build_context():
    entries = (REPO_ROOT / ".dockerignore").read_text().split()
    for required in ("node_modules", ".next", ".env", "playwright-report", "test-results"):
        assert required in entries


# ------------------------------------------- denial/failure cases on synthetic inputs


def test_rejects_range_specs_and_tags():
    synthetic = {
        "dependencies": {"next": "^16.4.3", "react": "latest"},
        "devDependencies": {"vitest": "~5.0.5", "typescript": "6.0.3"},
    }
    assert unpinned_dependencies(synthetic) == [
        "next@^16.4.3",
        "react@latest",
        "vitest@~5.0.5",
    ]


def test_rejects_unsupported_or_unpatched_runtime():
    assert unsupported_runtime(
        {"dependencies": {"next": "14.2.15", "react": "18.2.0", "react-dom": "18.2.0"}}
    )
    assert unsupported_runtime(
        {"dependencies": {"next": "16.4.2", "react": "19.3.1", "react-dom": "19.3.1"}}
    ) == ["next@16.4.2 not in supported patched line 16.x >= (16, 4, 3)"]


def test_rejects_drifted_or_untrusted_lock():
    pkg = {"dependencies": {"next": "16.4.3"}, "devDependencies": {}}
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"dependencies": {"next": "16.4.3"}},
            "node_modules/next": {
                "version": "16.4.2",
                "resolved": "https://evil.example/next.tgz",
                "integrity": "sha1-abc",
            },
        },
    }
    problems = lock_mismatches(pkg, lock)
    assert "next locked at 16.4.2 not 16.4.3" in problems
    assert any("non-registry source" in p for p in problems)
    assert any("lacks sha512 integrity" in p for p in problems)
    assert lock_mismatches(pkg, {"lockfileVersion": 2, "packages": {}})


def test_rejects_baseline_style_production_image():
    baseline = (
        "FROM node:20 AS builder\nRUN npm ci\nRUN npm run build\n"
        "FROM node:20 AS production\nENV NODE_ENV=production\n"
        "COPY --from=builder /app /app\n"
        'CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]\n'
    )
    problems = production_stage_problems(baseline)
    assert "copies the whole builder workspace (node_modules, sources, tools)" in problems
    assert "runs as root" in problems
    assert "does not ship Next standalone output" in problems
    dev_server = baseline.replace('CMD ["npm"', 'CMD ["npx", "next", "dev"]\n#')
    assert "starts a dev server" in production_stage_problems(dev_server)


def test_rejects_unsupported_or_inconsistent_node():
    pkg = {"engines": {"node": ">=24.11.0 <25"}}
    docker = "ARG NODE_IMAGE=node:24.22.1-trixie-slim@sha256:" + "a" * 64 + "\n"
    ci = "node-version-file: apps/web/.nvmrc"
    assert node_version_problems("24.22.1\n", pkg, docker, ci) == []
    assert node_version_problems("20.19.2\n", pkg, docker, ci)  # EOL major
    assert "Dockerfile NODE_IMAGE differs from .nvmrc" in node_version_problems(
        "24.21.0\n", pkg, docker, ci
    )
    unpinned = node_version_problems("24.22.1\n", pkg, "ARG NODE_IMAGE=node:24\n", ci)
    assert any("sha256 digest" in p for p in unpinned)
    assert node_version_problems("24.22.1\n", pkg, docker, 'node-version: "20"')
