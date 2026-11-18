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

A flag does not grant a role. A name for a security control is rejected.
`PATCH /api/feature-flags` and `GET /api/feature-flags/{flag_name}` return 400
with `Security controls are not feature flags`, and no audit row is written.
`is_enabled` and `set_flag` raise `SecurityFlagError` instead of resolving that
name to false. `POST /api/feature-flags/seed` skips such a name.

The controls are permissions, CSRF, sessions, authentication, MFA, audit, rate
limits and tenant isolation. The match is the flag's path segment: it equals
one of those tokens, or starts with the token and an underscore (`csrf`,
`audit.write`, `auth_bypass`, `rate-limit.login`). A product flag such as
`connectors.aws` is not in that set.

The build runs `python -m pytest tests/release/test_feature_flags.py -q` from
`apps/api` as part of `pytest -rs`. That file fails if a denylist of security
modules looks a flag up, and if Gmail or Slack (the flags named by the public
home and pricing pages) is default-off. Other registered flags may default off
only when the test classifies them as not advertised.
