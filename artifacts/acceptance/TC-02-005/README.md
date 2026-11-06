# TC-02-005 acceptance evidence: backend lint, type and unit checks

No production host, paid API or external account was contacted. The unit run points
`TC_TEST_DATABASE_URL` at `127.0.0.1:1` (closed). Postgres was not started. No credential
values are recorded here.

## Command

Working directory `apps/api`. Interpreter: the dev lock (`requirements-dev.lock`) on Python 3.11.

```bash
TC_REQUIRE_API_QUALITY=1 python -m pytest tests/release/test_api_quality.py -q
```

The ticket command is the same pytest invocation. `TC_REQUIRE_API_QUALITY=1` is what CI sets so a
missing ruff or mypy fails the session instead of skipping. With both tools installed the two
forms run the same 21 tests.

| Item | Value |
|---|---|
| Base (origin/master when the branch was cut) | `2cfe041682ed1636bb4ac9a0c5dc53980b21de3f` |
| Code commit the transcript was run against | `5c2535c5f273cc27d46f98179fb8621b18fa6627` |
| Exit | 0 |
| Totals | **21 passed**, 0 skipped, 0 failed (2.98s) |
| Transcript | [`pytest-q.txt`](pytest-q.txt) |
| Unit suite alone, closed database port | **15 passed**, 0 skipped, 0 failed (0.61s) — [`unit-q.txt`](unit-q.txt) |
| `ruff check --select E,F,I,B` on the six critical modules | exit 0 |
| `mypy` | exit 0, no issues in 6 source files — [`lint-type.txt`](lint-type.txt) |

## Environment

| Item | Value |
|---|---|
| OS | Linux 6.12.113+ x86_64 (agent sandbox) |
| Python | 3.11.18 |
| pip | 26.3 |
| ruff | 0.5.6 (dev lock and pre-commit hook) |
| mypy | 2.4.1 (dev extra only; not in `requirements.lock`) |
| uv | 0.13.7 (`scripts/lock-python-deps.sh`) |
| Detail | [`environment.txt`](environment.txt) |

`requirements.lock` is unchanged. `requirements-dev.lock` adds mypy 2.4.1 and its dependencies
(mypy-extensions 1.2.0, pathspec 1.1.1, librt 0.16.0, ast-serialize 0.13.1).

## What the 21 tests cover

Static checks: the mypy `files` list is the six critical modules, mypy is strict on that list,
ruff has no blanket ignore, the modules have no code-less `noqa` or `type: ignore`, ruff and mypy
are exact dev pins, CI selects `E,F,I,B` and runs `mypy`, and `tests/unit` imports each critical
module with real assertions and no database hints. Denial cases feed a shrunk scope, `ignore_errors`,
`follow_imports = skip`, a blanket ruff ignore, a file-wide noqa, an unpinned ruff, and a hollow unit
file.

Execution checks: ruff and mypy pass on the committed scope; ruff fails on unsorted imports (`I001`),
a mutable default (`B006`) and an undefined name (`F821`); a `# noqa` with no code hides the undefined
name from ruff and the policy check still rejects it; mypy fails on a bare `# type: ignore`
(`ignore-without-code`); the unit suite passes against the closed port; patching unexplained failures
to `timeout` makes `test_unknown_exception_is_terminal` fail.

Independent reviewer sign-off is not part of this file. The implementer does not accept the result.
