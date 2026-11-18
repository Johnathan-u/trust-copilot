# Feature flags

Workspace flags live in `feature_flags`. The admin API is `PATCH /api/feature-flags`.
A caller who is not a workspace admin receives 403 and no audit row. An empty or
over-long name receives 400 and no audit row.

## Who changed a flag

There is no actor column on `feature_flags`. The record is `audit_events`.

| Field | Value |
|---|---|
| `action` | `feature_flag.updated` |
| `user_id` | The signed-in admin. Null only when `set_flag` is called with no actor. |
| `email` | The admin's email, when the session has one. |
| `workspace_id` | The workspace whose row changed. |
| `resource_type` | `feature_flag` |
| `resource_id` | The flag key. |
| `details` | JSON: `flag_name`, `old_enabled`, `new_enabled`, `changed`. |

`old_enabled` is JSON `null` when the workspace had no row. `new_enabled` is the
value that was requested. `changed` is false when a row already stored that value.

A no-op still writes one event and does not rewrite the row. A real change writes
the row and the event in one commit (`persist_audit` commits the pending flag
change). The log line from `audit_log` omits null fields; the database `details`
keeps `old_enabled: null`.

`POST /api/feature-flags/seed` inserts missing built-in defaults and skips rows
that already exist. It does not write `feature_flag.updated`.

```sql
SELECT id, occurred_at, user_id, email, workspace_id, resource_id, details
FROM audit_events
WHERE action = 'feature_flag.updated'
ORDER BY id DESC;
```

## FEATURE_* environment variables

The variable name is `FEATURE_` plus the flag key in upper snake case. A dot in
the key becomes an underscore. `connectors.aws` is `FEATURE_CONNECTORS_AWS`.

| Value | Meaning |
|---|---|
| unset | No environment value. |
| `1`, `true`, `yes` | Enabled. Letter case is ignored. |
| anything else that is set, including `0` and an empty string | Disabled. |

Production is `APP_ENV`, detected by `app.core.session.is_production_env()`
(settings and the process environment, surrounding whitespace and letter case
ignored).

In production a stored row wins. `FEATURE_*` is used only when that workspace
has no row for the flag, and it wins over the built-in default. It does not
override a row, and applying it is not an admin action, so it is not audited.

In development, test, and staging a set variable overrides the stored row. That
is the local and CI behaviour. Do not rely on it in production.

The built-in list and its defaults are `KNOWN_FLAGS` in
`apps/api/app/services/feature_flags.py`. An unknown flag with no row and no
variable is off.

## What a flag does not do

A flag does not grant a role. Turning a flag off does not disable CSRF, session
checks, or audit. Nothing in the build fails when an advertised feature is
flagged off. Those checks are still open on TC-16-006.
