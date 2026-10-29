# TC-21-013a: Deterministic gap races and legacy create replay

Local only. This branch was not pushed.

## Command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`.

```text
python -m pytest tests/release/test_domain_evidence_gaps.py -q
```

## SHA

Tests ran on `bfcc33ed364c73ef1d171e8adce344775292cbff`. That commit is the parent of this evidence commit.

## Totals

| Command | Exit | Total |
| --- | --- | --- |
| `tests/release/test_domain_evidence_gaps.py` | 0 | 17 passed, 146 warnings, 6.20s |

## Guard check

With the scanner lock call removed, `test_scan_and_manual_create_leave_one_open_control_gap` failed: `scan never took the control lock`.

With `_update_open_gap` reduced to `return True`, `test_decision_and_resolve_race_for_one_open_gap` failed: `resolve did not wait on the open-row lock`.

Both edits were reverted before the passing run above.
