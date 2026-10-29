# TC-06-BUG-013b Operator queue write 404s and promise source references

## Release notes

- `PATCH /api/operator-queue/{id}` and `DELETE /api/operator-queue/{id}` return the standard 404
  (same body as a missing id) when the item no longer exists after the workspace check. They used
  to return 200 with a `null` body or `{"deleted": true}`. `GET` already behaves this way (#47).
- `POST /api/promises` returns 422 when `source_type` is `questionnaire_answer`, `trust_article` or
  `contract_clause` and `source_ref_id` is missing or null. The `detail` is a plain string for now.
  Other source types (`manual`, `sla`, `verbal`, ...) still accept no `source_ref_id`.
- Behaviour change shipped in #47 (TC-06-BUG-013a), recorded here because no release note existed:
  `POST /api/proof-graph/artifacts/verify` now returns 404 for a missing id, or an id from another
  workspace, of a known `artifact_kind`. It used to return 200 with
  `{"ok": false, "reason": "no_recorded_hash"}`. An own-workspace artifact with no recorded hash
  still returns 200 `no_recorded_hash`.

## Tests

`apps/api/tests/release/test_body_reference_workspace_scope.py` (TC-06-BUG-013b section): the item
deleted from another session between the scope check and the write, the same race with the service
mocked, foreign and missing ids, own-item PATCH/DELETE, and promise `source_ref_id` required/optional
cases. All data is synthetic.

## Rollback

Revert the PR. No migrations or persisted-state changes.
