# Retrieval and answer cache keys

Operator note for which inputs decide a cache hit. No new configuration key.
Changing one of these inputs misses. It does not read a row written for a
different value.

## Retrieval cache

`apps/api/app/services/retrieval_cache.py` hashes:

- workspace id
- normalized question
- corpus version for that workspace
- evidence scope (the questionnaire document list, or every eligible document)
- permission-policy fingerprint

`get` builds the key from the corpus version stored now. A row written under an
older version is a miss (`None`). A row that still matches the version but cites
a soft-deleted, not-indexed, tombstoned, or replaced source is also a miss.

Indexing a document, and soft-deleting or restoring one, bumps the corpus
version and deletes that workspace's retrieval rows and answer rows.

## Answer cache

`apps/api/app/services/answer_cache.py` hashes:

- workspace id
- normalized question
- response style
- evidence fingerprint (the chunk ids that were retrieved)
- corpus version for that workspace, read at get and at set
- prompt version (`ANSWER_PROMPT_VERSION` in `apps/api/app/services/prompt_builder.py`)
- model id (the resolved completion model; the default is `gpt-4o-mini`)
- permission-policy fingerprint

A caller does not pass the corpus version into `get`. After a bump, the same
question, style, evidence, prompt, and model miss. A hit whose citations name
an ineligible source returns `None`.

Bump `ANSWER_PROMPT_VERSION` when the answer system prompt or `build_prompt`
changes. The next generation then does not reuse drafts from the previous
prompt.

## Archive and replacement

Soft-delete (the document archive) tombstones the document's chunks and bumps
the corpus version. It also marks each answer that cites that document. The
approved text and `approved` status stay. `GET /api/questionnaires/{id}`
returns `support_stale: true` on that answer. Restoring the document does not
clear the marker.

A replaced storage key is the same stale state when a chunk still records the
previous source version, and a reindex of a new key marks citing answers
before it deletes those chunks. A reindex of the same key does not.

Final export (`POST /api/exports/export/{id}` and the export worker) returns
409 while any included answer cites a revoked source or is still that stale
revision. The body lists answer ids and does not include answer text. An
insufficient-evidence placeholder is not included. Export proceeds after a new
revision is approved against a document that is still active.

The marker is a field on the existing citations text. No new column and no
new configuration key.

## What a search returns

Keyword and semantic search keep a chunk when it has no document, or when its
document is in the caller's workspace, `status` is `indexed`, `deleted_at` is
null, the chunk is not tombstoned, and any recorded source version still
matches the document's storage key. The caller's permission policy is applied
with the existing role helpers. A document outside that policy is omitted even
when it is in the same workspace. The storage key itself is not part of the
result.
