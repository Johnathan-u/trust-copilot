# Purpose keyrings: backup, rotation, and sole-admin MFA recovery

Operator runbook for production key custody (TC-07-002a). It does not contain key material.
Do not paste a keyring, `SESSION_SECRET`, ciphertext, TOTP secret, or recovery code into
this file, a ticket, a log, or a shell history that is retained.

Production refuses to start unless `SESSION_KEYRING`, `OAUTH_STATE_KEYRING`, `MFA_KEYRING`
and `CONNECTOR_KEYRING` are all set. Each entry must be strong, different from the other
purpose keyrings, and different from `SESSION_SECRET`. A placeholder, whitespace around a
secret, a repeated secret, and a secret equal to `SESSION_SECRET` are refused. Error text
names the variable only. Development and test may leave a keyring unset; unset derives
`v0-legacy` from `SESSION_SECRET`. Production does not.

Format is `kid:secret` with optional retired entries after the first (`current,previous`).
The first entry is the current key. A secret must not contain a comma or whitespace.
Generate each secret separately, for example with `openssl rand -base64 48`, and store it
only in the operator secret store. `docker-compose.prod.yml` refuses to start the API or
the worker when any of the four is missing from Compose interpolation (the shell, a
Compose `.env` file, or `--env-file`). `env_file:` does not fill those `${VAR:?}` entries.

There is no product backup of keyrings and no in-product break-glass for a locked-out sole
administrator (OD-13). This runbook is that procedure.

## Back up the keyrings

1. After generating or changing a keyring, put the four purpose variables and
   `SESSION_SECRET` in the operator secret store. Label each entry with the variable name
   and the key id. Include every retired entry that is still required to read existing
   ciphertext.
2. Keep that copy outside the application database, outside git, and outside CI logs.
   Never store keyrings in a database backup, a database snapshot, or the same archive as
   either. A dump of the database must not contain keyring files.
3. Record who took the backup and when in the change record. Record variable names and key
   ids only. Do not write the secret values into the change record.
4. Update the keyring backup before cut-over so it contains the new current key and any
   previous key that production will still list.
5. If the current MFA key is lost and the previous entry was not retained, MFA ciphertext
   cannot be opened (the account must enrol again). Connector ciphertext stays stored and
   cannot be opened. Session cookies signed by a missing key stop working.

## Rotate, including the first move off derived keys

`apps/api/scripts/rotate_purpose_keys.py` refuses `APP_ENV=production` and has no override.
It prints counts only. Run it on a database copy, then cut over. The copy host holds
production data and key material, so treat it as production-sensitive: restrict who can
log in, do not snapshot it, and destroy the host and its disks after cut-over.

### Maintenance window before the copy

Stop the API and the worker before taking the copy. Production must not keep writing while
the copy is made or while the rotated database is prepared. Announce the maintenance
window, stop both processes, and only then take the database copy. Writes that arrive
after the copy and before the stop are lost, so the stop comes first.

The database copy must not include keyring files. Put keyrings only in the environment of
the rotation process.

### First migration, from derived keys to explicit keyrings

Until this migration, MFA and connector ciphertext is sealed under `v0-legacy`, derived
from `SESSION_SECRET`. Adding four new keyrings in production without rotating first makes
that ciphertext unreadable: every MFA user is locked out and every connector breaks.

Production cannot keep `v0-legacy:<session-secret>` as a previous key. That secret equals
`SESSION_SECRET`, which is refused. The same retired secret in more than one ring is also
refused. The working procedure is on the copy, outside production:

1. Point a process at the copy with `APP_ENV` set to something other than production. Do
   not point the tool at the live database.
2. For each of the four purpose variables, set the ring to this shape and this shape only:

   `new-kid:<generated>,v0-legacy:<session-secret>`

   `<generated>` is a new secret for that purpose. The four generated secrets must differ
   from each other. `<session-secret>` means the current value of `SESSION_SECRET`, used
   so the copy can open ciphertext that was derived from it. It is not a new secret, and
   it must not be written into the production environment. Describe it in change records
   as `SESSION_SECRET`. Do not paste the value.
3. From `apps/api` on the copy host:

   `python scripts/rotate_purpose_keys.py --dry-run`

   `python scripts/rotate_purpose_keys.py`

   Resume a partial run with `--limit` and `--after-id`. The command re-encrypts MFA,
   credential-store, Slack, and Gmail rows onto the new key. It deletes sessions whose
   signing key id is retired, and sessions with a null `signing_key_id` once the current
   session key is not `v0-legacy`.
4. Read the JSON counts. Do not cut over while credential-store, Slack, or Gmail still
   report failed rows: those rows would be unreadable once production drops `v0-legacy`.
   An MFA row that cannot be opened is marked `reenrol.<kid>` and stays enabled. That user
   cannot get a session until an administrator clears it, or until the sole-admin
   procedure below. The marker does not need the old key.
5. Give production the new key only, one distinct secret per ring:

   `new-kid:<generated>`

   Do not include `v0-legacy`. Do not put `SESSION_SECRET` in a production keyring.

### A later rotation

Stop the API and the worker, then take the copy, as above. On the copy, outside
production, set only the purpose being rotated to:

`new-kid:<generated>,previous-kid:<previous>`

`<previous>` is that purpose's current key, not `SESSION_SECRET`, and it is not placed in
the other rings. Leave the other three rings as production has them. After a clean apply,
production may list the previous key id until a later rotation has re-encrypted every row
that still depends on it. The first migration cannot do that, because its previous secret
is `SESSION_SECRET`.

### Cut over and destroy the copy

1. Update the keyring backup (see above) before changing production. The backup stays in
   the secret store, not in the database snapshot.
2. With the API and worker still stopped, promote or restore the rotated copy so it is the
   production database. Set the production environment to the keyrings from the step above.
3. Start the API and the worker only after `python -m app.core.config_contract check`
   accepts the environment. The production process still refuses to run the rotation script.
4. Expect users to sign in again when the session key changed.
5. Destroy the rotation host and its disks. Do not keep a snapshot of that host. It held
   production data together with key material.

The tool's output is counts. Do not log the process environment.

## Recover a sole administrator locked out of MFA

This procedure changes who can sign in. It is not a shortcut for account takeover.

`user_mfa` is one row per user, not per workspace. Clearing it removes MFA for every workspace that user belongs to. Say that in the change record before anyone approves.

When another active administrator of the workspace exists, use the product instead:

- Lost authenticator, and the sign-in challenge still accepts a code:
  `POST /api/members/reset-mfa/{user_id}` (audit action `auth.mfa_admin_reset`).
- Undecryptable MFA secret (`reenrol.<kid>`):
  `POST /api/members/clear-mfa-reenrol/{user_id}` (audit action
  `auth.mfa_reenrol_cleared`).

Both routes require a current active administrator of that workspace.

### Try a recovery code first

If password sign-in still returns an MFA challenge, the user submits a recovery code to
`POST /api/auth/mfa/verify-login`. Do not change the database while an unused recovery
code can do that. Continue here only when no unused recovery code remains, or when
sign-in returns `mfa_reset_required` and will not accept a code (the stored secret is the
`reenrol.` marker).

### Identity check and a second approval

1. Verify the person out of band, by a method agreed in advance (for example a live video
   conversation against an identity the organisation already holds). Record the method
   name. Do not put document numbers, images, or recovery codes in the database.
2. A second person, or the owner, must approve the recovery before the transaction. Record
   that approver and a change reference from the operator change system.
3. Stop if either the identity check or the approval is missing.

### Confirm the account is the sole active administrator

Take a database backup first. The backup must not contain keyrings. Then confirm the
workspace has exactly one active administrator, and that person is the locked-out user.
An active administrator is a `workspace_members` row with `suspended = false` whose `role`
is `admin`, or whose `role` equals `custom_roles.name` for that workspace and that custom
role has `can_admin` true.

Replace `<workspace_id>` with the numeric workspace id.

```sql
SELECT m.user_id, m.role
FROM workspace_members AS m
LEFT JOIN custom_roles AS c
  ON c.workspace_id = m.workspace_id AND c.name = m.role
WHERE m.workspace_id = <workspace_id>
  AND m.suspended = false
  AND (m.role = 'admin' OR c.can_admin = true);
```

Stop if that query returns any user other than the locked-out account. Use the in-product
route instead. Also list the user's other workspaces and include them in the approval,
because the MFA row is shared:

```sql
SELECT workspace_id, role, suspended
FROM workspace_members
WHERE user_id = <user_id>;
```

### Database change

`audit_events.occurred_at` and `user_mfa.updated_at` are timestamps without time zone.
`CURRENT_TIMESTAMP` follows the session time zone. Set the session to UTC first so those
values are UTC. Do not remove that statement.

The pending-enrolment value is the SQL string literal `'reenrol-pending!.pending'`. Copy
that literal, including the exclamation mark. Do not retype it and do not rebuild it from
the constant name. It is a marker, not a key and not a TOTP secret. In the update, replace
`<pending-enrolment-marker>` with that quoted literal.

Replace `<user_id>`, `<workspace_id>`, `<operator>`, `<approver>`,
`<verification-method>` and `<change-reference>` before running. `<operator>` is the
person who runs the change. `<approver>` is the second person or the owner.
`<verification-method>` is the out-of-band method name. `<change-reference>` is the change
id. None of these are key material. Leave `user_id` null unless the operator is a row in
`users`; the operator identity is still stored in `email` and in `details`.

```sql
SET TIME ZONE 'UTC';
BEGIN;

UPDATE user_mfa
SET enabled = false,
    totp_secret_encrypted = <pending-enrolment-marker>,
    updated_at = CURRENT_TIMESTAMP
WHERE user_id = <user_id>;
```

If the update reports zero rows, roll back and stop. There is no MFA row to clear.

Before `COMMIT`, this check must return one row, `enabled` false, and `marker_ok` true.
If it does not, roll back. A marker without the exclamation mark leaves `enabled` false
and no pending marker, and the next password login would issue a full session without MFA.

```sql
SELECT user_mfa.enabled,
       user_mfa.totp_secret_encrypted IS NOT DISTINCT FROM expected.marker AS marker_ok
FROM user_mfa
CROSS JOIN (SELECT 'reenrol-pending!.pending' AS marker) AS expected
WHERE user_mfa.user_id = <user_id>;
```

Then delete the codes and sessions and write the audit row:

```sql
DELETE FROM mfa_recovery_codes WHERE user_id = <user_id>;
DELETE FROM mfa_login_tokens WHERE user_id = <user_id>;
DELETE FROM user_sessions WHERE user_id = <user_id>;

INSERT INTO audit_events (
    occurred_at,
    action,
    user_id,
    email,
    workspace_id,
    resource_type,
    resource_id,
    details
) VALUES (
    CURRENT_TIMESTAMP,
    'auth.mfa_operator_recovery',
    NULL,
    '<operator>',
    <workspace_id>,
    'user',
    CAST(<user_id> AS varchar),
    '{"procedure":"sole_admin_mfa_lockout","target_user_id":<user_id>,"operator":"<operator>","approver":"<approver>","verification_method":"<verification-method>","change_reference":"<change-reference>","affects_every_workspace":true}'
);

COMMIT;
```

The next password login grants only a five-minute enrolment session with no workspace
privileges. Workspace access returns after the user confirms a new authenticator. Confirm
the audit row:

```sql
SELECT id, occurred_at, action, email, workspace_id, resource_type, resource_id, details
FROM audit_events
WHERE action = 'auth.mfa_operator_recovery'
  AND workspace_id = <workspace_id>
ORDER BY id DESC;
```

Do not delete that audit row. `details` must name the operator, the approver, the
verification method, and the change reference. It must not contain key material,
ciphertext, or recovery codes.
