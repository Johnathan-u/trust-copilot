# Private downloads

Operator notes for original, export, and trust-request attachment bytes (TC-07-008).
No new setting is added. Production is still `APP_ENV=production`. Do not paste a
storage key, a bucket policy, an ACL, or object bytes into a ticket or a log excerpt.

## What the browser receives

Three routes return object bytes. None of them returns a presigned URL.

- `GET /api/documents/{id}/content?workspace_id=`
- `GET /api/exports/records/{id}/download?workspace_id=`
- `GET /api/trust-requests/{id}/attachment`

The document and the attachment require a current reviewer session. The export
requires a current exporter session. `FileService.get_download_url` can mint a
presigned URL, and no route calls it. Do not add a response that hands that URL
to the browser. These routes do not accept a share token. There is no separate
public-grant download.

A missing session row, a session older than the workspace maximum age, and a
session created at or before that workspace's revocation time are 401. A
suspended member is 403. An id from another workspace is 404. The 404 body does
not include the storage key or the object bytes. Passing another workspace id
in the query is 403 and also returns no bytes.

An archived document (`deleted_at` set) is not streamed. Its list row does not
offer a preview URL.

A stored key that is empty, contains `..`, starts with `/`, contains a null, or
is longer than 600 characters is refused with 400 before any storage read. The
error text is `Invalid storage key` or `Storage key too long`. It does not echo
the key. That error and every successful download set
`X-Content-Type-Options: nosniff`. The document and export media type comes from
the filename extension. The attachment media type is
`application/octet-stream`. The download name is sanitized. A failed export, or
an export whose stored bytes do not match the recorded hash, is 409 and is not
a file.

## Buckets

`ensure_buckets` creates a missing raw or export bucket with a private ACL and
with all four public-access block flags. An existing bucket is checked and is
not rewritten.

The check refuses a bucket whose ACL grants `AllUsers` or `AuthenticatedUsers`,
or whose bucket policy allows any action to a public principal. In production
the public-access block must have `BlockPublicAcls`, `IgnorePublicAcls`,
`BlockPublicPolicy`, and `RestrictPublicBuckets` all true. If production cannot
read that answer, startup fails. The exception is `BucketNotPrivate`. The API
does not log it and continue. The message is either `Object storage bucket is
not private` or `Object storage bucket privacy could not be confirmed`. It does
not include the policy document or the ACL.

Outside production, a store that does not implement the public-access block API
is accepted when the ACL is private and there is no public policy. A public ACL
or a public policy is still refused. A store that is simply down remains a
startup warning, including in production, so the process can still boot when
object storage is unreachable. A bucket that is reachable and public does not.

When startup raises `BucketNotPrivate`:

1. Leave the bucket private. Do not add a public grant to make the API start.
2. Remove public ACL grants and any policy statement whose principal is public.
3. In production, turn on all four public-access block flags named above.
4. Start the API again.

No migration is involved. Do not change a table to make a download succeed.

## Check

From `apps/api`:

```sh
python -m pytest tests/release/test_download_safety.py -q
```

The file runs against PostgreSQL. A skip is a failure when `TC_REQUIRE_DB=1`.
