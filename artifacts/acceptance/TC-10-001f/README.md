# TC-10-001f acceptance evidence

Docs only. No lease behavior change.

`_transaction_locks_job` compares this backend's transaction id with `jobs.xmax` / `jobs.xmin`. A lone `FOR UPDATE` matches, and a `FOR KEY SHARE` cannot be granted while that lock is held. Two concurrent `FOR KEY SHARE` locks, or `FOR SHARE` beside `FOR KEY SHARE`, store a multixact id in `xmax`. The comparison misses. `lease_is_held` then does not call `_extend_lease_already_locked`. It requires `lease_expires_at > statement_timestamp()` and, when the caller asked for a lock, takes `FOR UPDATE`. An expired lease or a different owner raises `LeaseLost` and the commit is rolled back. The worst case is a retry. A result is not committed after the lease has expired.

That matches the code in `lease_is_held` and `confirm_lease_for_commit`. The note is in the `_transaction_locks_job` docstring and in the commit-fence paragraph of `docs/release/tickets/TC-10-001.md`.

## Lock check

`multixact-check.txt`. PostgreSQL 16.15, database `trustcopilot_test`, 2026-11-16T13:02:34Z.

- Lone `FOR UPDATE`: `detection=True` (`xmax` equals this transaction id).
- `FOR KEY SHARE` while `FOR UPDATE` is held: `LockNotAvailable`.
- Two `FOR KEY SHARE` locks: `xmax=17`, `detection=False` for both holders.
- `FOR SHARE` plus `FOR KEY SHARE`: `xmax=18`, `detection=False` for both holders.

## Tests

`module.txt`. Command, from `apps/api` on this docs tree:

```
TC_REQUIRE_DB=1 python -m pytest tests/release/test_job_leases.py -q --tb=line -p no:cacheprovider
```

31 passed, 0 failed, 0 skipped, 38 warnings, 20.68s. Exit 0. Python 3.12.3, pytest 9.1.1. The same module count as before the docstring edit. This file does not accept TC-10-001 or TC-10-001f.
