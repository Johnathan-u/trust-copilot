# TC-06-003e acceptance evidence

Implemented from actual master `46603ee17b686d22d86da14227c58a7dad9a4e94` under
#85/6516617322 and the timestamp-only amendment #85/6516679370.

The credential routes and permission contract are unchanged. The sole runtime
change handles a naive `last_rotated_at` as UTC for the due comparison, following
the existing session timestamp convention. Aware offsets retain their instant;
the persisted timestamp and serialized metadata are untouched.

| Check                                                           | Observed result                                                     |
| --------------------------------------------------------------- | ------------------------------------------------------------------- |
| First populated collection regression, before runtime change    | 2 passed; rotation-due failed with naive/aware datetime `TypeError` |
| SQLite HTTP matrix                                              | 79 passed                                                           |
| Naive UTC / aware UTC / +05:30 / -04:00 comparison boundaries   | 12 passed                                                           |
| Complete SQLite + PostgreSQL + comparison collection            | 170 collected                                                       |
| Strict PostgreSQL execution attempt                             | Setup aborted; localhost IPv4/IPv6 port 5432 refused                |
| Remove list workspace filter in memory                          | Expected regression failure: foreign IDs returned                   |
| Remove upsert workspace filter in memory                        | Expected regression failure: foreign record updated                 |
| Replace admin guard with session-only guard in memory           | Expected regression failure: editor receives 200 instead of 403     |
| Reset every aware timestamp to UTC without conversion in memory | Two expected +05:30 boundary failures                               |

The HTTP fixture substitutes only its owned database connection. Signed cookies
include explicit expiry and a real stored session; current membership and custom
role queries run normally. Tests do not replace auth, storage, crypto or service
behavior. The boundary controls replace only the service clock. Their separate
ORM-input tests intentionally retain supplied datetime values; they qualify
comparison semantics, not SQLite timezone-offset persistence.

Denied requests and GETs compare complete row hashes and permit only SELECT
statements. Denials must issue no credential-table query. Mutation cases compare
every unrelated row plus all unaffected columns of the target. Values are
generated at runtime and comparisons are hashed; no credential plaintext is
included in these artifacts. Only fixture-owned data is cleaned up. No FK,
trigger, provider, network, dependency or schema bypass is used.

PostgreSQL qualification and independent review remain pending. Passing local
controls is not a full-stack, external-provider, owner/viewer or full TC-06-003
completion claim. Confidence-setting isolation remains separate TC-12-012a work.
