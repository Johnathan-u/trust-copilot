# TC-02-007c local verification

Base commit: `b2bd1e0df5cdeb03b8d0cd240f5a161835ea621d`.
The baseline log uses that unchanged test. All repaired runs use the test changes
in this commit; the coordinator records the final commit SHA and required CI.
Test-source SHA-256:
`05078df8f30828df00e81afa8909355cf290b28c5d872ec22d2a33120b41be51`.
No external provider was called. No test credential or signed cookie is printed
in the committed evidence.

## Root cause and controls

The route sets `max_age = expires_at - int(time.time())` before returning the
response. The original assertion used a second `time.time()` after the response,
so a one-second crossing falsely rejected a valid cookie. The diagnostic wraps
only the existing test's `reissue` call: it holds time during the real route and
advances one second after the real response. It does not replace authentication,
signing, storage or the response.

| Evidence | Result | Meaning |
| --- | --- | --- |
| `baseline_crossing.txt` | 3 failed, exit 1 | All three original assertions reject a valid header after the controlled crossing. |
| `repaired_crossing.txt` | 3 passed, exit 0 | The exact issuance-time assertion survives the same crossing and reaches expiry checks. |
| `extended_cookie_negative_control.txt` | 3 failed, exit 1 | A deliberately incorrect extra second in the emitted cookie remains rejected. |
| `session_regressions.txt` | 118 passed, 117 deselected, exit 0 | Existing SQLite/unit session controls pass; PostgreSQL cases are not local qualification. |
| `local_full_suite.txt` | Interrupted, exit 2 | Safe aggregate report names all 18 failures and 39 errors from the attempted full suite. |

The focused runs emit existing `datetime.utcnow()` deprecation warnings under
Python 3.12. The broad regression run reports 1,196 warnings. No warning or test
is disabled by this repair.

## Commands

From the repository root, using the available virtual environment:

```sh
/tmp/tc-backend-venv/bin/python artifacts/acceptance/TC-02-007c/clock_boundary_probe.py crossing
/tmp/tc-backend-venv/bin/python artifacts/acceptance/TC-02-007c/clock_boundary_probe.py extend-cookie
/tmp/tc-backend-venv/bin/ruff check apps/api/tests/release/test_session_persistence.py artifacts/acceptance/TC-02-007c/clock_boundary_probe.py
git diff --check
```

The first command was run before the test edit to capture the red baseline, then
after the edit to capture green. The second command must fail and reports the
deliberately extended cookie. The probe is outside pytest's collection path.

From `apps/api`:

```sh
TC_TEST_DATABASE_URL='postgresql://127.0.0.1:1/trustcopilot_test?connect_timeout=1' /tmp/tc-backend-venv/bin/python -m pytest tests/release/test_session_persistence.py tests/release/test_remember_policy.py tests/release/test_session_validation.py -k 'not postgres' -q
TC_TEST_DATABASE_URL='postgresql://127.0.0.1:1/trustcopilot_test?connect_timeout=1' timeout 300 /tmp/tc-backend-venv/bin/python -m pytest -rs
```

## Environment and limitations

The reused environment has Python 3.12.14, pytest 9.1.1, SQLAlchemy 2.0.55,
FastAPI 0.162.0, pyotp 2.10.0 and Ruff 0.5.6. These listed package versions match
`requirements-dev.lock`; CI uses Python 3.11. No dependencies were installed or
changed for this repair.

Docker, Podman and PostgreSQL binaries are absent. The explicit closed loopback
port makes the shared fixture's optional database residue probe fail quickly;
selected session cases use their existing real SQLite database. The repository's
network/provider safety guard remains active. Local sandbox execution stalled in
AnyIO's cross-thread TestClient portal even with the original test; approved
execution with local event-loop IPC available completed the tests.

The full suite collected 4,513 cases plus one skipped collection case. It was
interrupted at the coordinator's request after 114.72 seconds because this
environment cannot qualify PostgreSQL. The partial totals were 18 failed,
813 passed, 352 skipped, 1,826 warnings and 39 errors. The report lists every
observed failure/error by name: database connection errors and billing fixtures
that explicitly require PostgreSQL. Raw tracebacks are retained in local scratch
only, to avoid publishing fixture values. This run is neither full-suite success
nor release qualification.

Required remaining evidence is independent review and both `build` and
`web-release-e2e` on push and pull request for the exact final head, followed by
green master CI after merge. TC-02-007 remains open for its full acceptance.
