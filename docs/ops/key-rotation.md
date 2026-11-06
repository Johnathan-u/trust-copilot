# Purpose keyrings: backup, rotation, and sole-admin MFA recovery

Operator runbook for production key custody (TC-07-002a). It does not contain key material.
Do not paste a keyring, `SESSION_SECRET`, ciphertext, TOTP secret, or recovery code into
this file, a ticket, a log, or a shell history that is retained.

Production refuses to start unless `SESSION_KEYRING`, `OAUTH_STATE_KEYRING`, `MFA_KEYRING`
and `CONNECTOR_KEYRING` are all set. Each entry must be strong, different from the other
purpose keyrings, and different from `SESSION_SECRET`. Error text names the variable only.
Development and test may leave a keyring unset; unset derives `v0-legacy` from
`SESSION_SECRET`. Production does not.

Format is `kid:secret` with optional retired entries after the first (`current,previous`).
The first entry is the current key. A secret must not contain a comma. Generate each secret
separately, for example with `openssl rand -base64 48`, and store it only in the production
secret store (`.env.production`, the same file Compose already requires for `SESSION_SECRET`).
`docker-compose.prod.yml` refuses to start the API or the worker when any of the four is
missing.

There is no product backup of keyrings and no in-product break-glass for a locked-out sole
administrator (OD-13). This runbook is that procedure.

## Back up the keyrings

1. After generating or changing a keyring, copy the four purpose variables and
   `SESSION_SECRET` into the operator secret store. Label each entry with the variable name
   and the key id. Include every retired entry that is still required to read existing
   ciphertext.
2. Keep that copy outside the application database, outside git, and outside CI logs.
3. Record who took the backup and when in the change record. Record variable names and key
   ids only. Do not write the secret values into the change record.
4. Update the backup before cut-over so it contains the new current key and the retained
   previous key.
5. If the current MFA key is lost and the previous entry was not retained, MFA ciphertext
   cannot be opened (the account must enrol again). Connector ciphertext stays stored and
   cannot be opened. Session cookies signed by a missing key stop working.

## Rotate a purpose key in production

`apps/api/scripts/rotate_purpose_keys.py` refuses `APP_ENV=production` and has no override.
It prints counts only. Run it on a database copy, then cut over.

1. Take a restorable copy of the production database. Point a process at that copy with
   `APP_ENV` set to something other than production. Do not point the tool at the live
   database.
2. On that process, set the purpose keyring being rotated so the new key id is first and
   the previous key id is retained. The shape is `new-kid:<generated>,previous-kid:<generated>`.
   Leave the other three purpose keyrings as they are in production. The new secret must be
   strong and must not match `SESSION_SECRET` or another purpose key.
3. From `apps/api`, rehearse:

   `python scripts/rotate_purpose_keys.py --dry-run`

4. Apply on the copy:

   `python scripts/rotate_purpose_keys.py`

   Resume a partial run with `--limit` and `--after-id`. The command re-encrypts MFA,
   credential-store, Slack, and Gmail rows onto the current key. It deletes sessions whose
   signing key id is retired, and sessions with a null `signing_key_id` once the current
   session key is not `v0-legacy`.
5. Read the JSON counts. Confirm the dry-run and the apply were against the copy. An MFA
   row that cannot be opened is marked `reenrol.<kid>` and stays enabled. That user cannot
   get a session until an administrator clears it, or until the sole-admin procedure below.
6. Update the keyring backup (see above) before changing production.
7. Cut over. Stop the API and the worker. Promote or restore the rotated copy so it is the
   production database. Set the production environment to the same keyring (new current key
   first, previous key retained). Start the API and the worker only after
   `python -m app.core.config_contract check` accepts the environment. The production
   process still refuses to run the rotation script.
8. Expect users to sign in again when the session key changed. Remove a previous key from
   the ring only after a later rotation has re-encrypted every row that still depends on it,
   and only after the backup contains both keys.

The tool's output is counts. Do not log the process environment.

## Recover a sole administrator locked out of MFA

When another active administrator exists, use the product:

- Lost authenticator: `POST /api/members/reset-mfa/{user_id}` (audit action
  `auth.mfa_admin_reset`).
- Undecryptable MFA secret (`reenrol.<kid>`): `POST /api/members/clear-mfa-reenrol/{user_id}`
  (audit action `auth.mfa_reenrol_cleared`).

Both routes require a current active administrator of that workspace. If the locked-out
user is the only one, those routes cannot be called. Use the database procedure in this
section. It does not reset the password, and it does not reveal or replace any key.

Take a database backup first. Then confirm the workspace has exactly one active
administrator, and that person is the locked-out user. An active administrator is a
`workspace_members` row with `suspended = false` whose `role` is `admin`, or whose `role`
equals `custom_roles.name` for that workspace and that custom role has `can_admin` true.

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
route instead.

In one transaction, mark that user's MFA row as pending enrolment, delete recovery codes,
login challenges, and sessions, and insert an audit row. Replace `<user_id>` and
`<workspace_id>` with the numeric ids from the lookup. Replace `<pending-enrolment-marker>`
with a quoted SQL string. The string's contents are `REENROL_PENDING_MARK` from
`apps/api/app/core/keys.py`, a dot, and a non-secret label such as the word pending. The
constant begins with `reenrol-pending`. Do not write a TOTP secret or a key into the column.
If the update reports zero rows, roll back and stop: there is no MFA row to clear.

```sql
BEGIN;

UPDATE user_mfa
SET enabled = false,
    totp_secret_encrypted = <pending-enrolment-marker>,
    updated_at = CURRENT_TIMESTAMP
WHERE user_id = <user_id>;

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
    NULL,
    <workspace_id>,
    'user',
    CAST(<user_id> AS varchar),
    '{"procedure":"sole_admin_mfa_lockout","target_user_id":<user_id>}'
);

COMMIT;
```

The next password login grants only a five-minute enrolment session with no workspace
privileges. Workspace access returns after the user confirms a new authenticator. Confirm
the audit row:

```sql
SELECT id, occurred_at, action, workspace_id, resource_type, resource_id
FROM audit_events
WHERE action = 'auth.mfa_operator_recovery'
  AND workspace_id = <workspace_id>
ORDER BY id DESC;
```

Do not delete that audit row. The `details` value records the procedure name and the
target user id. It must not contain key material, ciphertext, or recovery codes.
