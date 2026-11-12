# TC-13-002 acceptance evidence

This file records CI of `2cca8c7447dbc22369dc62d35426cb24dbfed883`. The commit
that adds it is a later SHA, so it is not the SHA under test. Reviewer signoff
is still pending. This record does not accept the ticket.

## Command

From `apps/api`, the suite CI runs is `pytest -rs`. That collects the ticket
command `python -m pytest tests/release/test_export_fidelity.py -q`.

Local run of the ticket file, before this evidence commit, on the same tree
as `2cca8c7`:

```
python -m pytest tests/release/test_export_fidelity.py -q
```

Exit 0. 60 passed, 0 failed, 0 skipped.

## Suite totals

Both `build` jobs reported the same totals. The only skip is the allowed one.

| Event | Passed | Failed | Skipped | Warnings | Exit |
|---|---:|---:|---:|---:|---:|
| push | 6510 | 0 | 1 | 52 | 0 |
| pull_request | 6510 | 0 | 1 | 52 | 0 |

Skip, both builds:

`tests/test_trust_scoring_blind.py:33: external_data: blind test pack not checked in; set TC_TRUST_SCORING_BLIND_PACK to run`

The fidelity file is in the collected suite (`tests/release/test_export_fidelity.py`, 60 tests, 0 skipped). Master before this change was 6450 passed and 1 skipped. 6450 + 60 = 6510.

## Environment

- Runner: GitHub-hosted, Python 3.11.18, pytest 9.1.1, openpyxl 3.1.5.
- Push build duration: 840.91s. Pull-request build duration: 784.12s.
- Pillow is not installed. Picture bytes are copied back after openpyxl save.
- Real viewer: LibreOffice 24.2.7.2 headless, recorded in `libreoffice_viewer_check.txt` on this same code. Both exports exited 0 with no document-recovery message. `LEN(A2)` calculated to 28 and the answer cell was the literal text `Approved`.

## Runs for `2cca8c7447dbc22369dc62d35426cb24dbfed883`

| Event | Run | Build job | web-release-e2e job | Conclusions |
|---|---|---|---|---|
| push | [43143973714](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143973714) | [130937345768](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143973714/job/130937345768) success | [130937346160](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143973714/job/130937346160) success | both success |
| pull_request | [43143979120](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143979120) | [130937363060](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143979120/job/130937363060) success | [130937362788](https://github.com/Johnathan-u/trust-copilot/actions/runs/43143979120/job/130937362788) success | both success |

PR: https://github.com/Johnathan-u/trust-copilot/pull/233

The previous head `6f293fbc0196e1c2b01083d21f83ce27b0012df3` failed `build` on both events because pre-commit `ruff-format` rewrote the fidelity test. `web-release-e2e` was already success on that head (push job 130934268415, pull_request job 130934341570). `2cca8c7` is the format-only follow-up and is the qualifying code head.
