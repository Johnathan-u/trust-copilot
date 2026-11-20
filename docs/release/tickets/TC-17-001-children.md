# TC-17-001 children

Registered from the review of #307 ([comment 6998922136](https://github.com/Johnathan-u/trust-copilot/pull/307#issuecomment-6998922136)). These follow-ups are not blockers. They do not change the parent verdict, and they are not counted toward DONE. None of them is accepted.

The sentence in the implementation commit said the tracker was not edited there. Records revision 35 registers TC-17-001a, TC-17-001b, TC-17-001c, TC-17-001d, TC-17-001e, TC-17-001f, TC-17-001h and TC-17-001i. TC-17-001g is the owner question. It is parked and is not a follow-up. Each registered child has its own file in this directory. Records revision 36 closes TC-17-001b (#313) and TC-17-001h (#312). Those closes are not counted toward DONE.

## TC-17-001a — Public reads require a published version

Open. P1. Registered. See [TC-17-001a.md](TC-17-001a.md).

A public read still returns the live columns when `published` is 1 and `published_version_id` is null (`apps/api/app/api/routes/trust_articles.py`). The seed scripts can insert those rows. Either require a version on the public read, or have the seeds publish through `approve_current_draft`.

## TC-17-001b — Acknowledging must not publish

Closed by #313 (`030550e86bf3393f480cc0802fcfde68233457ed`). P1 security. Registered. See [TC-17-001b.md](TC-17-001b.md).

`_viewable_version` publishes the current draft when a legacy published policy has no version. A member acknowledge should return 400 instead of calling `approve_current_draft`.

## TC-17-001c — Concurrent publish and a double acknowledge

Open. P2. Registered. See [TC-17-001c.md](TC-17-001c.md).

Two publishes can pick the same version number (`trust_article_versions.py`). A double-clicked acknowledge can hit the unique constraint. Both become a 500. Lock the article row and handle the conflict.

## TC-17-001d — Do not delete version history with the article

Open. P2. Registered. See [TC-17-001d.md](TC-17-001d.md).

Versions have no `BEFORE DELETE` guard. Deleting an article cascades away the acknowledgment history. Add the guard, or keep the history when the article is removed.

## TC-17-001e — Deal room and control publish return the draft

Open. P1. Registered. See [TC-17-001e.md](TC-17-001e.md).

`deal_room_service.py` and `get_published_controls` return the draft title and slug. They should use the published version.

## TC-17-001f — Runbook after downgrade

Open. P2. Registered. See [TC-17-001f.md](TC-17-001f.md).

The runbook should say that after a downgrade the previous code serves the draft text, and that the newest revoked acknowledgment counts again under that code.

## TC-17-001g — Owner ruling on publish-by-default

Parked for the owner. Not registered as work. There is no `TC-17-001g` follow-up. Not an engineering change until the owner rules.

Create still defaults to `published: 1`, and the dashboard sends `published: 1` on every save of a published article. There is no draft-only save, and every such edit revokes acknowledgments.

## TC-17-001h — Revoke comparison

Closed by #312 (`32cc730e508b78af9c5039c1ee4a88bb29e970e6`). P1. Registered. See [TC-17-001h.md](TC-17-001h.md). The branch commit `4a6251035996dad1b861074d1bfe1113989e1841` missed the #307 squash. #312 landed the comparison on master.

`revoke_acknowledgments` should compare the kept version with `IS DISTINCT FROM` so a null version id is not treated as equal.

## TC-17-001i — Members can read drafts

Open. P2. Registered as a note. See [TC-17-001i.md](TC-17-001i.md). Internal only.

A signed-in member can read the draft with a get that omits `workspace_id`, or with the workspace list. Note that, or restrict it. It is not the public read.
