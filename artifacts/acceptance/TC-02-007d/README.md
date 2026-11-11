# TC-02-007d evidence

Base is `dad086216f323f0caf1b39ec0eb4115515ec54eb` (master after #218 and #219).
Local child runs used Python 3.11.18 and pytest 9.1.1, with
`TC_REQUIRE_DB=1` and `TC_REQUIRE_STORAGE` unset, against a migrated local
`trustcopilot_test` database. Each child is the same helper the release tests
use (`tests/release/test_ci_integration.py::_run_child`): files are written
under a temporary directory and invoked through a short-lived symlink under
`apps/api/tests/` (outside `tests/release/`) so the child loads the path-local
`tests/conftest.py`.

A path-local `pytest_collectreport` does not receive a subdirectory conftest
skip. Pytest drops that directory's conftest modules from the hook proxy, so
deleting the `nodeid.endswith(".py")` return on its own still exits 0. The
gate is registered on the plugin manager, which does receive the directory
node, and the `.py` return is gone so a directory, package or conftest skip is
recorded.

## Criterion → evidence

| Criterion | Evidence |
|---|---|
| A collection skip of any node, including a directory, package or conftest, fails under `TC_REQUIRE_DB=1`. Allowed `pytestmark` values `provider`, `live_stack` and `external_data` stay exempt. | `apps/api/tests/conftest.py` (`_record_collection_skip`, `_CollectionSkipGate`). Before: `before-subdirectory-conftest.txt` exits 0, `1 passed, 1 skipped`, no gate text. After: `after-subdirectory-conftest.txt` exits 1 and prints `TC_REQUIRE_DB=1: collection-time skip is not allowed`. The existing `external_data` module-level control still exits 0 (`test_marked_external_data_module_skip_stays_allowed`). |
| Negative control: a child pytest with a subdirectory `conftest.py` that skips at module level fails and prints the gate message. | `test_subdirectory_conftest_skip_fails_under_tc_require_db`. Output pair above. On master's conftest the child exits 0. |
| Under `TC_REQUIRE_DB=1`, a skip of any test (`pytest.skip`, `skipif`, `importorskip`) fails unless the item is marked `provider`, `live_stack` or `external_data`. | `pytest_runtest_makereport` fails every such skip. Integration tests keep the existing `DB (integration) test skipped instead of running` text. Other tests use `test skipped instead of running`. `tests/release/test_python_lock.py` now expects the unit skip to be `FAILED` (it used to expect `SKIPPED`). |
| `tests/test_trust_scoring_blind.py:33` (`external_data`) stays allowed. | Unchanged module marker and module-level skip. The collection gate still exempts a module whose `pytestmark` is `external_data`. It was the only skip on the master baseline. |
| Every test that skips in CI is found. The suite stays at one skip, plus the new passing tests. | Master baseline, from the #219 `build` log (run 42983172693, job 130398101870), `pytest -rs`: `6439 passed, 1 skipped`. The only skip line is `SKIPPED [1] tests/test_trust_scoring_blind.py:33: external_data: blind test pack not checked in; set TC_TRUST_SCORING_BLIND_PACK to run`. This branch adds 4 passing tests, so the expected total is **6443 passed, 1 skipped**. The total from this PR's `pytest -rs` is recorded after CI. |
| `tests/release/test_safe_collection.py` ("node not installed") runs in CI. | The `build` job already runs `Setup Node` (`apps/web/.nvmrc`, Node 24.22.1) before `Safe test collection` and `Run backend tests`. The master skip list above does not include that test, so it ran. It is not given an allowed-skip marker. If `node` is absent while `TC_REQUIRE_DB=1`, that `pytest.skip` now fails the run. |
| Negative control: an unmarked test that calls `pytest.skip` under `TC_REQUIRE_DB=1` fails the child. | `test_unmarked_runtime_skip_fails_under_tc_require_db`. `before-unmarked-runtime-skip.txt` exits 0. `after-unmarked-runtime-skip.txt` exits 1 with `TC_REQUIRE_DB=1: test skipped instead of running`. |
| `docs/release/tickets/TC-02-007.md` readiness timeout matches `ci.yml` `--max-time 15`. | The runbook says "each attempt limited to 15 seconds". `test_moto_readiness_timeout_and_licence_match_ci` rejects "limited to 5 seconds". |
| The CI storage step prints `moto.__version__`. | `.github/workflows/ci.yml` runs `docker exec tc-ci-s3 python3 -c 'import moto; print("moto version:", moto.__version__)'` after the final probe. The printed line is copied into `moto-version.txt` after CI. |
| Moto is a test-only CI image in `docs/acceptance/license-resolution.md` §6. | §6 names `motoserver/moto:5.2.5` (Apache-2.0), pinned by the digest in `ci.yml`, not shipped. |
| Negative control: a `storage`-marked test that skips fails the child. | `test_storage_marked_skip_fails_under_tc_require_db`, with `TC_REQUIRE_STORAGE` unset so master's storage hook does not hide the hole. `before-storage-marked-skip.txt` exits 0. `after-storage-marked-skip.txt` exits 1 with `TC_REQUIRE_DB=1: test skipped instead of running`. |
| Negative-control files are written to a temporary directory, not `tests/release/`. The #218 controls use the same helper. | `_run_child` writes `tmp_path / "child"` and deletes the symlink before returning. `test_deliberate_integration_skip_fails_under_tc_require_db`, `test_unmarked_module_skip_fails_under_tc_require_db`, `test_marked_external_data_module_skip_stays_allowed` and `test_storage_unavailability_fails_under_tc_require_storage` all call it. |

## Before / after

Master conftest is `origin/master` at `dad086216f323f0caf1b39ec0eb4115515ec54eb`.
The same three children were run against that file and against this branch.

| Scenario | Master conftest | This branch |
|---|---|---|
| Subdirectory `conftest.py` module-level skip | exit 0 (`before-subdirectory-conftest.txt`) | exit 1 (`after-subdirectory-conftest.txt`) |
| Unmarked `pytest.skip` | exit 0 (`before-unmarked-runtime-skip.txt`) | exit 1 (`after-unmarked-runtime-skip.txt`) |
| `storage`-marked `pytest.skip` | exit 0 (`before-storage-marked-skip.txt`) | exit 1 (`after-storage-marked-skip.txt`) |

## Local commands

From `apps/api`, with the test database migrated and `TC_TEST_DATABASE_URL` set:

```bash
python -m pytest tests/release/test_ci_integration.py tests/release/test_python_lock.py::test_db_test_skip_fails_when_db_is_required tests/release/test_python_lock.py::test_db_test_skip_stays_a_skip_without_tc_require_db -q
```

That run was 16 passed. The database, storage and browser services are not started by those tests. The closed-port storage control and the workflow assertions do not need Postgres. The `TC_REQUIRE_DB=1` children do.
