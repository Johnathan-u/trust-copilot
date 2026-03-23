"""
Merge duplicate SOC 2 vs SOC2 framework rows in a local/dev database.

- Canonical framework: **SOC 2** (name with space), matching seed_dev_compliance_catalog.
- Relinks WorkspaceControl rows to FrameworkControls under the canonical framework.
- Remaps FKs that point at duplicate WorkspaceControl ids, then deletes duplicate FC/WC rows.
- Removes the orphan **SOC2** framework row when empty.

**Not** a production Alembic migration — run manually when needed:

  cd apps/api
  python -m scripts.merge_dev_duplicate_soc2_framework --dry-run
  python -m scripts.merge_dev_duplicate_soc2_framework --apply

Safety: refuses --apply unless TRUST_COPILOT_MERGE_SOC2=1 is set (or pass --i-know-what-im-doing for local scripts).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from dotenv import load_dotenv

load_dotenv(API_ROOT / ".env")

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Framework, FrameworkControl, WorkspaceControl


def _norm_fw(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def find_soc2_pair(db: Session) -> tuple[Framework, Framework] | None:
    """Return (canonical, duplicate) or None."""
    cands = [f for f in db.query(Framework).all() if _norm_fw(f.name) == "soc2"]
    if len(cands) < 2:
        return None
    canonical = next((f for f in cands if f.name.strip() == "SOC 2"), None)
    if not canonical:
        canonical = min(cands, key=lambda f: f.id)
    duplicate = next(f for f in cands if f.id != canonical.id)
    return canonical, duplicate


def _table_exists(db: Session, table: str) -> bool:
    r = db.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :t LIMIT 1"
        ),
        {"t": table},
    ).scalar()
    return r is not None


def repoint_workspace_control_id(db: Session, old_id: int, new_id: int) -> None:
    if old_id == new_id:
        return
    updates: list[tuple[str, str]] = [
        ("control_evidence_links", "control_id"),
        ("framework_control_mappings", "control_id"),
        ("control_evidence_mappings", "control_id"),
        ("gmail_control_suggestions", "control_id"),
        ("slack_control_suggestions", "control_id"),
    ]
    for table, col in updates:
        if not _table_exists(db, table):
            continue
        db.execute(text(f"UPDATE {table} SET {col} = :n WHERE {col} = :o"), {"n": new_id, "o": old_id})
    if _table_exists(db, "question_mapping_preferences"):
        db.execute(
            text("UPDATE question_mapping_preferences SET preferred_control_id = :n WHERE preferred_control_id = :o"),
            {"n": new_id, "o": old_id},
        )
    db.commit()


def remap_control_mapping_override_json(db: Session, old_wc: int, new_wc: int) -> None:
    if not _table_exists(db, "control_mapping_override"):
        return
    rows = db.execute(text("SELECT id, override_control_ids FROM control_mapping_override")).fetchall()
    for rid, raw in rows:
        if not isinstance(raw, list):
            continue
        if old_wc not in raw:
            continue
        new_list = [new_wc if x == old_wc else x for x in raw]
        db.execute(
            text("UPDATE control_mapping_override SET override_control_ids = CAST(:j AS json) WHERE id = :i"),
            {"j": json.dumps(new_list), "i": rid},
        )
    db.commit()


def remap_question_control_log_json(db: Session, old_wc: int, new_wc: int) -> None:
    if not _table_exists(db, "question_control_log"):
        return
    rows = db.execute(text("SELECT id, control_ids FROM question_control_log")).fetchall()
    for rid, raw in rows:
        if not isinstance(raw, list):
            continue
        if old_wc not in raw:
            continue
        new_list = [new_wc if x == old_wc else x for x in raw]
        db.execute(
            text("UPDATE question_control_log SET control_ids = CAST(:j AS json) WHERE id = :i"),
            {"j": json.dumps(new_list), "i": rid},
        )
    db.commit()


def remap_framework_control_ids_in_control_mappings(db: Session, mapping: dict[int, int]) -> None:
    if not mapping or not _table_exists(db, "control_mappings"):
        return
    for old_fc, new_fc in mapping.items():
        db.execute(
            text("UPDATE control_mappings SET source_control_id = :n WHERE source_control_id = :o"),
            {"n": new_fc, "o": old_fc},
        )
        db.execute(
            text("UPDATE control_mappings SET target_control_id = :n WHERE target_control_id = :o"),
            {"n": new_fc, "o": old_fc},
        )
    db.commit()


def merge_duplicate_workspace_controls(db: Session, keep_id: int, drop_id: int) -> None:
    repoint_workspace_control_id(db, drop_id, keep_id)
    remap_control_mapping_override_json(db, drop_id, keep_id)
    remap_question_control_log_json(db, drop_id, keep_id)
    dw = db.query(WorkspaceControl).filter(WorkspaceControl.id == drop_id).first()
    if dw:
        db.delete(dw)
        db.commit()


def diagnose(db: Session, canonical: Framework, duplicate: Framework) -> None:
    print(f"Canonical: id={canonical.id} name={canonical.name!r} version={canonical.version!r}")
    print(f"Duplicate: id={duplicate.id} name={duplicate.name!r} version={duplicate.version!r}")
    for label, fid in ("canonical", canonical.id), ("duplicate", duplicate.id):
        nfc = db.execute(
            text("SELECT COUNT(*) FROM framework_controls WHERE framework_id = :f"),
            {"f": fid},
        ).scalar()
        nwc = db.execute(
            text(
                """
                SELECT COUNT(*) FROM workspace_controls wc
                JOIN framework_controls fc ON fc.id = wc.framework_control_id
                WHERE fc.framework_id = :f
                """
            ),
            {"f": fid},
        ).scalar()
        print(f"  {label}: framework_controls={nfc}, workspace_controls (via FC)={nwc}")
    n_cm = db.execute(
        text(
            """
            SELECT COUNT(*) FROM control_mappings cm
            JOIN framework_controls fc ON fc.id = cm.source_control_id
            WHERE fc.framework_id = :f
            """
        ),
        {"f": duplicate.id},
    ).scalar()
    print(f"  control_mappings with source on duplicate framework: {n_cm}")


def run_merge(db: Session, apply: bool) -> None:
    pair = find_soc2_pair(db)
    if not pair:
        print("No duplicate SOC2-style frameworks found; nothing to do.")
        return
    canonical, duplicate = pair
    diagnose(db, canonical, duplicate)

    dup_fcs = (
        db.query(FrameworkControl)
        .filter(FrameworkControl.framework_id == duplicate.id)
        .order_by(FrameworkControl.id)
        .all()
    )
    fc_id_remap: dict[int, int] = {}

    for dfc in dup_fcs:
        cfc = (
            db.query(FrameworkControl)
            .filter(
                FrameworkControl.framework_id == canonical.id,
                FrameworkControl.control_key == dfc.control_key,
            )
            .first()
        )
        if cfc:
            fc_id_remap[dfc.id] = cfc.id
            d_wcs = (
                db.query(WorkspaceControl)
                .filter(WorkspaceControl.framework_control_id == dfc.id)
                .order_by(WorkspaceControl.id)
                .all()
            )
            for dw in d_wcs:
                kw = (
                    db.query(WorkspaceControl)
                    .filter(
                        WorkspaceControl.workspace_id == dw.workspace_id,
                        WorkspaceControl.framework_control_id == cfc.id,
                    )
                    .first()
                )
                if kw:
                    if apply:
                        print(f"  Merge WC workspace={dw.workspace_id}: drop wc={dw.id} -> keep wc={kw.id}")
                        merge_duplicate_workspace_controls(db, kw.id, dw.id)
                    else:
                        print(f"  [dry-run] Would merge WC workspace={dw.workspace_id}: drop wc={dw.id} -> keep wc={kw.id}")
                else:
                    if apply:
                        print(f"  Relink WC {dw.id} to canonical FC {cfc.id} ({cfc.control_key})")
                        dw.framework_control_id = cfc.id
                        db.commit()
                    else:
                        print(f"  [dry-run] Would relink WC {dw.id} to canonical FC {cfc.id} ({cfc.control_key})")
            if apply:
                remap_framework_control_ids_in_control_mappings(db, {dfc.id: cfc.id})
                db.delete(dfc)
                db.commit()
                print(f"  Deleted duplicate FC id={dfc.id} key={dfc.control_key}")
            else:
                print(f"  [dry-run] Would delete duplicate FC id={dfc.id} key={dfc.control_key}")
        else:
            if apply:
                print(f"  Move FC id={dfc.id} key={dfc.control_key} to canonical framework {canonical.id}")
                dfc.framework_id = canonical.id
                db.commit()
            else:
                print(f"  [dry-run] Would move FC id={dfc.id} key={dfc.control_key} to canonical framework")

    if apply:
        remap_framework_control_ids_in_control_mappings(db, fc_id_remap)
        db.query(Framework).filter(Framework.id == duplicate.id).delete()
        db.commit()
        print(f"Deleted duplicate framework id={duplicate.id}")
    else:
        print(f"[dry-run] Would delete duplicate framework id={duplicate.id}")


def main() -> None:
    p = argparse.ArgumentParser(description="Merge SOC2 duplicate framework into SOC 2 (dev only).")
    p.add_argument("--dry-run", action="store_true", help="Print actions only (default if neither flag)")
    p.add_argument("--apply", action="store_true", help="Perform merge")
    p.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help="Allow --apply without TRUST_COPILOT_MERGE_SOC2=1 (local dev only)",
    )
    args = p.parse_args()
    if args.apply and not args.i_know_what_im_doing:
        if os.environ.get("TRUST_COPILOT_MERGE_SOC2") != "1":
            print("Refusing --apply: set TRUST_COPILOT_MERGE_SOC2=1 or pass --i-know-what-im-doing")
            sys.exit(1)
    apply = bool(args.apply)
    if not apply and not args.dry_run:
        args.dry_run = True
    db = SessionLocal()
    try:
        run_merge(db, apply=apply)
    finally:
        db.close()


if __name__ == "__main__":
    main()
