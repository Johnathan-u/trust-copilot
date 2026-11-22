# Storage checksums

Operator notes for original-document and export hashes (TC-10-006).
No new setting was added. Do not paste a storage key, a hash, or object
bytes into a ticket or a log excerpt.

## What a download checks

`GET /api/documents/{id}/content` and `GET /api/exports/records/{id}/download`
return bytes only when the row and the object agree.

- The SHA-256 of the object bytes equals the hash on the row.
- The row's object version equals the version stored with the object.
- The media type derived from the filename equals the type stored on the row
  and on the object. The browser is not given the client-supplied content type.
- The workspace id in the storage key (`raw/{workspace}/` or
  `exports/{workspace}/`) equals the row's workspace, and the object metadata
  names that same workspace.

A current session is still required. A stored key that fails
`validate_storage_key` is still 400, before any read, with
`X-Content-Type-Options: nosniff`, and the error does not echo the key.
Those checks are unchanged from TC-07-008 (`docs/ops/private-downloads.md`).

When the recorded hash is missing, the hash does not match, the object is
missing, or the version, type, or workspace does not agree, the download is
refused. It is not a file. The body does not include the key or the hash.
The response sets `X-Content-Type-Options: nosniff`.

- A document refusal is 409. The detail is `The stored file could not be verified.`
- An export refusal is 409 `export_storage_failed`. The message is
  `The export could not be stored. No substitute file was produced.`
- A failed export is still that export's own 409, not a file.
- An id from another workspace is still 404. An archived document is still
  not streamed.

A new upload stores the document hash, version 1, and the filename media type
as the object is written. A completed export stores the same three fields on
`export_records` when the worker writes the object. The job result hash is
the same value. If that job hash and the row hash ever disagree, the download
is refused.

## Legacy rows

Rows written before this change have a null hash. They stay null through the
migration. A null hash is refused. The migration does not read object storage
and does not invent a hash.

The backfill command is the only way those rows become downloadable. It reads
each object, hashes the bytes that are there now, and writes that hash with
version 1 when all of the following are true:

- The key's workspace segment matches the row.
- The key passes `validate_storage_key`.
- The object exists.
- For a completed export that already has a job hash, that hash matches these
  bytes and the filename type.

It does not write a hash when the key names another workspace, the object is
missing, or an export's recorded job hash does not match the bytes. Those
rows stay refused. Do not copy an object into another workspace to make a
download succeed. A failed export has no object and is left alone.

Dry-run is the default. It changes nothing and prints counts only.

From `apps/api`, with the deployment's database and object-storage settings:

```sh
python -m app.services.storage_checksum
python -m app.services.storage_checksum --execute
```

The output is one line of counts: `pending`, `updated`, `missing`,
`disagreed`, and `mismatched`. It does not print a key or a hash. Run the
dry-run first. Run `--execute` only when the counts are the ones you expect.
Running it again does not change a row whose hash already matches the object.

## Rollback

Revision `tc10006_storage_checksums` adds nullable columns on `documents`
(`content_sha256`, `object_version`, `object_media_type`) and `export_records`
(`content_sha256`, `object_version`, `content_type`). Downgrade drops those
columns. The objects stay in the bucket. The hashes are not written back.

Upgrade again and the columns are null. Downloads stay refused until
`--execute` has been run again. Do not drop a bucket to make a download
succeed.
