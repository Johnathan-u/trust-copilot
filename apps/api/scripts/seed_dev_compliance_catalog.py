"""
Idempotently seed multi-framework FrameworkControl rows and link WorkspaceControl rows
for the demo workspace (default workspace_id=1).

Run from apps/api:
  python -m scripts.seed_dev_compliance_catalog
  python -m scripts.seed_dev_compliance_catalog --workspace-id 1

Also invoked from scripts.seed_demo_workspace after questionnaire/documents seed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from dotenv import load_dotenv

load_dotenv(API_ROOT / ".env")

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Framework, FrameworkControl, Workspace, WorkspaceControl

from scripts.dev_compliance_catalog import DEV_COMPLIANCE_CATALOG


def _normalize_framework_key(name: str) -> str:
    """Match SOC2 / SOC 2 / soc-2 style names to one canonical key."""
    return "".join(c for c in (name or "").lower() if c.isalnum())


def _ensure_framework(db: Session, name: str, version: str | None) -> Framework:
    """Resolve or create Framework; avoid duplicate SOC2 vs SOC 2 rows in dev."""
    want_key = _normalize_framework_key(name)
    candidates = db.query(Framework).order_by(Framework.id).all()
    for fw in candidates:
        if _normalize_framework_key(fw.name) == want_key:
            if version and (fw.version is None or fw.version == ""):
                fw.version = version
                db.commit()
                db.refresh(fw)
            return fw
    fw = Framework(name=name.strip(), version=version)
    db.add(fw)
    db.commit()
    db.refresh(fw)
    print(f"  Created framework: {name} (id={fw.id})")
    return fw


def seed_dev_compliance_catalog(db: Session, workspace_id: int = 1) -> tuple[int, int]:
    """
    Insert missing FrameworkControl rows from DEV_COMPLIANCE_CATALOG and ensure each
    has a WorkspaceControl link for the given workspace.

    Returns (framework_controls_touched, workspace_controls_created).
    """
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise RuntimeError(f"Workspace id={workspace_id} not found. Create workspace first.")

    fc_seen = 0
    wc_created = 0

    for row in DEV_COMPLIANCE_CATALOG:
        fw = _ensure_framework(
            db,
            row["framework_name"],
            row.get("framework_version"),
        )
        key = row["control_key"]
        fc = (
            db.query(FrameworkControl)
            .filter(
                FrameworkControl.framework_id == fw.id,
                FrameworkControl.control_key == key,
            )
            .first()
        )
        if not fc:
            fc = FrameworkControl(
                framework_id=fw.id,
                control_key=key,
                title=row.get("title"),
                category=row.get("category"),
                description=row.get("description"),
                criticality=row.get("criticality") or "medium",
            )
            db.add(fc)
            db.commit()
            db.refresh(fc)
            print(f"  + FC {fw.name}/{key} (id={fc.id})")
        else:
            # Enrich sparse legacy rows so keyword matching works in dev.
            desc = row.get("description") or ""
            if desc and (not fc.description or len((fc.description or "").strip()) < 40):
                fc.title = row.get("title") or fc.title
                fc.category = row.get("category") or fc.category
                fc.description = desc
                db.commit()
                db.refresh(fc)
                print(f"  ~ FC {fw.name}/{key} enriched (id={fc.id})")
        fc_seen += 1

        wc = (
            db.query(WorkspaceControl)
            .filter(
                WorkspaceControl.workspace_id == workspace_id,
                WorkspaceControl.framework_control_id == fc.id,
            )
            .first()
        )
        if not wc:
            db.add(
                WorkspaceControl(
                    workspace_id=workspace_id,
                    framework_control_id=fc.id,
                    status="not_implemented",
                )
            )
            db.commit()
            wc_created += 1

    return fc_seen, wc_created


def main() -> None:
    p = argparse.ArgumentParser(description="Seed dev compliance catalog + workspace links.")
    p.add_argument("--workspace-id", type=int, default=1, help="Target workspace (default: 1)")
    args = p.parse_args()
    db = SessionLocal()
    try:
        print(f"Seeding dev compliance catalog for workspace_id={args.workspace_id} ...")
        fc_n, wc_n = seed_dev_compliance_catalog(db, workspace_id=args.workspace_id)
        print(f"Done. Catalog rows processed: {fc_n}, new workspace_controls: {wc_n}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
