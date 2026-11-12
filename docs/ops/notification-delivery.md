# Notification delivery

Operator note for a dead-lettered notification and for dedupe claims. It does not
contain tokens, mailbox contents, or message bodies. Do not copy
`rendered_subject`, `rendered_body`, or `error_message` into a ticket.

Attempt rows live in `notification_delivery_attempts`. A claim lives in
`notification_dedupe_claims` and is keyed by the sha256 dedupe key. Several
attempt rows may share one key. The claim is what blocks a second send.

## Dead letter

`dead-lettered` means email or Slack exhausted `BoundedRetrySeam` (3 tries) or
failed in a way that will not be retried. `notification_log.status` is `failed`
and `notification_log.delivery_state` is `dead-lettered`. The dispatcher releases
the claim when the provider did not accept the message, so a later send of that
same event id is allowed. There is no replay control. Do not `UPDATE` the
attempt or the log to `sent`. That would record a delivery that did not happen.

A crash after the send has started does not release the claim. The 15-minute
lease is what stops a second send while the first outcome is unknown. Do not
delete that live claim to force another post. The provider may already have
accepted it. After the lease expires, a new send can take the key.

```sql
SELECT id, channel, event_type, template_key, state, error_code,
       attempt_number, destination, created_at
FROM notification_delivery_attempts
WHERE state = 'dead-lettered'
ORDER BY id DESC;
```

`destination` is the redacted address or channel id stored on the row. Leave
`rendered_subject`, `rendered_body`, and `error_message` out of this query.

A deduped row has `state = 'deduped'` and `error_code = 'claimed'`. That is a
claim that was already held. It is not a dead letter and it is not a send.

## Dedupe-claim pruning

`prune_dedupe_claims` deletes a claim only when `released_at` is set or
`expires_at` is in the past. Indexes `ix_notification_dedupe_claims_expires_at`
and `ix_notification_dedupe_claims_released_at` support that delete. Attempt
rows stay.

The worker calls the prune from `_process_one_job` when an hour has passed
(`USAGE_CLEANUP_INTERVAL_SEC` is 3600), including an idle poll. The first poll
after process start prunes because the timer begins at zero. A released or
expired claim does not block a new send even before the delete: the claim
statement takes over a row that is released or past `expires_at`. Pruning is
housekeeping. It is not required to unblock a send.

Do not delete a claim whose `released_at` is null and whose `expires_at` is
still in the future. That row is the lock for an in-flight or accepted send.

```sql
SELECT dedupe_key, claimed_at, expires_at, released_at
FROM notification_dedupe_claims
WHERE released_at IS NOT NULL
   OR expires_at < now()
ORDER BY expires_at;
```

Those are the rows the hourly prune deletes. A row that is absent from this
result is still holding its key.

## User recipients

A rule whose recipient type is `user` stores a workspace member's user id.
That id is `users.id` for an active, non-suspended member of the current
workspace. It is not an email address and it is not `workspace_members.id`.

Administrators choose the member in Alert Rules. The form reads `GET /api/members`,
which is limited to current administrators, and submits the selected user id.
The API still rejects an email, a non-integer, a missing member, a suspended
member, and a member of another workspace with the same not-found response.
Do not update `notification_policies.recipient_value` by hand to an email or a
membership row id. Delivery will not resolve it.

A disable-only change can turn off a rule after the member has left or been
suspended. The stored id stays. Turning the rule back on requires an active
member of this workspace. Role recipients remain a built-in role name or a
custom role in the same workspace.
