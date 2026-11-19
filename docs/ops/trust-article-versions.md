# Trust article versions

Publishing a trust article stores an immutable row in `trust_article_versions`.
Readers of the public trust centre see that row. The article row itself is the
draft. An edit that does not send `published: 1` changes the draft only.

## Publish and withdraw

- Create with `published: 1` (the default when the field is omitted) writes version 1.
- `PATCH` with `published: 1` approves the current draft. Different text inserts the next version. The same text reuses the current version.
- `PATCH` with any other `published` value withdraws the article. The version row stays. A public read is 404.
- `UPDATE` of `trust_article_versions` is rejected by `trg_tc17001_version_immutable`. Delete happens only when the article is deleted.

## Acknowledgments

`policy_acknowledgments` stores `user_id`, `workspace_id`, and `article_version_id`.
The acknowledge call must send `article_version_id`, and that id must be the
published version. A different id is 409.
A row counts only while `revoked_at` is null, the article is published, and
`article_version_id` is the article's `published_version_id`.

Unpublish, or publishing a different draft, sets `revoked_at` on the previous
rows. The reader has to acknowledge the version that is on screen. A repeat
acknowledgment of that same version returns the original timestamp.

## Create retry

`POST /api/trust-articles/` accepts an optional `Idempotency-Key`. The key is
stored scoped to the workspace and this route. The same key and the same body
return the first article. The same key with a different body is 422. A missing
key still rejects a duplicate slug with 400.

## Migration

Revision `tc17001_article_versions` (parent `tc04005a_member_revoked_at`).

Upgrade copies each published, workspace-scoped article into version 1 and
binds existing acknowledgments of those articles to that version. That bind
runs on a first upgrade, when no downgrade archive exists. Those rows stay
unrevoked. An acknowledgment with no published version is marked revoked.

Downgrade copies versions, publication pointers, and acknowledgment bindings
into `tc17001_version_archive`, `tc17001_article_pub_archive`,
`tc17001_ack_binding_archive`, and `tc17001_ack_row_archive`, then restores the
previous `policy_acknowledgments` shape. Extra acknowledgment rows that would
break the old unique index are removed from the live table and kept in
`tc17001_ack_row_archive`. Re-upgrade puts those rows back when the user,
article, and version still exist.

```sh
cd apps/api
alembic downgrade tc04005a_member_revoked_at
alembic upgrade head
```

This revision needs review before it is applied. It changes persisted state.
