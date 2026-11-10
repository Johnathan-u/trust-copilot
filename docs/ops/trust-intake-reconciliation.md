# Trust intake reconciliation

Operator note for a public trust intake whose save or attachment cleanup did not finish.
The API writes one of the lines below and nothing else about the request. A line may
include an opaque `storage_key` and, for an uncertain save, a numeric `request_id`.
It does not include the requester email, name, subject, message, original filename,
or the database or storage exception text. Do not add those values to a ticket, a
copied log, or this runbook.

The public form keeps one `Idempotency-Key` for the same details and sends that key
again after a lost response. A repeated key returns the original request and does
not create a second row or upload the attachment again. The same key with different
details is a conflict. Do not file a replacement request by hand to "finish" an
uncertain save.

No migration is involved. Do not change `trust_requests` or `idempotency_keys` to
force a row into existence.

## `trust intake save outcome requires reconciliation`

COMMIT had started, so the API cannot tell whether the request row and the retry
record committed. It does not delete the blob. A failed session rollback on this
path logs `trust intake database cleanup requires reconciliation` first; the
save-outcome line still follows and is the one that carries `request_id` and
`storage_key`.

1. Read `request_id` and `storage_key` from the log line.
2. Look up `trust_requests.id` equal to that `request_id`.
3. If that row exists and its `attachment_storage_key` equals `storage_key`, the
   save committed. Leave the blob. The sender submits the same details with the
   same `Idempotency-Key` and receives the original response.
4. If that row does not exist, search `trust_requests.attachment_storage_key` for
   the same key.
5. If no row references the key, the object is unreferenced. Delete only that
   object from the raw bucket. Do not delete by filename, and do not delete a
   prefix wider than the exact key.
6. If a different row references the key, leave the blob and record the mismatch
   for a human. Do not delete it.

## `trust attachment cleanup requires reconciliation`

The intake failed before COMMIT, and deleting the blob failed. The request row
should not exist. The line carries `storage_key` only.

1. Read `storage_key` from the log line.
2. Confirm no `trust_requests.attachment_storage_key` equals that key.
3. If none match, delete that exact object from the raw bucket.
4. If a row matches, do not delete. Treat the object as an uncertain save and
   follow the section above.

## `trust intake database cleanup requires reconciliation`

Rolling back the database session or releasing the retry claim failed. This line
has no `request_id` and no `storage_key`.

1. Correlate it by timestamp with a nearby save-outcome or attachment-cleanup
   line, which carries the key.
2. If there is no companion line, look for an idempotency row whose stored key
   contains `:trust-intake:create:` and whose response is still empty, and for
   `trust_requests` rows created at that time. Do not guess from an email address
   or from message text. Those values are not in the log.
3. Do not delete a blob unless a companion line gives its exact key and no row
   references that key.

## What not to do

- Do not delete an attachment while a request row might reference it.
- Do not resend or invent a second intake to complete an uncertain save.
- Do not copy the message, the original filename, or a backend exception into the
  incident record.
