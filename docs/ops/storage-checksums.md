# Storage checksums

## Required post-deploy step

After deploying this change, every existing document and export download returns 409 until the backfill runs.

From `apps/api`, with the deployment's database and object-storage settings:

1. Run `python -m app.services.storage_checksum` (dry run).
2. Check the counts.
3. Run `python -m app.services.storage_checksum --execute`.

The dry run changes nothing. `--execute` writes the hashes. Do not paste a storage key, a hash, or object bytes into a ticket or a log excerpt.

Operator notes for original-document and export hashes (TC-10-006).
No new setting was added.

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

That version 1 write is for a row that does not already agree. A row that
already agrees, including a version above 1, is left unchanged. See TC-10-006c.

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
`disagreed`, `mismatched`, and `already`. It does not print a key or a hash.
`already` is a row whose hash, media type, positive version, and workspace
already agree with the object. Run the dry-run first. Run `--execute` only
when the counts are the ones you expect. Running it again does not change a
row that already agrees. An interrupted run, and a document whose workspace
was moved, are covered under TC-10-006c below.

## TC-10-006c

### Rows that already agree

A document or a completed export is already complete when all of the following
agree:

- The SHA-256 of the object bytes equals `content_sha256` on the row.
- The media type derived from the filename equals the type on the row
  (`object_media_type` for a document, `content_type` for an export) and the
  type stored with the object. A document's client-supplied `content_type`
  is not the checksum type.
- `object_version` is a positive integer and equals the version stored with
  the object. Version 2 or higher is complete. It is not rewritten as version 1.
- The workspace id on the row equals the workspace in the storage key and the
  workspace stored with the object.

Dry-run and `--execute` count that row as `already`. They do not upload the
object again and they do not change the version. A re-rendered export whose
hash is still correct stays on its current version.

A row that does not agree keeps the earlier behaviour. A key that names
another workspace, or a key that fails `validate_storage_key`, is
`disagreed` and is not written. A recorded hash that does not match the
bytes is `mismatched` and is not written. An export whose job hash does not
match the bytes is `mismatched` and is not written. The download stays
refused. The 409, the workspace check, the hash check, the version check,
and the media-type check are unchanged.

### Interrupted --execute

`--execute` stamps the object, then commits the row. If the process stops
after the stamp and before the commit, the object has the checksum metadata
and the row does not. Fix that by running the command again. From `apps/api`,
with the deployment's database and object-storage settings:

```sh
python -m app.services.storage_checksum
python -m app.services.storage_checksum --execute
```

The dry-run still changes nothing. The next `--execute` writes the row from
the object that is already there. A row that already agrees is not rewritten
and its version is not reset. Run the command once more after that. `already`
counts the rows that agree, and `updated` is zero when there is nothing left
to write.

### Moved documents

`reassign_parent_workspace` changes the document's workspace and leaves the
storage key on the old workspace (`raw/{old workspace}/...`). The download
is refused, because the key's workspace does not match the row. The body is
the same 409 as any other checksum refusal. It is not the file. The backfill
counts that row as `disagreed` and does not write a hash, a version, or a
new key. That failure is closed on purpose. Do not copy the object into the
new workspace to make the download succeed.

## Rollback

Revision `tc10006_storage_checksums` adds nullable columns on `documents`
(`content_sha256`, `object_version`, `object_media_type`) and `export_records`
(`content_sha256`, `object_version`, `content_type`). Downgrade drops those
columns. The objects stay in the bucket. The hashes are not written back.

Upgrade again and the columns are null. Downloads stay refused until
`--execute` has been run again. Do not drop a bucket to make a download
succeed.
