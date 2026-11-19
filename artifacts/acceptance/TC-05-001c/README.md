# TC-05-001c evidence

Local runs only. CI run ids for the merged head are in [ci-runs.md](ci-runs.md). Records revision 35 closes the child.

Unfixed code (`failing-before.txt`):

- API `tests/release/test_switch_workspace_mfa.py`: 5 failed, 1 passed, 6 skipped (SQLite; PostgreSQL skipped). The pass is a target workspace that does not require MFA. Failures are the enrol-only switch, the unsatisfied-session challenge, and the missing `mfa_satisfied` fact.
- Web `tests/unit/switch-workspace-mfa.test.ts`: 4 failed. The client kept the previous `mfa_required_for_workspace`.

Fixed code (`passing-after.txt`):

- API switch tests plus `tests/release/test_tc05001c_mfa_satisfied_migration.py`: 8 passed, 6 skipped.
- Web: 4 passed.

A follow-up SQLite run of `test_mfa_enroll.py`, `test_mfa_reenrol_security.py`, `test_principal_contract.py`, `test_session_persistence.py`, and `test_remember_policy.py` was 180 passed, 169 skipped. The migration adds `user_sessions.mfa_satisfied` (default false). Downgrade drops it; upgrade again leaves every row false.
