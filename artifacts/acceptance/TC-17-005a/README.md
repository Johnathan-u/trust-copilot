# TC-17-005a evidence

Local runs used Python 3.12.3 and PostgreSQL 16.15, database `trustcopilot_test` at `127.0.0.1:5432`. Base before the fix: `f305b4e8911471eed249d749f53fdeeec31380b9`.

| Run | Result |
| --- | --- |
| `pytest tests/test_shareable_space_token_gate.py -q --tb=line` before the fix | 16 failed, 3 passed (`failing-before.txt`). Every built-in role, custom role, and API key received the raw token from the list. The stored `access_token` equalled that secret. A plaintext column was accepted by `/access`. A successful access wrote no audit row. |
| Same gate file, existing share tests, the deal-room token gate, the NDA/share authorization suite, and the migration round trip, after the fix | 192 passed (`passing-after.txt`). |
| `alembic heads` | `tc17005a_share_token` (head), `down_revision` `question_cell_mapping`. |

Quoted synthetic tokens in the failing log are replaced with `<synthetic-token>`. CI run IDs for the exact head are on the pull request, so recording them here does not take another commit.

`apps/web` does not call `GET /api/shareable-spaces`. No web file changed.
