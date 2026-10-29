"""BUG-019: trust-article slugs are unique per workspace, matching /trust/{workspace-slug}."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, text

from app.core.database import SessionLocal, engine
from app.models.trust_article import TrustArticle
from app.models.workspace import Workspace
from app.models.workspace_control import WorkspaceControl
from app.services import trust_center_publish_service as tcp


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _add_workspace(db, label: str) -> Workspace:
    next_id = (db.query(func.max(Workspace.id)).scalar() or 0) + 1
    ws = Workspace(
        id=next_id,
        name=f"Synthetic {label}",
        slug=f"bug019-{label}-{_suffix()}",
    )
    db.add(ws)
    db.flush()
    db.execute(
        text(
            "SELECT setval(pg_get_serial_sequence('workspaces', 'id'), (SELECT MAX(id) FROM workspaces))"
        )
    )
    return ws


def test_two_workspaces_auto_publish_same_control(client, db_session):
    """Both workspaces publish control-cov, and each public trust URL resolves its own article."""
    ws_a = _add_workspace(db_session, "alpha")
    ws_b = _add_workspace(db_session, "beta")
    db_session.add_all(
        [
            WorkspaceControl(workspace_id=ws_a.id, custom_name="cov", status="implemented"),
            WorkspaceControl(workspace_id=ws_b.id, custom_name="cov", status="implemented"),
        ]
    )
    db_session.flush()

    first = tcp.auto_publish_approved_controls(db_session, ws_a.id)
    second = tcp.auto_publish_approved_controls(db_session, ws_b.id)
    db_session.commit()

    ids = (ws_a.id, ws_b.id)
    try:
        assert first["articles_created"] == 1
        assert second["articles_created"] == 1
        published_a = tcp.get_published_controls(db_session, ws_a.id)
        published_b = tcp.get_published_controls(db_session, ws_b.id)
        assert [row["slug"] for row in published_a] == ["control-cov"]
        assert [row["slug"] for row in published_b] == ["control-cov"]
        assert published_a[0]["id"] != published_b[0]["id"]

        for ws, published in ((ws_a, published_a), (ws_b, published_b)):
            resolved = client.get(f"/api/workspaces/by-slug/{ws.slug}")
            assert resolved.status_code == 200, resolved.text
            body = resolved.json()
            assert body["id"] == ws.id
            assert body["slug"] == ws.slug
            listed = client.get(f"/api/trust-articles?workspace_id={ws.id}&published_only=true")
            assert listed.status_code == 200, listed.text
            match = [item for item in listed.json() if item["slug"] == "control-cov"]
            assert len(match) == 1
            assert match[0]["id"] == published[0]["id"]
            article = client.get(f"/api/trust-articles/{match[0]['id']}?workspace_id={ws.id}")
            assert article.status_code == 200, article.text
            assert article.json()["slug"] == "control-cov"
            assert article.json()["workspace_id"] == ws.id
    finally:
        db_session.query(TrustArticle).filter(TrustArticle.workspace_id.in_(ids)).delete(
            synchronize_session=False
        )
        db_session.query(WorkspaceControl).filter(WorkspaceControl.workspace_id.in_(ids)).delete(
            synchronize_session=False
        )
        db_session.query(Workspace).filter(Workspace.id.in_(ids)).delete(synchronize_session=False)
        db_session.commit()


def test_slug_migration_roundtrip_refuses_duplicate_downgrade(_ensure_test_data):
    """Upgrade/downgrade restores the indexes, and downgrade fails while a slug is shared."""
    if not _ensure_test_data:
        pytest.skip("Postgres test DB unavailable")

    api_dir = Path(__file__).resolve().parents[2]
    mig_path = api_dir / "alembic" / "versions" / "bug019_trust_article_slug_workspace.py"
    spec = importlib.util.spec_from_file_location("bug019_mig", mig_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    token = _suffix()

    def alembic(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=api_dir,
            env=env,
            capture_output=True,
            text=True,
        )

    def alembic_ok(*args: str) -> None:
        result = alembic(*args)
        assert result.returncode == 0, result.stderr[-2000:]

    def constraint_names() -> set[str]:
        engine.dispose()
        insp = inspect(engine)
        names = {item["name"] for item in insp.get_unique_constraints("trust_articles")}
        names.update(item["name"] for item in insp.get_indexes("trust_articles"))
        return names

    session = SessionLocal()
    ws_ids: list[int] = []
    try:
        assert mod._WORKSPACE_UNIQUE in constraint_names()
        assert mod._GLOBAL_INDEX not in constraint_names()

        for label in ("downgrade-a", "downgrade-b"):
            ws = _add_workspace(session, label)
            ws_ids.append(ws.id)
            session.add(
                TrustArticle(
                    workspace_id=ws.id,
                    slug=f"shared-{token}",
                    title="Synthetic article",
                    content="Synthetic",
                    published=1,
                )
            )
        session.commit()

        blocked = alembic("downgrade", mod.down_revision)
        assert blocked.returncode != 0
        assert "does not delete rows" in blocked.stderr

        session.query(TrustArticle).filter(TrustArticle.slug == f"shared-{token}").delete(
            synchronize_session=False
        )
        session.commit()

        alembic_ok("downgrade", mod.down_revision)
        names = constraint_names()
        assert mod._GLOBAL_INDEX in names
        assert mod._WORKSPACE_UNIQUE not in names
    finally:
        alembic_ok("upgrade", "head")
        if ws_ids:
            session.query(TrustArticle).filter(TrustArticle.workspace_id.in_(ws_ids)).delete(
                synchronize_session=False
            )
            session.query(Workspace).filter(Workspace.id.in_(ws_ids)).delete(
                synchronize_session=False
            )
            session.commit()
        session.close()
        assert mod._WORKSPACE_UNIQUE in constraint_names()
        assert mod._GLOBAL_INDEX not in constraint_names()
