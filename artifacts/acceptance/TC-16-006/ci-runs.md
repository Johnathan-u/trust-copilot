# CI for TC-16-006

`build` and `web-release-e2e` are green on both `push` and `pull_request` for the two heads below. No migration.

## #302 Gap 1, flag audit and production env-as-default-only

Head `66275f155ee90e14f86fbf72fc25c0b785e9193a`. Squash-merged as `fff358abf2001b9d18b0fdf5507ba8a0fc99127c`.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [44359724233](https://github.com/Johnathan-u/trust-copilot/actions/runs/44359724233) | build `134997434629` | success |
| push | 44359724233 | web-release-e2e `134997435670` | success |
| pull_request | [44359758120](https://github.com/Johnathan-u/trust-copilot/actions/runs/44359758120) | build `134997553645` | success |
| pull_request | 44359758120 | web-release-e2e `134997553199` | success |

## #304 Gap 2, flags cannot gate security controls

Head `15aeeb2aa06468abd0f13afd5a5ba926ba3377e9`. Squash-merged as `f2ab399e5c07e614cef5937e61bd943da3b678a4`. The release check is collected by the existing `pytest -rs` step in `build`. No workflow change.

| Event | Run | Job | Conclusion |
|---|---|---|---|
| push | [44373596657](https://github.com/Johnathan-u/trust-copilot/actions/runs/44373596657) | build `135046680302` | success |
| push | 44373596657 | web-release-e2e `135046681086` | success |
| pull_request | [44373674456](https://github.com/Johnathan-u/trust-copilot/actions/runs/44373674456) | build `135046958434` | success |
| pull_request | 44373674456 | web-release-e2e `135046957817` | success |
