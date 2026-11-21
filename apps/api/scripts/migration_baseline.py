#!/usr/bin/env python3
"""Qualify the audited-SHA migration snapshot (TC-03-004).

The planning baseline SHA c20f949161ac12a619b396d30904448ffd74d532 has one
alembic head, revision 075. This tool builds that schema in an empty database,
inserts the synthetic fixture, and upgrades to the single current head.

It never stamps a version. A database that claims revision 075 without the
core tables is refused, and the version row is left as it was.

Usage (from apps/api/), with DATABASE_URL set to a disposable database:

  python scripts/migration_baseline.py qualify --report /tmp/backfill-report.json
  python scripts/migration_baseline.py fresh --report /tmp/fresh-upgrade.json
  python scripts/migration_baseline.py upgrade --report /tmp/backfill-report.json

qualify builds the synthetic snapshot, upgrades it, checks survival, downgrades
to 075, checks the original rows again, then upgrades to head once more.
fresh upgrades an empty database to head. upgrade starts from a database that
is already at revision 075 and does not downgrade it.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

# Head of the migration tree at the audited SHA. The versions in that commit
# are 001 through 075 in one line.
AUDITED_SHA = "c20f949161ac12a619b396d30904448ffd74d532"
BASELINE_REVISION = "075"
API_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "audited_snapshot_075.sql"
REFUSED = "MIGRATION_BASELINE_REFUSED"
FAILED = "MIGRATION_BASELINE_FAILED"
_URL_RE = re.compile(r"postgresql(?:\+\w+)?://\S+", re.IGNORECASE)
_DML_RE = re.compile(r"\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM)\b", re.IGNORECASE)
_TABLE_RE = re.compile(
    r"\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.IGNORECASE,
)
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
REQUIRED_COLUMNS = {
    "workspaces": ("name", "slug"),
    "users": ("email",),
    "workspace_members": ("workspace_id", "user_id", "role"),
    "documents": ("workspace_id", "storage_key", "filename"),
    "questionnaires": ("workspace_id", "filename", "storage_key"),
    "questions": ("questionnaire_id", "text"),
    "answers": ("question_id", "text"),
}
FILE_KEY_COLUMNS = (("documents", "storage_key"), ("questionnaires", "storage_key"))
# Rows inserted by the audited fixture. Later migrations may add rows to other
# tables; those increases are reported, and a drop in any baseline table is not.
AUDITED_TABLES = (
    "workspaces",
    "users",
    "workspace_members",
    "documents",
    "questionnaires",
    "questions",
    "answers",
)


class SnapshotRefused(RuntimeError):
    """The database is not the audited snapshot. Its version was not changed."""


class UpgradeFailed(RuntimeError):
    """A migration command failed. The version was not stamped."""


def redact(value: str) -> str:
    return _URL_RE.sub("postgresql://redacted", value)


def alembic_config() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(API_ROOT))
    return cfg


def script_directory(cfg: Config) -> ScriptDirectory:
    return ScriptDirectory.from_config(cfg)


def single_head(script: ScriptDirectory) -> str:
    heads = list(script.get_heads())
    if len(heads) != 1:
        found = ", ".join(heads) if heads else "(none)"
        raise UpgradeFailed(f"{FAILED}: expected one alembic head, found {len(heads)}: {found}")
    return heads[0]


def revision_path(script: ScriptDirectory, start: str, head: str) -> list[str]:
    children: dict[str | None, list[str]] = {}
    for rev in script.walk_revisions():
        down = rev.down_revision
        parents = down if isinstance(down, tuple) else (down,)
        for parent in parents:
            children.setdefault(parent, []).append(rev.revision)
    path: list[str] = []
    current = start
    seen = {start}
    while current != head:
        nxt = children.get(current, [])
        if len(nxt) != 1:
            raise UpgradeFailed(
                f"{FAILED}: revision {current} has {len(nxt)} children on the way to {head}"
            )
        current = nxt[0]
        if current in seen:
            raise UpgradeFailed(f"{FAILED}: revision cycle at {current}")
        seen.add(current)
        path.append(current)
    return path


def _function_map(tree: ast.AST) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _reachable(functions: dict[str, ast.FunctionDef], name: str, seen: set[str]) -> None:
    if name in seen or name not in functions:
        return
    seen.add(name)
    for node in ast.walk(functions[name]):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            _reachable(functions, node.func.id, seen)


def _string_pieces(node: ast.AST) -> list[str]:
    pieces: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            pieces.append(child.value)
        elif isinstance(child, ast.JoinedStr):
            parts: list[str] = []
            for value in child.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
            if parts:
                pieces.append("".join(parts))
    return pieces


def backfill_targets(script: ScriptDirectory) -> dict[str, set[str]]:
    """Revisions whose upgrade path contains data DML, and the literal tables named there."""
    targets: dict[str, set[str]] = {}
    for rev in script.walk_revisions():
        path = Path(rev.path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = _function_map(tree)
        if "upgrade" not in functions:
            continue
        reached: set[str] = set()
        _reachable(functions, "upgrade", reached)
        sql: list[str] = []
        for name in reached:
            sql.extend(_string_pieces(functions[name]))
        if not any(_DML_RE.search(piece) for piece in sql):
            continue
        tables: set[str] = set()
        for piece in sql:
            tables.update(match.group(1).lower() for match in _TABLE_RE.finditer(piece))
        targets[rev.revision] = tables
    return targets


def connect(url: str) -> Engine:
    return create_engine(url, poolclass=NullPool)


def public_tables(conn: Connection) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'alembic_version' "
            "ORDER BY tablename"
        )
    )
    return [row[0] for row in rows if _IDENT_RE.match(row[0])]


def current_revision(conn: Connection) -> str | None:
    exists = conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar()
    if exists is None:
        return None
    rows = [row[0] for row in conn.execute(text("SELECT version_num FROM alembic_version"))]
    if len(rows) != 1:
        raise SnapshotRefused(
            f"{REFUSED}: alembic_version has {len(rows)} rows; refusing to stamp over it"
        )
    return str(rows[0])


def column_names(conn: Connection, table: str) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table"
        ),
        {"table": table},
    )
    return {row[0] for row in rows}


def require_baseline_shape(conn: Connection) -> str:
    revision = current_revision(conn)
    if revision != BASELINE_REVISION:
        found = revision if revision is not None else "(no alembic version)"
        raise SnapshotRefused(
            f"{REFUSED}: expected revision {BASELINE_REVISION}, found {found}; "
            "refusing to stamp this snapshot"
        )
    missing: list[str] = []
    for table, columns in REQUIRED_COLUMNS.items():
        present = column_names(conn, table)
        if not present:
            missing.append(table)
            continue
        for column in columns:
            if column not in present:
                missing.append(f"{table}.{column}")
    if missing:
        raise SnapshotRefused(
            f"{REFUSED}: partial snapshot is missing {', '.join(missing)}; "
            "refusing to stamp over it"
        )
    return revision


def require_empty(conn: Connection) -> None:
    revision = current_revision(conn)
    tables = public_tables(conn)
    if revision is not None or tables:
        raise SnapshotRefused(
            f"{REFUSED}: database is not empty (revision {revision}, {len(tables)} tables); "
            "refusing to stamp over it"
        )


def run_upgrade(cfg: Config, revision: str) -> None:
    try:
        command.upgrade(cfg, revision)
    except Exception as exc:
        raise UpgradeFailed(
            f"{FAILED}: alembic upgrade {revision} failed: {redact(str(exc))}"
        ) from exc


def run_downgrade(cfg: Config, revision: str) -> None:
    try:
        command.downgrade(cfg, revision)
    except Exception as exc:
        raise UpgradeFailed(
            f"{FAILED}: alembic downgrade {revision} failed: {redact(str(exc))}"
        ) from exc


def apply_fixture(conn: Connection) -> None:
    if not FIXTURE.is_file():
        raise UpgradeFailed(f"{FAILED}: missing fixture {FIXTURE.name}")
    script = FIXTURE.read_text(encoding="utf-8")
    statements = [part.strip() for part in script.split(";") if part.strip()]
    for statement in statements:
        # The driver executes the fixture as written. text() would treat :12
        # inside the locator JSON as a bind parameter.
        conn.exec_driver_sql(statement)


def _freeze(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, (bytes, memoryview)):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {str(key): _freeze(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_freeze(item) for item in value]
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return iso()
    return str(value)


def _primary_key(conn: Connection, table: str) -> str | None:
    rows = conn.execute(
        text(
            "SELECT a.attname "
            "FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey) "
            "WHERE i.indrelid = CAST(:regclass AS regclass) AND i.indisprimary "
            "ORDER BY a.attnum"
        ),
        {"regclass": f"public.{table}"},
    ).fetchall()
    if len(rows) != 1:
        return None
    name = str(rows[0][0])
    if not _IDENT_RE.match(name):
        return None
    return name


def _table_image(conn: Connection, table: str) -> dict[str, object]:
    pk = _primary_key(conn, table)
    rows = conn.execute(text(f'SELECT * FROM "{table}"')).mappings().all()
    if pk is None:
        return {"pk": None, "count": len(rows), "rows": None}
    images: dict[str, str] = {}
    for row in rows:
        key = json.dumps(_freeze(row[pk]), sort_keys=True, default=str)
        images[key] = json.dumps(
            {name: _freeze(row[name]) for name in row.keys()},
            sort_keys=True,
            default=str,
        )
    return {"pk": pk, "count": len(rows), "rows": images}


def snapshot(conn: Connection, tables: set[str] | None = None) -> dict[str, dict[str, object]]:
    names = public_tables(conn)
    if tables is not None:
        names = [name for name in names if name in tables]
    return {name: _table_image(conn, name) for name in names}


def _diff_table(
    before: dict[str, object] | None, after: dict[str, object] | None
) -> dict[str, object]:
    if before is None and after is None:
        return {"inserted": 0, "deleted": 0, "updated": 0, "measurable": True}
    if before is None:
        return {
            "inserted": int(after["count"]) if after else 0,
            "deleted": 0,
            "updated": 0,
            "measurable": True,
            "row_count_before": 0,
            "row_count_after": int(after["count"]) if after else 0,
        }
    if after is None:
        return {
            "inserted": 0,
            "deleted": int(before["count"]),
            "updated": 0,
            "measurable": True,
            "row_count_before": int(before["count"]),
            "row_count_after": 0,
        }
    before_rows = before.get("rows")
    after_rows = after.get("rows")
    result = {
        "row_count_before": int(before["count"]),
        "row_count_after": int(after["count"]),
    }
    if not isinstance(before_rows, dict) or not isinstance(after_rows, dict):
        result.update(
            {
                "inserted": None,
                "deleted": None,
                "updated": None,
                "measurable": False,
                "reason": "no single-column primary key",
            }
        )
        return result
    inserted = len(set(after_rows) - set(before_rows))
    deleted = len(set(before_rows) - set(after_rows))
    updated = sum(
        1 for key in set(before_rows) & set(after_rows) if before_rows[key] != after_rows[key]
    )
    result.update(
        {"inserted": inserted, "deleted": deleted, "updated": updated, "measurable": True}
    )
    return result


def diff_snapshots(
    before: dict[str, dict[str, object]], after: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    for name in sorted(set(before) | set(after)):
        table_diff = _diff_table(before.get(name), after.get(name))
        moved = any(
            table_diff.get(key) not in (0, None) for key in ("inserted", "deleted", "updated")
        )
        count_moved = table_diff.get("row_count_before") != table_diff.get("row_count_after")
        if moved or count_moved:
            table_diff["name"] = name
            changes.append(table_diff)
    return changes


def rows_affected(changes: list[dict[str, object]]) -> int | None:
    if any(not change.get("measurable") for change in changes):
        return None
    total = 0
    for change in changes:
        total += int(change["inserted"]) + int(change["deleted"]) + int(change["updated"])
    return total


def foreign_keys(conn: Connection) -> list[dict[str, str]]:
    rows = conn.execute(
        text(
            "SELECT c.conname, rel.relname, pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c "
            "JOIN pg_class rel ON rel.oid = c.conrelid "
            "JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace "
            "WHERE c.contype = 'f' AND nsp.nspname = 'public' "
            "ORDER BY rel.relname, c.conname"
        )
    )
    return [{"name": row[0], "table": row[1], "definition": row[2]} for row in rows]


def row_counts(conn: Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in public_tables(conn):
        counts[table] = int(conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() or 0)
    return counts


def storage_keys(conn: Connection) -> list[str]:
    found: list[str] = []
    for table, column in FILE_KEY_COLUMNS:
        if column not in column_names(conn, table):
            continue
        rows = conn.execute(
            text(
                f'SELECT "{column}" FROM "{table}" '
                f'WHERE "{column}" IS NOT NULL ORDER BY "{column}"'
            )
        )
        found.extend(str(row[0]) for row in rows)
    return found


def answer_texts(conn: Connection) -> list[str]:
    if "text" not in column_names(conn, "answers"):
        return []
    rows = conn.execute(text("SELECT text FROM answers WHERE text IS NOT NULL ORDER BY id"))
    return [str(row[0]) for row in rows]


def capture(conn: Connection) -> dict[str, object]:
    return {
        "revision": current_revision(conn),
        "row_counts": row_counts(conn),
        "foreign_keys": foreign_keys(conn),
        "storage_keys": storage_keys(conn),
        "answer_texts": answer_texts(conn),
    }


def _definitions(keys: list[dict[str, str]]) -> set[str]:
    return {f"{item['table']} {item['definition']}" for item in keys}


def compare(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    before_counts = dict(before["row_counts"])
    after_counts = dict(after["row_counts"])
    shared = sorted(set(before_counts) & set(after_counts))
    missing_tables = sorted(set(before_counts) - set(after_counts))
    losses = {
        table: {"before": before_counts[table], "after": after_counts[table]}
        for table in shared
        if after_counts[table] < before_counts[table]
    }
    increases = {
        table: {"before": before_counts[table], "after": after_counts[table]}
        for table in shared
        if after_counts[table] > before_counts[table]
    }
    audited_deltas = {
        table: {"before": before_counts[table], "after": after_counts.get(table)}
        for table in AUDITED_TABLES
        if before_counts.get(table) != after_counts.get(table)
    }
    before_keys = _definitions(list(before["foreign_keys"]))
    after_keys = _definitions(list(after["foreign_keys"]))
    missing_fks = sorted(before_keys - after_keys)
    return {
        "row_counts_match": not losses and not missing_tables and not audited_deltas,
        "missing_tables": missing_tables,
        "row_count_losses": losses,
        "row_count_increases": increases,
        "audited_row_count_deltas": audited_deltas,
        "tables_added": sorted(set(after_counts) - set(before_counts)),
        "foreign_keys_preserved": not missing_fks,
        "foreign_keys_missing": missing_fks,
        "foreign_key_count_before": len(list(before["foreign_keys"])),
        "foreign_key_count_after": len(list(after["foreign_keys"])),
        "storage_keys_preserved": list(before["storage_keys"]) == list(after["storage_keys"]),
        "answer_texts_preserved": list(before["answer_texts"]) == list(after["answer_texts"]),
    }


def survival_ok(survival: dict[str, object]) -> bool:
    return bool(
        survival["row_counts_match"]
        and survival["foreign_keys_preserved"]
        and survival["storage_keys_preserved"]
        and survival["answer_texts_preserved"]
    )


def step_to_head(
    cfg: Config, engine: Engine, script: ScriptDirectory, head: str
) -> list[dict[str, object]]:
    targets = backfill_targets(script)
    path = revision_path(script, BASELINE_REVISION, head)
    reports: list[dict[str, object]] = []
    for revision in path:
        named = targets.get(revision)
        before_image: dict[str, dict[str, object]] | None = None
        if named is not None:
            with engine.connect() as conn:
                before_image = snapshot(conn, named or None)
        run_upgrade(cfg, revision)
        if named is None or before_image is None:
            continue
        with engine.connect() as conn:
            existing = set(public_tables(conn))
            after_scope = existing if not named else (set(before_image) | named) & existing
            after_scope |= set(before_image)
            after_image = snapshot(conn, after_scope)
        changes = diff_snapshots(before_image, after_image)
        reports.append(
            {
                "revision": revision,
                "tables_named": sorted(named),
                "table_scope": "named" if named else "all_public_tables",
                "measurable": all(change.get("measurable") for change in changes),
                "rows_affected": rows_affected(changes),
                "tables": changes,
            }
        )
    return reports


def upgrade_snapshot(cfg: Config, engine: Engine) -> dict[str, object]:
    script = script_directory(cfg)
    head = single_head(script)
    if head == BASELINE_REVISION:
        raise UpgradeFailed(f"{FAILED}: current head is still {BASELINE_REVISION}")
    with engine.connect() as conn:
        require_baseline_shape(conn)
        before = capture(conn)
    backfills = step_to_head(cfg, engine, script, head)
    with engine.connect() as conn:
        after = capture(conn)
        if after["revision"] != head:
            raise UpgradeFailed(
                f"{FAILED}: database revision is {after['revision']}, head is {head}"
            )
    survival = compare(before, after)
    return {
        "ok": survival_ok(survival),
        "audited_sha": AUDITED_SHA,
        "baseline_revision": BASELINE_REVISION,
        "head_revision": head,
        "head_count": 1,
        "revision_before": before["revision"],
        "revision_after": after["revision"],
        "row_counts_before": before["row_counts"],
        "row_counts_after": after["row_counts"],
        "sampled_storage_keys": before["storage_keys"],
        "sampled_storage_keys_after": after["storage_keys"],
        "sampled_answer_texts": before["answer_texts"],
        "sampled_answer_texts_after": after["answer_texts"],
        "foreign_keys_before": before["foreign_keys"],
        "foreign_keys_missing": survival["foreign_keys_missing"],
        "survival": survival,
        "backfills": backfills,
        "measurement": (
            "Each revision whose upgrade() reaches INSERT, UPDATE, or DELETE is listed. "
            "rows_affected is the count of inserted, deleted, and primary-key-updated rows "
            "in the tables named by that SQL. A new column in the same revision counts as an "
            "update when the stored row image changes. Tables without a single-column primary "
            "key leave rows_affected null."
        ),
    }


def qualify(cfg: Config, engine: Engine) -> dict[str, object]:
    script = script_directory(cfg)
    single_head(script)
    revision_path(script, BASELINE_REVISION, single_head(script))
    with engine.connect() as conn:
        require_empty(conn)
    run_upgrade(cfg, BASELINE_REVISION)
    with engine.begin() as conn:
        apply_fixture(conn)
    report = upgrade_snapshot(cfg, engine)
    with engine.connect() as conn:
        before_keys = list(report["sampled_storage_keys"])
        before_answers = list(report["sampled_answer_texts"])
        before_counts = dict(report["row_counts_before"])
    run_downgrade(cfg, BASELINE_REVISION)
    with engine.connect() as conn:
        rolled_revision = current_revision(conn)
        rolled_keys = storage_keys(conn)
        rolled_answers = answer_texts(conn)
        rolled_counts = row_counts(conn)
    count_deltas = {
        table: {"before": before_counts[table], "after": rolled_counts.get(table)}
        for table in before_counts
        if rolled_counts.get(table) != before_counts[table]
    }
    rollback_ok = (
        rolled_revision == BASELINE_REVISION
        and rolled_keys == before_keys
        and rolled_answers == before_answers
        and not count_deltas
    )
    report["rollback"] = {
        "downgrade_to": BASELINE_REVISION,
        "revision_after_downgrade": rolled_revision,
        "storage_keys_preserved": rolled_keys == before_keys,
        "answer_texts_preserved": rolled_answers == before_answers,
        "row_counts_match": not count_deltas,
        "row_count_deltas": count_deltas,
        "ok": rollback_ok,
    }
    run_upgrade(cfg, "head")
    with engine.connect() as conn:
        final_revision = current_revision(conn)
        final_keys = storage_keys(conn)
        final_answers = answer_texts(conn)
    report["reupgrade"] = {
        "revision": final_revision,
        "storage_keys_preserved": final_keys == before_keys,
        "answer_texts_preserved": final_answers == before_answers,
        "ok": final_revision == report["head_revision"]
        and final_keys == before_keys
        and final_answers == before_answers,
    }
    report["ok"] = bool(report["ok"] and rollback_ok and report["reupgrade"]["ok"])
    report["kind"] = "audited_snapshot"
    return report


def fresh(cfg: Config, engine: Engine) -> dict[str, object]:
    script = script_directory(cfg)
    head = single_head(script)
    with engine.connect() as conn:
        require_empty(conn)
    run_upgrade(cfg, "head")
    with engine.connect() as conn:
        revision = current_revision(conn)
    if revision != head:
        raise UpgradeFailed(f"{FAILED}: fresh database revision is {revision}, head is {head}")
    return {
        "ok": True,
        "kind": "fresh_schema",
        "audited_sha": AUDITED_SHA,
        "baseline_revision": BASELINE_REVISION,
        "head_revision": head,
        "head_count": 1,
        "revision_after": revision,
        "upgrade_exit_code": 0,
    }


def upgrade_existing(cfg: Config, engine: Engine) -> dict[str, object]:
    report = upgrade_snapshot(cfg, engine)
    report["kind"] = "audited_snapshot"
    return report


def write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_local_env() -> None:
    if os.environ.get("TRUST_COPILOT_TESTING") == "1":
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(API_ROOT / ".env")
    load_dotenv(API_ROOT.parent.parent / ".env")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qualify the audited migration snapshot")
    parser.add_argument("command", choices=("qualify", "fresh", "upgrade"))
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    os.chdir(API_ROOT)
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    load_local_env()
    if not os.environ.get("DATABASE_URL"):
        print(f"{FAILED}: DATABASE_URL is not set", file=sys.stderr)
        return 1
    cfg = alembic_config()
    engine = connect(os.environ["DATABASE_URL"])
    commands = {"qualify": qualify, "fresh": fresh, "upgrade": upgrade_existing}
    try:
        payload = commands[args.command](cfg, engine)
    except SnapshotRefused as exc:
        write_report(
            args.report,
            {"ok": False, "kind": args.command, "error": redact(str(exc)), "stamped": False},
        )
        print(redact(str(exc)), file=sys.stderr)
        return 2
    except UpgradeFailed as exc:
        write_report(
            args.report,
            {"ok": False, "kind": args.command, "error": redact(str(exc)), "stamped": False},
        )
        print(redact(str(exc)), file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    payload["upgrade_exit_code"] = 0 if payload.get("ok") else 1
    write_report(args.report, payload)
    if not payload.get("ok"):
        print(f"{FAILED}: survival check failed", file=sys.stderr)
        return 1
    print(
        f"ok kind={payload['kind']} baseline={BASELINE_REVISION} "
        f"head={payload['head_revision']} backfills={len(payload.get('backfills', []))}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
