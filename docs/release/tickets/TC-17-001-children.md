# TC-17-001 children

Registered from the review of #307 ([comment 6998922136](https://github.com/Johnathan-u/trust-copilot/pull/307#issuecomment-6998922136)). These follow-ups are not blockers. They do not change the parent verdict, and they are not counted toward DONE. None of them is accepted. The tracker is not edited here.

## TC-17-001a — Public reads require a published version

Open. P3.

A public read still returns the live columns when `published` is 1 and `published_version_id` is null (`apps/api/app/api/routes/trust_articles.py`). The seed scripts can insert those rows. Either require a version on the public read, or have the seeds publish through `approve_current_draft`.

## TC-17-001b — Acknowledging must not publish

Open. P3.

`_viewable_version` publishes the current draft when a legacy published policy has no version. A member acknowledge should return 400 instead of calling `approve_current_draft`.

## TC-17-001c — Concurrent publish and a double acknowledge

Open. P3.

Two publishes can pick the same version number (`trust_article_versions.py`). A double-clicked acknowledge can hit the unique constraint. Both become a 500. Lock the article row and handle the conflict.

## TC-17-001d — Do not delete version history with the article

Open. P3.

Versions have no `BEFORE DELETE` guard. Deleting an article cascades away the acknowledgment history. Add the guard, or keep the history when the article is removed.

## TC-17-001e — Deal room and control publish return the draft

Open. P3.

`deal_room_service.py` and `get_published_controls` return the draft title and slug. They should use the published version.

## TC-17-001f — Runbook after downgrade

Open. P3.

The runbook should say that after a downgrade the previous code serves the draft text, and that the newest revoked acknowledgment counts again under that code.

## TC-17-001g — Owner ruling on publish-by-default

Open. Owner question. Not an engineering change until the owner rules.

Create still defaults to `published: 1`, and the dashboard sends `published: 1` on every save of a published article. There is no draft-only save, and every such edit revokes acknowledgments.

## TC-17-001h — Revoke comparison

Fixed in this change. Not deferred.

`revoke_acknowledgments` compares the kept version with `IS DISTINCT FROM`, so a null version id is revoked. `tests/release/test_domain_trust_articles.py` `test_revoke_acknowledgments_revokes_a_null_version_id` covers it. The parent is not accepted.

## TC-17-001i — Members can read drafts

Open. P3. Internal only.

A signed-in member can read the draft with a get that omits `workspace_id`, or with the workspace list. Note that, or restrict it. It is not the public read.
