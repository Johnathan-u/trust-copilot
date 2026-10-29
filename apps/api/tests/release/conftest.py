"""Delete rows a release test committed, by primary key, and compare counts.

The shared ``db_session`` fixture only rolls back its own transaction. Request
handlers commit on another connection. Callers record the user, workspace and
credential ids they insert. Child rows (sessions, MFA, audit) are found from
those ids and deleted by id. No trigger changes, no truncation.
"""

from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

COUNT_TABLES = (
    "workspaces",
    "users",
    "workspace_members",
    "user_mfa",
    "mfa_recovery_codes",
    "mfa_login_tokens",
    "user_sessions",
    "credential_store",
    "audit_events",
)
DELETE_ORDER = (
    "audit_events",
    "mfa_login_tokens",
    "mfa_recovery_codes",
    "user_sessions",
    "user_mfa",
    "workspace_members",
    "credential_store",
    "users",
    "workspaces",
)
OWNED: dict[str, list[int]] = {"users": [], "workspaces": [], "credentials": []}


def counts(db: Session) -> dict[str, int]:
    return {
        table: int(db.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)
        for table in COUNT_TABLES
    }


def _ids_where(db: Session, table: str, column: str, values: list) -> list[int]:
    if not values:
        return []
    statement = text(f"SELECT id FROM {table} WHERE {column} IN :values").bindparams(
        bindparam("values", expanding=True)
    )
    return [int(row[0]) for row in db.execute(statement, {"values": list(values)})]


def _delete_ids(db: Session, table: str, ids: list[int]) -> None:
    if not ids:
        return
    statement = text(f"DELETE FROM {table} WHERE id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    db.execute(statement, {"ids": list(ids)})


def delete_owned(db: Session) -> None:
    user_ids = list(OWNED["users"])
    workspace_ids = list(OWNED["workspaces"])
    credential_ids = list(OWNED["credentials"])
    audit_ids = set(_ids_where(db, "audit_events", "user_id", user_ids))
    audit_ids.update(_ids_where(db, "audit_events", "workspace_id", workspace_ids))
    if credential_ids:
        statement = text(
            "SELECT id FROM audit_events "
            "WHERE resource_type = 'credential_store' AND resource_id IN :values"
        ).bindparams(bindparam("values", expanding=True))
        audit_ids.update(
            int(row[0])
            for row in db.execute(statement, {"values": [str(item) for item in credential_ids]})
        )
    member_ids = set(_ids_where(db, "workspace_members", "user_id", user_ids))
    member_ids.update(_ids_where(db, "workspace_members", "workspace_id", workspace_ids))
    found = {
        "audit_events": list(audit_ids),
        "mfa_login_tokens": _ids_where(db, "mfa_login_tokens", "user_id", user_ids),
        "mfa_recovery_codes": _ids_where(db, "mfa_recovery_codes", "user_id", user_ids),
        "user_sessions": _ids_where(db, "user_sessions", "user_id", user_ids),
        "user_mfa": _ids_where(db, "user_mfa", "user_id", user_ids),
        "workspace_members": list(member_ids),
        "credential_store": credential_ids,
        "users": user_ids,
        "workspaces": workspace_ids,
    }
    for table in DELETE_ORDER:
        _delete_ids(db, table, found[table])


def assert_back_to_baseline(db: Session, before: dict[str, int]) -> None:
    after = counts(db)
    detail = ", ".join(f"{table} {before[table]}->{after[table]}" for table in COUNT_TABLES)
    assert after == before, detail
