"""TC-25-005a: case-study publish claims are fenced by an owner token.

Runs on PostgreSQL. Placeholders are synthetic labels, not customers.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.core.database import SessionLocal
from app.main import app
from tests.conftest import TEST_HEADERS, TEST_ORIGIN
from tests.release.test_domain_case_studies import (
    _admin,
    _create,
    _grant_matrix,
    _publish,
    _stored_flags,
    _submit_and_approve,
)


@pytest.fixture
def admin_client(client):
    return _admin(client)


_TOUCHED = (
    "case_study_result_permissions",
    "case_study_organization_consents",
    "case_studies",
    "idempotency_keys",
)


def _counts() -> dict[str, int]:
    db = SessionLocal()
    try:
        return {
            name: int(db.execute(text(f"SELECT count(*) FROM {name}")).scalar() or 0)
            for name in _TOUCHED
        }
    finally:
        db.close()


def _delete_in(db, table: str, column: str, values: list) -> None:
    statement = text(f"DELETE FROM {table} WHERE {column} IN :values").bindparams(
        bindparam("values", expanding=True)
    )
    db.execute(statement, {"values": values})


@pytest.fixture
def tracked():
    """Record ids this test creates and put every touched table back."""
    box: dict[str, list] = {"studies": [], "keys": []}
    before = _counts()
    yield box
    db = SessionLocal()
    try:
        if box["studies"]:
            _delete_in(db, "case_study_result_permissions", "case_study_id", box["studies"])
            _delete_in(db, "case_study_organization_consents", "case_study_id", box["studies"])
            _delete_in(db, "case_studies", "id", box["studies"])
        if box["keys"]:
            _delete_in(db, "idempotency_keys", "idempotency_key", box["keys"])
        db.commit()
    finally:
        db.close()
    after = _counts()
    assert after == before, {"before": before, "after": after}
    print(f"TC25005A_COUNTS before={before} after={after}")


def _ready(client) -> dict:
    study = _create(client, title=f"Owner fence {uuid.uuid4().hex[:8]}")
    study = _grant_matrix(client, study)
    return _submit_and_approve(client, study)


def _storage_key(study: dict, client_key: str) -> str:
    return f"case-study:{study['workspace_id']}:{study['id']}:{client_key}"


def _owner_of(db, key: str):
    return db.execute(
        text("SELECT owner_token FROM idempotency_keys WHERE idempotency_key = :k"),
        {"k": key},
    ).scalar()


def _expire(db, key: str) -> None:
    db.execute(
        text("UPDATE idempotency_keys SET expires_at = :t WHERE idempotency_key = :k"),
        {"t": datetime.now(timezone.utc) - timedelta(seconds=5), "k": key},
    )
    db.commit()


def test_publish_normal_path_and_retry_are_idempotent(admin_client, tracked):
    from app.core import idempotency

    study = _ready(admin_client)
    tracked["studies"].append(study["id"])
    key = f"cs-ok-{uuid.uuid4().hex}"
    storage = _storage_key(study, key)
    tracked["keys"].append(storage)
    first = _publish(admin_client, study, headers={"Idempotency-Key": key})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "published"
    db = SessionLocal()
    try:
        assert _owner_of(db, storage)
        assert idempotency.get(db, storage)[0] == 200
        assert idempotency.get(db, storage)[1]["id"] == body["id"]
    finally:
        db.close()

    retried = _publish(admin_client, study, headers={"Idempotency-Key": key})
    assert retried.status_code == 200
    assert retried.json()["published_at"] == body["published_at"]
    assert retried.json()["revision"] == body["revision"]
    stored = _stored_flags(study["id"])
    assert stored["status"] == "published"
    assert stored["revision"] == body["revision"]


def test_stale_owner_set_and_release_leave_the_new_claim(admin_client, tracked):
    from app.core import idempotency
    from app.services import case_study_service as cs

    study = _ready(admin_client)
    tracked["studies"].append(study["id"])
    key = f"cs-stale-{uuid.uuid4().hex}"
    storage = _storage_key(study, key)
    tracked["keys"].append(storage)
    holder: dict = {}
    real_publish = cs.publish

    def reclaim_then_publish(*args, **kwargs):
        side = SessionLocal()
        try:
            holder["stale"] = _owner_of(side, storage)
            _expire(side, storage)
            holder["fresh"] = idempotency.claim(side, storage)
        finally:
            side.close()
        return real_publish(*args, **kwargs)

    with patch("app.api.routes.case_studies.cs.publish", side_effect=reclaim_then_publish):
        response = _publish(admin_client, study, headers={"Idempotency-Key": key})
    assert response.status_code == 200, response.text
    assert holder["stale"] and holder["fresh"] and holder["stale"] != holder["fresh"]

    db = SessionLocal()
    try:
        assert _owner_of(db, storage) == holder["fresh"]
        assert idempotency.get(db, storage) is None
        assert idempotency.release(db, storage, owner=holder["stale"]) is False
        assert idempotency.set(db, storage, 200, {"id": "stale"}, owner=holder["stale"]) is False
        assert _owner_of(db, storage) == holder["fresh"]
        assert idempotency.get(db, storage) is None
        stored = idempotency.set(
            db, storage, 200, {"id": study["id"], "kept": True}, owner=holder["fresh"]
        )
        assert stored is True
        assert idempotency.get(db, storage) == (200, {"id": study["id"], "kept": True})
    finally:
        db.close()
    assert _stored_flags(study["id"])["status"] == "published"


def test_stale_owner_release_on_unexpected_error_leaves_the_new_claim(admin_client, tracked):
    from app.core import idempotency

    study = _ready(admin_client)
    tracked["studies"].append(study["id"])
    key = f"cs-release-{uuid.uuid4().hex}"
    storage = _storage_key(study, key)
    tracked["keys"].append(storage)
    holder: dict = {}

    def reclaim_then_fail(*args, **kwargs):
        side = SessionLocal()
        try:
            holder["stale"] = _owner_of(side, storage)
            _expire(side, storage)
            holder["fresh"] = idempotency.claim(side, storage)
        finally:
            side.close()
        raise RuntimeError("synthetic late finisher")

    quiet = TestClient(
        app, base_url=TEST_ORIGIN, headers=TEST_HEADERS, raise_server_exceptions=False
    )
    _admin(quiet)
    with patch("app.api.routes.case_studies.cs.publish", side_effect=reclaim_then_fail):
        response = quiet.post(
            f"/api/case-studies/{study['id']}/publish",
            json={"expected_revision": study["revision"]},
            headers={"Idempotency-Key": key},
        )
    assert response.status_code == 500
    db = SessionLocal()
    try:
        assert holder["fresh"]
        assert _owner_of(db, storage) == holder["fresh"]
        assert idempotency.get(db, storage) is None
        assert idempotency.release(db, storage, owner=holder["stale"]) is False
        assert _owner_of(db, storage) == holder["fresh"]
    finally:
        db.close()
    assert _stored_flags(study["id"])["status"] != "published"
