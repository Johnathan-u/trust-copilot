# TC-21-013a: Deterministic gap races and legacy create replay

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_evidence_gaps.py -q
```

## SHA

Tests and the four CI checks ran on `f2b6aff2317ee376c068d02c48f7d6ef2a9390f9`. That commit was the branch head. This README commit only changes docs.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| `tests/release/test_domain_evidence_gaps.py` | 0 | 17 passed, 146 warnings, 7.94s |

## CI

4/4 green on `f2b6aff2317ee376c068d02c48f7d6ef2a9390f9`.

| Event | Run | `build` | `web-release-e2e` |
| --- | --- | --- | --- |
| push | `40938731895` | success | success |
| pull_request | `40938741204` | success | success |

## Guard check

On `bfcc33e`, with the scanner lock call removed, `test_scan_and_manual_create_leave_one_open_control_gap` failed: `scan never took the control lock`.

With `_update_open_gap` reduced to `return True`, `test_decision_and_resolve_race_for_one_open_gap` failed: `resolve did not wait on the open-row lock`.

Both edits were reverted before the passing run recorded above that commit. They were not repeated for this docs update.
