"""TC-02-006 release checks: meaningful frontend lint, unit and formatting gates.

Acceptance:
  TC-02-006-AC1  npm lint and unit scripts actually run representative assertions
                 rather than missing/no-tests success.
  TC-02-006-AC2  Type/build/format results are captured with pinned versions.

Two layers:

* Static policy checks read repository files only. Each policy function is also
  exercised against synthetic bad inputs (denial cases) so it cannot pass vacuously.
* Execution checks run the real gates from apps/web (vitest, eslint, prettier)
  against the committed code and against synthetic failing inputs written to a
  temporary directory. They need apps/web/node_modules (``npm ci --ignore-scripts``)
  and Node 24 on PATH; without them they skip with an explicit reason. Set
  ``TC_REQUIRE_WEB_TOOLCHAIN=1`` (CI does) to turn that skip into a failure.

No network, database, credentials or production systems are touched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
WEB = REPO_ROOT / "apps" / "web"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"
UNIT_DIR = WEB / "tests" / "unit"

# Gate tools that must be exact-pinned devDependencies and match the lock.
GATE_TOOLS = (
    "eslint",
    "@eslint/js",
    "typescript-eslint",
    "eslint-plugin-react-hooks",
    "@next/eslint-plugin-next",
    "globals",
    "prettier",
    "vitest",
    "typescript",
)
# Rule sets the flat config must extend (source text references).
REQUIRED_RULESETS = (
    "js.configs.recommended",
    "tseslint.configs.recommended",
    "reactHooks.configs.flat.recommended",
    "nextPlugin.configs['core-web-vitals']",
)
# Rules allowed to be switched off globally, each with a documented reason in
# docs/release/tickets/TC-02-006.md. TC-02-006b removed set-state-in-effect
# from this set; that rule is now enforced.
ALLOWED_OFF_RULES = {
    "@typescript-eslint/no-require-imports",  # CommonJS config/scripts only
}
# Rules that must never be disabled globally.
CORE_RULES = (
    "react-hooks/rules-of-hooks",
    "react-hooks/exhaustive-deps",
    "react-hooks/set-state-in-effect",
    "@typescript-eslint/no-unused-vars",
    "@typescript-eslint/no-explicit-any",
    "no-undef",
)
# Generated paths that live under a source directory but may be ignored.
GENERATED_UNDER_SOURCE = {"e2e/.auth/"}  # Playwright storage state, never hand-written
SOURCE_DIRS = ("app", "components", "contexts", "lib", "e2e", "scripts", "tests")
NOOP_PATTERNS = (
    (re.compile(r"\|\|\s*true\b"), "swallows failure with '|| true'"),
    (re.compile(r"\bexit\s+0\b"), "forces 'exit 0'"),
    (re.compile(r"^\s*(echo|true|:)\b"), "is a no-op command"),
    (re.compile(r"--passWithNoTests\b"), "passes with no tests"),
    (re.compile(r"--no-error-on-unmatched-pattern\b"), "ignores unmatched files"),
    (re.compile(r"--max-warnings[ =](?!0\b)\d+"), "tolerates lint warnings"),
    (re.compile(r"--quiet\b"), "hides lint warnings"),
)
SKIP_MARKERS = re.compile(r"\b(?:it|test|describe)\.(?:skip|only|todo)\b|\bx(?:it|describe)\(")


# --------------------------------------------------------------------------- helpers


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def script_problems(name: str, command: str | None, required: str) -> list[str]:
    """Problems with an npm script that must run ``required`` meaningfully."""
    if not command or not command.strip():
        return [f"{name}: missing"]
    problems = [f"{name}: {why}" for rx, why in NOOP_PATTERNS if rx.search(command)]
    if not re.search(required, command):
        problems.append(f"{name}: does not run {required!r}")
    return problems


def gate_script_problems(pkg: dict) -> list[str]:
    scripts = pkg.get("scripts") or {}
    problems = []
    problems += script_problems("lint", scripts.get("lint"), r"^eslint \. --max-warnings=0$")
    problems += script_problems("test:unit", scripts.get("test:unit"), r"^vitest run$")
    problems += script_problems("format:check", scripts.get("format:check"), r"^prettier --check ")
    problems += script_problems("typecheck", scripts.get("typecheck"), r"\btsc --noEmit\b")
    problems += script_problems("build", scripts.get("build"), r"^next build$")
    return problems


def pinned_tool_problems(pkg: dict, lock: dict) -> list[str]:
    dev = pkg.get("devDependencies") or {}
    packages = lock.get("packages") or {}
    problems = []
    for tool in GATE_TOOLS:
        spec = dev.get(tool)
        if spec is None:
            problems.append(f"{tool}: not a devDependency")
            continue
        if not re.fullmatch(r"\d+\.\d+\.\d+", spec):
            problems.append(f"{tool}@{spec}: not an exact pin")
        entry = packages.get(f"node_modules/{tool}") or {}
        if entry.get("version") != spec:
            problems.append(f"{tool}: lock has {entry.get('version')!r}, package.json {spec!r}")
        if not entry.get("dev"):
            problems.append(f"{tool}: locked as a runtime dependency")
    return problems


def eslint_config_problems(text: str) -> list[str]:
    problems = [f"missing rule set {r}" for r in REQUIRED_RULESETS if r not in text]
    code = "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("//"))
    off = set(re.findall(r"""['"]([\w@/-]+)['"]\s*:\s*\[?\s*(?:['"]off['"]|0(?![\d.]))""", code))
    for rule in sorted(off - ALLOWED_OFF_RULES):
        problems.append(f"rule {rule} switched off")
    for rule in CORE_RULES:
        if rule in off:
            problems.append(f"core rule {rule} disabled")
    if re.search(r"""globalIgnores\(\s*\[[^\]]*['"](?:app|components|lib|contexts)/?""", code):
        problems.append("source directory globally ignored")
    return problems


def blanket_disable_problems(files: dict[str, str]) -> list[str]:
    """eslint-disable comments must name rules; no file-wide or unscoped disables."""
    problems = []
    for name, text in files.items():
        for m in re.finditer(r"eslint-disable(-next-line|-line)?([^\n*]*)", text):
            kind, rest = m.group(1), m.group(2).split("--")[0].strip()
            if not kind:
                problems.append(f"{name}: file/block-wide eslint-disable")
            elif not rest:
                problems.append(f"{name}: unscoped eslint-disable{kind}")
    return problems


def unit_suite_problems(tests: dict[str, str], modules: dict[str, str]) -> list[str]:
    problems = []
    if not tests:
        return ["no unit test files"]
    for name, text in tests.items():
        if len(re.findall(r"\bexpect\(", text)) < 2:
            problems.append(f"{name}: fewer than 2 assertions")
        if SKIP_MARKERS.search(text):
            problems.append(f"{name}: contains skip/only/todo")
    imports = "\n".join(tests.values())
    for mod, src in modules.items():
        if not re.search(r"^export\s+(?:async\s+)?(?:function|const|class)\b", src, re.M):
            continue  # type-only module, nothing executable to test
        if f"'@/{mod}'" not in imports and f'"@/{mod}"' not in imports:
            problems.append(f"{mod}: runtime module has no unit test")
    return problems


def vitest_config_problems(text: str) -> list[str]:
    problems = []
    if re.search(r"passWithNoTests\s*:\s*true", text):
        problems.append("passWithNoTests enabled")
    if "tests/unit/" not in text:
        problems.append("tests/unit not included")
    return problems


def ci_steps(ci: str) -> list[str]:
    return [b for b in re.split(r"\n(?=\s+- name:)", ci) if "- name:" in b]


def ci_gate_problems(ci: str) -> list[str]:
    steps = ci_steps(ci)
    problems = []
    for gate in ("lint", "format:check", "test:unit", "typecheck", "build"):
        hits = [
            s
            for s in steps
            if re.search(rf"run:\s*npm run {re.escape(gate)}\s*$", s, re.M)
            and "working-directory: apps/web" in s
        ]
        if not hits:
            problems.append(f"CI does not run npm run {gate} in apps/web")
        elif any("continue-on-error" in s or "if: false" in s for s in hits):
            problems.append(f"CI step for {gate} may not fail the build")
    versions = [s for s in steps if "eslint --version" in s]
    if not versions:
        problems.append("CI does not record gate tool versions")
    else:
        for tool in ("node", "tsc", "eslint", "prettier", "vitest"):
            if f"{tool} --version" not in versions[0]:
                problems.append(f"CI version step omits {tool}")
    if not re.search(r"npm ci --ignore-scripts", ci):
        problems.append("CI does not install from the lock")
    return problems


def prettierignore_problems(text: str) -> list[str]:
    entries = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    problems = []
    for e in entries:
        if e in GENERATED_UNDER_SOURCE:
            continue
        top = e.strip("/").split("/")[0]
        if (
            e in ("*", "**", "**/*")
            or top in SOURCE_DIRS
            or e.endswith((".ts", ".tsx"))
            and (e != "next-env.d.ts")
        ):
            problems.append(f"ignores source: {e}")
    return problems


def _read_tree(root: Path, pattern: str) -> dict[str, str]:
    return {
        str(p.relative_to(WEB)): p.read_text(encoding="utf-8")
        for p in sorted(root.glob(pattern))
        if "node_modules" not in p.parts and ".next" not in p.parts
    }


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def pkg() -> dict:
    return _load_json(WEB / "package.json")


@pytest.fixture(scope="module")
def lock() -> dict:
    return _load_json(WEB / "package-lock.json")


@pytest.fixture(scope="module")
def ci() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- static: AC1


def test_gate_scripts_exist_and_are_not_noops(pkg):
    assert gate_script_problems(pkg) == []


def test_eslint_config_extends_real_rule_sets(pkg):
    text = (WEB / "eslint.config.mjs").read_text(encoding="utf-8")
    assert eslint_config_problems(text) == []


def test_lint_suppressions_are_rule_scoped():
    files: dict[str, str] = {}
    for d in SOURCE_DIRS:
        for ext in ("ts", "tsx", "js", "mjs"):
            files.update(_read_tree(WEB / d, f"**/*.{ext}"))
    files.update(_read_tree(WEB, "*.ts"))
    assert len(files) > 50
    assert blanket_disable_problems(files) == []


def test_unit_suite_covers_runtime_modules_with_real_assertions():
    tests = _read_tree(UNIT_DIR, "**/*.test.ts") | _read_tree(WEB / "lib", "**/*.test.ts")
    modules = {
        f"lib/{p.stem}": p.read_text(encoding="utf-8")
        for p in sorted((WEB / "lib").glob("*.ts"))
        if not p.name.endswith(".test.ts")
    }
    modules["middleware"] = (WEB / "middleware.ts").read_text(encoding="utf-8")
    modules["app/api/[[...path]]/route"] = (WEB / "app/api/[[...path]]/route.ts").read_text(
        encoding="utf-8"
    )
    assert len(tests) >= 6
    assert unit_suite_problems(tests, modules) == []


def test_vitest_fails_on_empty_suite():
    assert vitest_config_problems((WEB / "vitest.config.ts").read_text(encoding="utf-8")) == []


def test_prettier_ignore_only_covers_generated_output():
    text = (WEB / ".prettierignore").read_text(encoding="utf-8")
    assert prettierignore_problems(text) == []
    for generated in ("node_modules/", ".next/", "playwright-report/", "test-results/"):
        assert generated in text


def test_pre_commit_prettier_hook_uses_app_ignore_file():
    text = PRE_COMMIT.read_text(encoding="utf-8")
    assert "prettier --check --ignore-path apps/web/.prettierignore" in text


def test_ci_runs_every_frontend_gate(ci):
    assert ci_gate_problems(ci) == []


# --------------------------------------------------------------------------- static: AC2


def test_gate_tools_are_pinned_and_locked(pkg, lock):
    assert pinned_tool_problems(pkg, lock) == []


# --------------------------------------------------------------------------- denial cases


def test_rejects_noop_or_missing_scripts():
    bad = {
        "scripts": {
            "lint": "eslint . || true",
            "test:unit": "vitest run --passWithNoTests",
            "format:check": "echo skipped",
            "typecheck": "exit 0",
        }
    }
    problems = gate_script_problems(bad)
    assert any("lint: swallows failure" in p for p in problems)
    assert any("test:unit: passes with no tests" in p for p in problems)
    assert any("format:check: is a no-op" in p for p in problems)
    assert any("typecheck: forces 'exit 0'" in p for p in problems)
    assert "build: missing" in problems
    assert gate_script_problems({"scripts": {"lint": "eslint . --max-warnings=10"}})[0] == (
        "lint: tolerates lint warnings"
    )


def test_rejects_weak_eslint_config():
    weak = """
    export default [
      js.configs.recommended,
      { rules: { 'react-hooks/rules-of-hooks': 'off', 'no-undef': 0 } },
      { rules: { '@typescript-eslint/no-explicit-any': ['off'], 'no-console': 'warn' } },
      globalIgnores(['app/**']),
    ]
    """
    problems = eslint_config_problems(weak)
    assert "missing rule set tseslint.configs.recommended" in problems
    assert "core rule react-hooks/rules-of-hooks disabled" in problems
    assert "core rule no-undef disabled" in problems
    assert "core rule @typescript-eslint/no-explicit-any disabled" in problems
    assert not any("no-console" in p for p in problems)
    assert "source directory globally ignored" in problems


def test_rejects_blanket_disables():
    files = {
        "a.ts": "/* eslint-disable */\nconst x = 1\n",
        "b.ts": "// eslint-disable-next-line\nfoo()\n",
        "c.ts": "// eslint-disable-next-line no-console -- reason\nconsole.log(1)\n",
    }
    assert blanket_disable_problems(files) == [
        "a.ts: file/block-wide eslint-disable",
        "b.ts: unscoped eslint-disable-next-line",
    ]


def test_rejects_hollow_unit_suite():
    modules = {"lib/x": "export function x() { return 1 }", "lib/t": "export type T = 1"}
    assert unit_suite_problems({}, modules) == ["no unit test files"]
    problems = unit_suite_problems(
        {"tests/unit/a.test.ts": "it.skip('x', () => { expect(1).toBe(1) })"}, modules
    )
    assert "tests/unit/a.test.ts: fewer than 2 assertions" in problems
    assert "tests/unit/a.test.ts: contains skip/only/todo" in problems
    assert "lib/x: runtime module has no unit test" in problems
    assert not any("lib/t" in p for p in problems)
    assert vitest_config_problems("test: { passWithNoTests: true }") == [
        "passWithNoTests enabled",
        "tests/unit not included",
    ]


def test_rejects_ci_without_gates():
    ci = """
      - name: Install
        working-directory: apps/web
        run: npm install
      - name: Lint
        working-directory: apps/web
        continue-on-error: true
        run: npm run lint
    """
    problems = ci_gate_problems(ci)
    assert "CI step for lint may not fail the build" in problems
    assert "CI does not run npm run test:unit in apps/web" in problems
    assert "CI does not record gate tool versions" in problems
    assert "CI does not install from the lock" in problems


def test_rejects_unpinned_or_drifted_tools():
    pkg = {"devDependencies": {t: "1.0.0" for t in GATE_TOOLS} | {"eslint": "^10.0.0"}}
    lock = {
        "packages": {f"node_modules/{t}": {"version": "1.0.0", "dev": True} for t in GATE_TOOLS}
    }
    lock["packages"]["node_modules/vitest"] = {"version": "1.0.1", "dev": True}
    lock["packages"]["node_modules/prettier"] = {"version": "1.0.0"}
    del pkg["devDependencies"]["globals"]
    problems = pinned_tool_problems(pkg, lock)
    assert "eslint@^10.0.0: not an exact pin" in problems
    assert "vitest: lock has '1.0.1', package.json '1.0.0'" in problems
    assert "prettier: locked as a runtime dependency" in problems
    assert "globals: not a devDependency" in problems


def test_rejects_prettierignore_hiding_source():
    text = "app/\nlib/foo.ts\n**/*\nnext-env.d.ts\ne2e/.auth/\ne2e/\n"
    assert prettierignore_problems(text) == [
        "ignores source: app/",
        "ignores source: lib/foo.ts",
        "ignores source: **/*",
        "ignores source: e2e/",
    ]


# --------------------------------------------------------------------------- execution


def _toolchain_reason() -> str | None:
    node = shutil.which("node")
    if not node:
        return "node not on PATH"
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)
    if not out.stdout.startswith("v24."):
        return f"Node 24 required, found {out.stdout.strip()!r}"
    for tool in ("eslint", "prettier", "vitest"):
        if not (WEB / "node_modules" / ".bin" / tool).exists():
            return f"apps/web/node_modules/.bin/{tool} missing (run npm ci --ignore-scripts)"
    return None


_REASON = _toolchain_reason()
if _REASON and os.environ.get("TC_REQUIRE_WEB_TOOLCHAIN") == "1":
    raise RuntimeError(f"TC_REQUIRE_WEB_TOOLCHAIN=1 but web toolchain unavailable: {_REASON}")
needs_toolchain = pytest.mark.skipif(
    _REASON is not None, reason=f"web toolchain unavailable: {_REASON}"
)


def _bin(tool: str) -> str:
    return str(WEB / "node_modules" / ".bin" / tool)


def _run(args: list[str], cwd: Path = WEB, stdin: str | None = None, timeout: int = 300):
    env = {**os.environ, "CI": "1", "NO_COLOR": "1", "FORCE_COLOR": "0"}
    return subprocess.run(
        args,
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


@pytest.fixture()
def web_tmp():
    """Scratch dir inside apps/web so node resolution finds the pinned toolchain."""
    path = Path(tempfile.mkdtemp(prefix=".tc-gate-probe-", dir=WEB))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@needs_toolchain
def test_unit_script_runs_real_assertions_and_passes(web_tmp):
    report = web_tmp / "vitest.json"
    res = _run([_bin("vitest"), "run", "--reporter=json", f"--outputFile={report}"])
    assert res.returncode == 0, res.stdout + res.stderr
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["numTotalTestSuites"] > 0
    assert data["numTotalTests"] >= 30
    assert data["numFailedTests"] == 0
    assert data["numPendingTests"] == 0 and data["numTodoTests"] == 0
    assert data["numPassedTests"] == data["numTotalTests"]
    files = {Path(r["name"]).name for r in data["testResults"]}
    assert {"middleware.test.ts", "api-proxy.test.ts", "api-error.test.ts"} <= files


@needs_toolchain
def test_unit_runner_fails_when_no_tests_match():
    res = _run([_bin("vitest"), "run", "tc-gate-no-such-test-file"])
    assert res.returncode != 0
    assert "No test files found" in res.stdout + res.stderr


@needs_toolchain
def test_unit_runner_fails_on_a_failing_assertion(web_tmp):
    (web_tmp / "probe.test.ts").write_text(
        "import { expect, it } from 'vitest'\n"
        "it('synthetic failure', () => { expect(1 + 1).toBe(3) })\n",
        encoding="utf-8",
    )
    res = _run([_bin("vitest"), "run", "--root", str(web_tmp)])
    assert res.returncode != 0
    assert "synthetic failure" in res.stdout + res.stderr


@needs_toolchain
def test_lint_script_passes_on_committed_code():
    res = _run(["npm", "run", "--silent", "lint"])
    assert res.returncode == 0, res.stdout + res.stderr


@needs_toolchain
def test_lint_rejects_hooks_unused_and_any_violations():
    probe = (
        "import { useState } from 'react'\n"
        "export function Probe({ on }: { on: boolean }) {\n"
        "  const unused = 1\n"
        "  if (on) {\n"
        "    const [v] = useState(0)\n"
        "    return v\n"
        "  }\n"
        "  const x: any = null\n"
        "  return x\n"
        "}\n"
    )
    res = _run(
        [
            _bin("eslint"),
            "--max-warnings=0",
            "--format=json",
            "--stdin",
            "--stdin-filename",
            "components/__tc_gate_probe.tsx",
        ],
        stdin=probe,
    )
    assert res.returncode == 1, res.stdout + res.stderr
    rules = {m["ruleId"] for f in json.loads(res.stdout) for m in f["messages"]}
    assert {
        "react-hooks/rules-of-hooks",
        "@typescript-eslint/no-unused-vars",
        "@typescript-eslint/no-explicit-any",
    } <= rules


@needs_toolchain
def test_lint_rejects_next_specific_violation():
    probe = 'export function Pic() {\n  return <img src="/a.png" alt="a" />\n}\n'
    res = _run(
        [
            _bin("eslint"),
            "--max-warnings=0",
            "--format=json",
            "--stdin",
            "--stdin-filename",
            "components/__tc_gate_probe.tsx",
        ],
        stdin=probe,
    )
    assert res.returncode == 1, res.stdout + res.stderr
    rules = {m["ruleId"] for f in json.loads(res.stdout) for m in f["messages"]}
    assert "@next/next/no-img-element" in rules


@needs_toolchain
def test_lint_accepts_clean_code():
    clean = "export function sum(a: number, b: number): number {\n  return a + b\n}\n"
    res = _run(
        [_bin("eslint"), "--max-warnings=0", "--stdin", "--stdin-filename", "lib/__probe.ts"],
        stdin=clean,
    )
    assert res.returncode == 0, res.stdout + res.stderr


@needs_toolchain
def test_format_check_passes_on_committed_code():
    res = _run(["npm", "run", "--silent", "format:check"])
    assert res.returncode == 0, res.stdout + res.stderr


@needs_toolchain
def test_format_check_rejects_unformatted_code(web_tmp):
    bad = web_tmp / "bad.ts"
    bad.write_text('export const x = {a:1,  "b" : 2};\n', encoding="utf-8")
    good = web_tmp / "good.ts"
    good.write_text("export const x = { a: 1, b: 2 }\n", encoding="utf-8")
    res_bad = _run([_bin("prettier"), "--check", str(bad)])
    res_good = _run([_bin("prettier"), "--check", str(good)])
    assert res_bad.returncode == 1, res_bad.stdout + res_bad.stderr
    assert res_good.returncode == 0, res_good.stdout + res_good.stderr


@needs_toolchain
def test_installed_gate_tools_match_pins(pkg):
    dev = pkg["devDependencies"]
    for tool in GATE_TOOLS:
        installed = _load_json(WEB / "node_modules" / tool / "package.json")["version"]
        assert installed == dev[tool], f"{tool}: installed {installed}, pinned {dev[tool]}"
