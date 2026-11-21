# Private downloads

Operator notes for original, export, and trust-request attachment bytes (TC-07-008).
Production is still `APP_ENV=production`. The one optional setting is
`S3_PRIVACY_ATTESTATION`, and the only accepted value is
`unsupported-store-private`. Do not paste a storage key, a bucket policy, an
ACL, or object bytes into a ticket or a log excerpt.

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
`BlockPublicPolicy`, and `RestrictPublicBuckets` all true when the store can
answer that call. If production cannot read an ACL, policy, or
public-access-block answer, startup fails. The exception is `BucketNotPrivate`.
The API does not log it and continue. The message is either `Object storage
bucket is not private` or `Object storage bucket privacy could not be
confirmed`. It does not include the policy document or the ACL.

`S3_PRIVACY_ATTESTATION=unsupported-store-private` is the only exception. It
skips a call the store reports as unsupported, and it logs one warning per
skipped call with the bucket name and the check name (`acl`, `policy`, or
`public-access-block`). It does not skip a call the store answers. A public ACL
or a public policy still refuses startup. Any other non-empty value refuses
startup. Leave the variable unset on AWS S3.

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

## Cloudflare R2

`docker-compose.prod.yml` names Cloudflare R2 as a supported production store.
R2 does not implement bucket ACLs or `GetPublicAccessBlock`. Without the
attestation, those unsupported calls stop the API. Confirm the buckets are
private in R2 itself before you set the variable.

Do this for the raw bucket and again for the export bucket:

1. In the Cloudflare dashboard, open R2 and select the bucket.
2. Open the bucket's public access settings. The r2.dev development URL must be
   disabled. That URL looks like `https://pub-<id>.r2.dev`. If it is enabled,
   anyone who has the URL can read objects. Turn it off.
3. Remove any custom domain on that bucket that serves objects to the public.
   A custom domain is another way to publish the bucket. A private bucket has
   none.
4. Leave the bucket with public access off. R2 has no public ACL switch to
   clear; the r2.dev URL and custom domains are the public paths.

Only after both buckets pass those checks, set
`S3_PRIVACY_ATTESTATION=unsupported-store-private` in the production
environment and start the API again. The startup warning names each bucket and
the check it skipped. It does not include a policy or an ACL. If a later call
the store does answer shows a public policy, startup still fails. Any other
value of the variable refuses to start.

## Check

From `apps/api`:

```sh
python -m pytest tests/release/test_download_safety.py -q
```

The file runs against PostgreSQL. A skip is a failure when `TC_REQUIRE_DB=1`.
