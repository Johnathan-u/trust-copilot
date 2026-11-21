# Answer edits

Operator note for review-page answer saves (TC-12-002). No new configuration key. No migration.

`answers.updated_at` is the revision. The column is already on the table.

`GET /api/questionnaires/{id}` includes that value on each answer. The review editor sends it back on `PATCH /api/answers/{answer_id}`.

A missing `updated_at`, a blank value, or a value that is not the stored revision is HTTP 409. The response detail is `This answer changed since it was loaded. Reload it and try again.` The stored row is left unchanged. Reload the questionnaire and send the new `updated_at`.

The same per-question advisory lock still serializes answer writes. It does not decide the 409.

On HTTP 403, 409, and 500 the review row keeps the typed text and stays on `Not saved yet`. It does not show `Saved`.

Another workspace is still 403, and a missing answer is still 404. Those checks run before the revision check. `POST /api/answers` still creates a row when the question has no answer yet. `PATCH /api/answers/bulk` still updates status without this revision.

Archiving or replacing a cited document rewrites that answer's citations and `updated_at`. The next save of an open editor is 409 until the questionnaire is reloaded. The approved text stays, and the read adds `support_stale`. See `docs/ops/retrieval-cache-keys.md`.
