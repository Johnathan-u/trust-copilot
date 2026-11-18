# TC-11-001a acceptance evidence

Follow-up of TC-11-001, from the post-merge review of #212 (comment 6789647959 on merged `edd3320`). The review accepted the parent and left two documentation corrections. The child ticket also requires `result.json` to cite master run 42886627596.

## What changed

- `artifacts/acceptance/TC-11-001/result.json` no longer puts `"postgresql": "16.15"` in the CI `environment`. The CI logs for that record show only the image digest `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a`. `postgresql_note` says the 16.15 figure is the local run, under `local_run.postgresql`.
- `docs/release/tickets/TC-11-001.md` and `artifacts/acceptance/TC-11-001/README.md` pin the 27-revision count as of `edd3320` instead of saying it is the count on current master.
- `result.json` `master_run` cites master push [42886627596](https://github.com/Johnathan-u/trust-copilot/actions/runs/42886627596) of `edd332013d09af4222b9c700a489f9b4c7709091`. `build` job 130076533241 and `web-release-e2e` job 130076534472 both succeeded.

No application code, migration, authentication, or authorization path changed. The new release test is the only test change. It does not skip, and it does not touch a database.

## Release test

`apps/api/tests/release/test_tc11001a_evidence_wording.py`

| Test | Checks |
|---|---|
| `test_tc11001a_ci_environment_does_not_state_postgresql_16_15` | The CI `environment` keeps the image digest and does not set `postgresql` to the bare value `16.15`. With the field removed, `postgresql_note` says the version is the local run and that CI shows the digest. |
| `test_tc11001a_revision_count_is_pinned_to_edd3320` | The release doc and the README contain the phrase as of `edd3320`. Each line that states the 27-revision count names `edd3320` and does not say "current master". |
| `test_tc11001a_result_cites_master_run` | `master_run.run_id` is 42886627596, the event is `push`, the SHA is `edd332013d09af4222b9c700a489f9b4c7709091`, and the conclusion is success. |

Command, from `apps/api`:

```
python -m pytest tests/release/test_tc11001a_evidence_wording.py -q --tb=short -p no:cacheprovider
```

Python 3.12.3, pytest 9.1.1. Base before the wording edit: `0dd145f58f3abdfe03c2d68bf83bf32d56648e61`.

| Artifact | Result |
|---|---|
| `failing-before.txt` | 3 failed, 0 passed. Exit 1. |
| `passing-after.txt` | 3 passed, 0 failed, 0 skipped. Exit 0. |

## CI

`build` and `web-release-e2e` run IDs for the implementation head, on both `push` and `pull_request`, are in `ci-runs.md` once those runs are green. This directory does not accept TC-11-001 or TC-11-001a.
