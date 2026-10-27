"""TC-25-005 consent-backed case study publication.

Runs against the test PostgreSQL database. Placeholders are synthetic labels,
not customers, quotes, or results.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.routes.case_studies import PRESERVED_FIELDS
from app.core.database import SessionLocal, engine
from app.models.case_study import CaseStudy, CaseStudyResultPermission
from app.services import case_study_service as cs

REPO_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = Path(__file__).resolve().parents[2]
CONSUMER_RUNNER = Path(__file__).resolve().parent / "run_case_study_consumer.mjs"
MIGRATION_PATH = REPO_ROOT / "apps/api/alembic/versions/tc25005_case_study_consent.py"
PARENT_REVISION = "tc11001_model_outcome_codes"

ORG = "SYNTHETIC-ORG-PLACEHOLDER"
ORG_2 = "SYNTHETIC-ORG-PLACEHOLDER-2"
QUOTE = "SYNTHETIC-QUOTE-PLACEHOLDER"
RESULT = "SYNTHETIC-RESULT-PLACEHOLDER"
METRIC = "synthetic_metric_placeholder"
METRIC_VALUE = "SYNTHETIC-METRIC-PLACEHOLDER"
CONSENT_REF = "SYNTHETIC-CONSENT-REF"
AGREE_FIELDS = (
    "id",
    "status",
    "schema_version",
    "synthetic",
    "data_basis",
    "customer_claim",
    "publication_authorized",
    "review_status",
    "revision",
    "published_at",
    "display_label",
)


def _login(client, email: str, password: str):
    # Login allows 10 attempts per minute. This module logs in more often than that
    # while it walks the publish workflow, including inside one round-trip test.
    from app.core import rate_limit

    rate_limit._store.clear()
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.status_code
    return client


def _admin(client):
    return _login(client, "admin@trust.local", "a")


def _reviewer(client):
    return _login(client, "reviewer@trust.local", "r")


def _editor(client):
    return _login(client, "editor@trust.local", "e")


def _create(client, **overrides) -> dict:
    body = {
        "title": "Placeholder draft",
        "company_name": ORG,
        "quote": QUOTE,
        "results": RESULT,
        "metrics": {METRIC: METRIC_VALUE},
        "synthetic": False,
    }
    body.update(overrides)
    response = client.post("/api/case-studies", json=body)
    assert response.status_code == 200, response.status_code
    return response.json()


def _grant_matrix(client, study: dict, *, skip: tuple | None = None) -> dict:
    """Record consent and a permission for every quoted org × result, minus skip pairs."""
    skipped = set(skip or ())
    for org in study["quoted_organizations"]:
        response = client.post(
            f"/api/case-studies/{study['id']}/consents",
            json={
                "organization_name": org,
                "consent_reference": CONSENT_REF,
                "expected_revision": study["revision"],
            },
        )
        assert response.status_code == 200, response.status_code
        study = response.json()
        consent = next(
            item
            for item in study["consents"]
            if item["organization_name"] == org and item["active"]
        )
        for key in study["quoted_results"]:
            if (org, key) in skipped:
                continue
            response = client.post(
                f"/api/case-studies/{study['id']}/result-permissions",
                json={
                    "consent_id": consent["id"],
                    "result_key": key,
                    "expected_revision": study["revision"],
                },
            )
            assert response.status_code == 200, response.status_code
            study = response.json()
    return study


def _submit_and_approve(client, study: dict) -> dict:
    _admin(client)
    response = client.post(
        f"/api/case-studies/{study['id']}/submit-review",
        json={"expected_revision": study["revision"]},
    )
    assert response.status_code == 200, response.status_code
    study = response.json()
    _reviewer(client)
    response = client.post(
        f"/api/case-studies/{study['id']}/review",
        json={"decision": "approve", "expected_revision": study["revision"]},
    )
    assert response.status_code == 200, response.status_code
    study = response.json()
    _admin(client)
    return study


def _publish(client, study: dict, **kwargs):
    _admin(client)
    return client.post(
        f"/api/case-studies/{study['id']}/publish",
        json={"expected_revision": study["revision"]},
        **kwargs,
    )


def _stored_flags(case_id: int) -> dict:
    engine.dispose()
    db = SessionLocal()
    try:
        row = db.query(CaseStudy).filter(CaseStudy.id == case_id).one()
        return {
            "status": row.status,
            "customer_claim": bool(row.customer_claim),
            "synthetic": bool(row.synthetic),
            "data_basis": row.data_basis,
            "publication_authorized": bool(row.publication_authorized),
            "revision": int(row.revision),
            "review_status": row.review_status,
            "published_at": row.published_at,
            "schema_version": row.schema_version,
        }
    finally:
        db.close()


def _row_snapshot(case_id: int) -> dict:
    engine.dispose()
    db = SessionLocal()
    try:
        row = db.query(CaseStudy).filter(CaseStudy.id == case_id).one()
        return {
            "status": row.status,
            "customer_claim": bool(row.customer_claim),
            "synthetic": bool(row.synthetic),
            "data_basis": row.data_basis,
            "publication_authorized": bool(row.publication_authorized),
            "revision": int(row.revision),
            "review_status": row.review_status,
            "published_at": row.published_at,
            "quote": row.quote,
            "title": row.title,
            "company_name": row.company_name,
            "updated_at": row.updated_at,
        }
    finally:
        db.close()


def _audit_events(caplog) -> list[dict]:
    events = []
    for record in caplog.records:
        if record.name != "trustcopilot.audit":
            continue
        message = record.getMessage()
        payload = message.split("audit ", 1)[1]
        events.append(json.loads(payload))
    return events


def _times_match(api_value, db_value) -> bool:
    if api_value is None or db_value is None:
        return api_value is None and db_value is None
    parsed = datetime.fromisoformat(api_value)
    if parsed.tzinfo is None:
        return False
    if isinstance(db_value, datetime):
        return parsed == db_value
    return parsed == datetime.fromisoformat(str(db_value))


def _consumer_agrees(api_body: dict, persisted: dict) -> dict:
    completed = subprocess.run(
        ["node", str(CONSUMER_RUNNER)],
        input=json.dumps({"api": api_body, "persisted": persisted}),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _projection(body: dict) -> dict:
    return {key: body[key] for key in AGREE_FIELDS}


@pytest.fixture
def admin_client(client):
    return _admin(client)


def test_ac1_template_is_not_a_customer_claim(admin_client):
    response = admin_client.get("/api/case-studies/template")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "case-study.v2"
    assert body["data_basis"] == "blank_template"
    assert body["customer_claim"] is False
    assert body["synthetic"] is False
    assert body["metrics_are_field_names_not_results"] is True
    assert len(body["sections"]) >= 5
    encoded = json.dumps(body)
    for banned in ("Acme", "Globex", "StartupCo", "TestCo"):
        assert banned not in encoded
    assert "hours_saved" in body["suggested_metrics"]
    assert all(isinstance(name, str) for name in body["suggested_metrics"])


def test_ac1_publish_requires_consent_for_every_quoted_org_and_result(admin_client):
    study = _create(admin_client)
    assert study["customer_claim"] is False
    assert study["status"] == "draft"
    assert "quote" in study["quoted_results"]
    assert f"metric:{METRIC}" in study["quoted_results"]
    assert ORG in study["quoted_organizations"]

    blocked = admin_client.patch(
        f"/api/case-studies/{study['id']}",
        json={"status": "published", "expected_revision": study["revision"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "publish_requires_workflow"
    assert blocked.json()["detail"]["schema_version"] == "api-error.v1"

    study = _submit_and_approve(admin_client, study)
    denied = _publish(admin_client, study)
    assert denied.status_code == 409
    detail = denied.json()["detail"]
    assert detail["code"] == "consent_incomplete"
    assert detail["retryable"] is False
    codes = {item["code"] for item in detail["field_errors"]}
    assert "organization_consent_missing" in codes
    assert "result_permission_missing" in codes
    stored = _stored_flags(study["id"])
    assert stored["status"] != "published"
    assert stored["customer_claim"] is False
    assert stored["published_at"] is None

    study = admin_client.get(f"/api/case-studies/{study['id']}").json()
    study = _grant_matrix(admin_client, study)
    published = _publish(admin_client, study)
    assert published.status_code == 200, published.status_code
    body = published.json()
    assert body["status"] == "published"
    assert body["customer_claim"] is True
    assert body["data_basis"] == "consented_customer"
    assert body["synthetic"] is False
    assert body["display_label"] == "Consented publication"
    assert body["publication_authorized"] is True
    for field in PRESERVED_FIELDS:
        assert field in body
    stored = _stored_flags(study["id"])
    assert stored["customer_claim"] is True
    assert stored["status"] == "published"
    assert stored["data_basis"] == "consented_customer"
    assert _times_match(body["published_at"], stored["published_at"])


def test_ac1_synthetic_stays_marked_and_is_not_a_customer_claim(admin_client):
    study = _create(admin_client, synthetic=True, title="Synthetic placeholder draft")
    assert study["synthetic"] is True
    assert study["data_basis"] == "synthetic_example"
    assert study["customer_claim"] is False
    assert study["display_label"] == "Synthetic example. Not a customer claim."
    study = _grant_matrix(admin_client, study)
    study = _submit_and_approve(admin_client, study)
    published = _publish(admin_client, study)
    assert published.status_code == 200, published.status_code
    body = published.json()
    assert body["status"] == "published"
    assert body["synthetic"] is True
    assert body["customer_claim"] is False
    assert body["data_basis"] == "synthetic_example"
    assert body["display_label"] == "Synthetic example. Not a customer claim."
    stored = _stored_flags(study["id"])
    assert stored["customer_claim"] is False
    assert stored["synthetic"] is True
    assert stored["data_basis"] == "synthetic_example"

    unlabeled = _create(
        admin_client,
        synthetic=True,
        title="Synthetic blank draft",
        company_name=None,
        quote=None,
        results=None,
        metrics=None,
    )
    assert unlabeled["quoted_organizations"] == []
    assert unlabeled["quoted_results"] == []
    unlabeled = _submit_and_approve(admin_client, unlabeled)
    published_blank = _publish(admin_client, unlabeled)
    assert published_blank.status_code == 200, published_blank.status_code
    blank = published_blank.json()
    assert blank["customer_claim"] is False
    assert blank["data_basis"] == "synthetic_example"
    assert blank["display_label"] == "Synthetic example. Not a customer claim."


def test_ac1_tampered_row_cannot_appear_as_a_customer_claim(admin_client):
    study = _create(admin_client, title="Tamper placeholder")
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                UPDATE case_studies
                SET status = 'published',
                    customer_claim = TRUE,
                    publication_authorized = TRUE,
                    review_status = 'approved',
                    data_basis = 'consented_customer',
                    published_at = NOW()
                WHERE id = :id
                """
            ),
            {"id": study["id"]},
        )
        db.commit()
    finally:
        db.close()

    before = _row_snapshot(study["id"])
    response = admin_client.get(f"/api/case-studies/{study['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["customer_claim"] is False
    assert body["data_basis"] != "consented_customer"
    assert body["publication_authorized"] is False
    assert body["status"] == "published"
    assert body["display_label"] == "Not a customer claim."
    listed = admin_client.get("/api/case-studies")
    assert listed.status_code == 200
    listed_row = next(item for item in listed.json()["case_studies"] if item["id"] == study["id"])
    assert listed_row["customer_claim"] is False
    assert listed_row["data_basis"] != "consented_customer"
    after = _row_snapshot(study["id"])
    assert after == before
    assert after["customer_claim"] is True
    assert after["status"] == "published"


def test_ac1_sources_do_not_seed_a_customer_claim():
    paths = [
        REPO_ROOT / "apps/api/app/services/case_study_service.py",
        REPO_ROOT / "apps/api/app/api/routes/case_studies.py",
        REPO_ROOT / "apps/api/app/models/case_study.py",
        MIGRATION_PATH,
        REPO_ROOT / "apps/web/lib/caseStudyConsumer.ts",
        REPO_ROOT / "apps/web/app/dashboard/case-studies/page.tsx",
        REPO_ROOT / "apps/api/tests/test_case_studies.py",
    ]
    banned = ("Acme", "Globex", "StartupCo", "TestCo", "Initech")
    for path in paths:
        text_value = path.read_text()
        for name in banned:
            assert name not in text_value, path.name
    service = (REPO_ROOT / "apps/api/app/services/case_study_service.py").read_text()
    assert "def seed" not in service
    migration = MIGRATION_PATH.read_text()
    assert 'revision = "tc25005_case_study_consent"' in migration
    assert f'down_revision = "{PARENT_REVISION}"' in migration
    assert "INSERT INTO case_studies" not in migration
    assert "DELETE FROM case_studies" not in migration
    assert "TRUNCATE case_studies" not in migration
    assert "NOT IN" not in migration
    assert "from app" not in migration
    assert "import app" not in migration
    assert "case_study_consent_archive" in migration
    assert "case_study_result_permission_archive" in migration
    assert "case_study_review_archive" in migration
    page = (REPO_ROOT / "apps/web/app/dashboard/case-studies/page.tsx").read_text()
    assert "parseCaseStudyResponse" in page
    assert "caseStudyConsumer" in page
    assert "display_label" in page


def test_ac2_negative_current_permissions_and_cross_workspace(client):
    anonymous = client.get("/api/case-studies")
    assert anonymous.status_code == 401

    _editor(client)
    editor_create = client.post("/api/case-studies", json={"title": "Editor placeholder"})
    assert editor_create.status_code == 403

    _admin(client)
    study = _create(client, title="Permission placeholder", quote=QUOTE, results=None, metrics=None)
    study = _grant_matrix(client, study)
    study = _submit_and_approve(client, study)

    _editor(client)
    assert (
        client.post(
            f"/api/case-studies/{study['id']}/publish",
            json={"expected_revision": study["revision"]},
        ).status_code
        == 403
    )
    _reviewer(client)
    assert (
        client.post(
            f"/api/case-studies/{study['id']}/publish",
            json={"expected_revision": study["revision"]},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/case-studies/{study['id']}/consents",
            json={
                "organization_name": ORG,
                "consent_reference": CONSENT_REF,
                "expected_revision": study["revision"],
            },
        ).status_code
        == 403
    )

    _admin(client)
    too_early = _create(
        client, title="Review required placeholder", quote=None, results=None, metrics=None
    )
    early = client.post(
        f"/api/case-studies/{too_early['id']}/publish",
        json={"expected_revision": too_early["revision"]},
    )
    assert early.status_code == 409
    assert early.json()["detail"]["code"] == "review_required"

    db = SessionLocal()
    try:
        other = cs.create(db, 2, "Other workspace placeholder")
        db.commit()
        other_id = other["id"]
    finally:
        db.close()
    missing = client.get(f"/api/case-studies/{other_id}")
    assert missing.status_code == 404
    listed = client.get("/api/case-studies")
    assert all(item["id"] != other_id for item in listed.json()["case_studies"])
    assert client.delete(f"/api/case-studies/{other_id}").status_code == 404


def test_ac2_partial_failure_does_not_publish(admin_client):
    study = _create(
        admin_client,
        title="Partial placeholder",
        quoted_organizations=[ORG_2],
    )
    assert set(study["quoted_organizations"]) == {ORG, ORG_2}
    study = _grant_matrix(
        admin_client,
        study,
        skip={(ORG_2, f"metric:{METRIC}")},
    )
    study = _submit_and_approve(admin_client, study)
    key = "partial-placeholder-key"
    denied = _publish(admin_client, study, headers={"Idempotency-Key": key})
    assert denied.status_code == 409
    errors = denied.json()["detail"]["field_errors"]
    assert any(
        item["code"] == "result_permission_missing"
        and item["field"] == f"metric:{METRIC}"
        and item["organization_name"] == ORG_2
        for item in errors
    )
    assert all(item["code"] != "organization_consent_missing" for item in errors)
    stored = _stored_flags(study["id"])
    assert stored["status"] == "in_review"
    assert stored["customer_claim"] is False
    assert stored["published_at"] is None

    retried = _publish(admin_client, study, headers={"Idempotency-Key": key})
    assert retried.status_code == 409
    assert retried.json()["detail"]["code"] == "consent_incomplete"
    assert _stored_flags(study["id"])["status"] == "in_review"

    unrelated = admin_client.post(
        f"/api/case-studies/{study['id']}/result-permissions",
        json={"consent_id": 999999, "result_key": "quote", "expected_revision": study["revision"]},
    )
    assert unrelated.status_code == 422
    assert unrelated.json()["detail"]["code"] == "foreign_reference"
    db = SessionLocal()
    try:
        count = (
            db.query(CaseStudyResultPermission)
            .filter(CaseStudyResultPermission.case_study_id == study["id"])
            .count()
        )
    finally:
        db.close()
    granted = sum(1 for item in study["result_permissions"] if item["active"])
    assert count == granted


def test_ac2_foreign_reference_checks(admin_client):
    first = _create(admin_client, title="Foreign ref A", quote=QUOTE, results=None, metrics=None)
    second = _create(admin_client, title="Foreign ref B", quote=QUOTE, results=None, metrics=None)
    consented = _grant_matrix(admin_client, first)
    consent_id = next(item["id"] for item in consented["consents"] if item["active"])
    crossed = admin_client.post(
        f"/api/case-studies/{second['id']}/result-permissions",
        json={
            "consent_id": consent_id,
            "result_key": "quote",
            "expected_revision": second["revision"],
        },
    )
    assert crossed.status_code == 422
    assert crossed.json()["detail"]["code"] == "foreign_reference"

    unknown_org = admin_client.post(
        f"/api/case-studies/{first['id']}/consents",
        json={
            "organization_name": "SYNTHETIC-ORG-NOT-ON-DRAFT",
            "consent_reference": CONSENT_REF,
            "expected_revision": first["revision"],
        },
    )
    assert unknown_org.status_code == 422
    assert unknown_org.json()["detail"]["code"] == "organization_not_quoted"

    bad_result = admin_client.post(
        f"/api/case-studies/{first['id']}/result-permissions",
        json={
            "consent_id": consent_id,
            "result_key": "metric:not_a_quoted_result",
            "expected_revision": first["revision"],
        },
    )
    assert bad_result.status_code == 422
    assert bad_result.json()["detail"]["code"] == "result_not_quoted"

    db = SessionLocal()
    try:
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    """
                    INSERT INTO case_study_organization_consents
                        (workspace_id, case_study_id, organization_name, consent_granted, granted_revision)
                    VALUES (1, 999999, :org, TRUE, 1)
                    """
                ),
                {"org": ORG},
            )
            db.commit()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    """
                    INSERT INTO case_study_organization_consents
                        (workspace_id, case_study_id, organization_name, consent_granted, granted_revision)
                    VALUES (2, :case_id, :org, TRUE, 1)
                    """
                ),
                {"case_id": first["id"], "org": ORG},
            )
            db.commit()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    """
                    INSERT INTO case_study_result_permissions
                        (workspace_id, case_study_id, consent_id, result_key, permitted, granted_revision)
                    VALUES (1, :case_id, :consent_id, 'quote', TRUE, 1)
                    """
                ),
                {"case_id": second["id"], "consent_id": consent_id},
            )
            db.commit()
        db.rollback()
        permission_count = (
            db.query(CaseStudyResultPermission)
            .filter(CaseStudyResultPermission.case_study_id == second["id"])
            .count()
        )
        assert permission_count == 0
    finally:
        db.rollback()
        db.close()


def test_ac3_schema_consumer_and_persisted_outcome_agree_across_retry(admin_client):
    study = _create(admin_client, title="Agreement placeholder", results=None, metrics=None)
    study = _grant_matrix(admin_client, study)
    study = _submit_and_approve(admin_client, study)
    key = "agreement-placeholder-key"
    first = _publish(admin_client, study, headers={"Idempotency-Key": key})
    assert first.status_code == 200, first.status_code
    body = first.json()
    assert body["schema_version"] == "case-study.v2"
    for field in PRESERVED_FIELDS:
        assert field in body

    openapi = admin_client.get("/openapi.json")
    assert openapi.status_code == 200
    schema = openapi.json()["components"]["schemas"]["CaseStudyResponse"]["properties"]
    for field in PRESERVED_FIELDS:
        assert field in schema
    for field in ("schema_version", "customer_claim", "synthetic", "data_basis", "display_label"):
        assert field in schema
    list_schema = openapi.json()["components"]["schemas"]["CaseStudyListResponse"]["properties"]
    assert "case_studies" in list_schema

    stored = _stored_flags(study["id"])
    assert stored["status"] == body["status"] == "published"
    assert stored["customer_claim"] is True
    assert stored["data_basis"] == body["data_basis"]
    assert stored["revision"] == body["revision"]
    assert stored["schema_version"] == body["schema_version"]
    assert _times_match(body["published_at"], stored["published_at"])

    engine.dispose()
    reread = admin_client.get(f"/api/case-studies/{study['id']}")
    assert reread.status_code == 200
    fresh = reread.json()
    agreement = _consumer_agrees(body, _projection(fresh))
    assert agreement["agrees"] is True, agreement["mismatches"]
    assert agreement["view"]["customer_claim"] is True
    assert agreement["view"]["display_label"] == body["display_label"]

    retried = _publish(admin_client, fresh, headers={"Idempotency-Key": key})
    assert retried.status_code == 200
    assert retried.json()["published_at"] == body["published_at"]
    assert retried.json()["id"] == body["id"]
    again = _consumer_agrees(retried.json(), _projection(fresh))
    assert again["agrees"] is True, again["mismatches"]

    natural = _publish(admin_client, fresh)
    assert natural.status_code == 200
    assert natural.json()["published_at"] == body["published_at"]
    assert natural.json()["customer_claim"] is True
    stored_after = _stored_flags(study["id"])
    assert stored_after["revision"] == stored["revision"]
    assert _times_match(body["published_at"], stored_after["published_at"])

    page = (REPO_ROOT / "apps/web/app/dashboard/case-studies/page.tsx").read_text()
    consumer = (REPO_ROOT / "apps/web/lib/caseStudyConsumer.ts").read_text()
    assert "parseCaseStudyResponse" in page
    assert "displayLabel" in consumer
    assert "Not a customer claim." in consumer


def test_ac3_revision_conflict_is_retryable(admin_client):
    study = _create(
        admin_client, title="Revision placeholder", quote=None, results=None, metrics=None
    )
    stale = admin_client.patch(
        f"/api/case-studies/{study['id']}",
        json={
            "challenge": "SYNTHETIC-CHALLENGE-PLACEHOLDER",
            "expected_revision": study["revision"] + 5,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    assert stale.json()["detail"]["retryable"] is True
    assert _stored_flags(study["id"])["revision"] == study["revision"]
    retried = admin_client.patch(
        f"/api/case-studies/{study['id']}",
        json={
            "challenge": "SYNTHETIC-CHALLENGE-PLACEHOLDER",
            "expected_revision": study["revision"],
        },
    )
    assert retried.status_code == 200, retried.status_code
    assert retried.json()["revision"] == study["revision"] + 1
    assert retried.json()["customer_claim"] is False


def _alembic(*args: str) -> None:
    engine.dispose()
    env = os.environ.copy()
    env["TRUST_COPILOT_TESTING"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_get_does_not_change_stored_row(admin_client):
    study = _create(admin_client, title="Read only placeholder")
    before = _row_snapshot(study["id"])
    listed = admin_client.get("/api/case-studies")
    assert listed.status_code == 200
    fetched = admin_client.get(f"/api/case-studies/{study['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == study["title"]
    again = admin_client.get(f"/api/case-studies/{study['id']}")
    assert again.status_code == 200
    after = _row_snapshot(study["id"])
    assert after == before


def test_content_patch_requires_expected_revision(admin_client):
    study = _create(
        admin_client,
        title="Revision required placeholder",
        quote=None,
        results=None,
        metrics=None,
    )
    missing = admin_client.patch(
        f"/api/case-studies/{study['id']}",
        json={"challenge": "SYNTHETIC-CHALLENGE-PLACEHOLDER"},
    )
    assert missing.status_code == 422
    assert _stored_flags(study["id"])["revision"] == study["revision"]
    assert _row_snapshot(study["id"])["quote"] is None


def test_consent_reference_hidden_from_non_admins(client):
    _admin(client)
    study = _create(
        client, title="Reference visibility placeholder", quote=None, results=None, metrics=None
    )
    granted = client.post(
        f"/api/case-studies/{study['id']}/consents",
        json={
            "organization_name": ORG,
            "consent_reference": CONSENT_REF,
            "expected_revision": study["revision"],
        },
    )
    assert granted.status_code == 200, granted.status_code
    study = granted.json()
    assert study["consents"][0]["consent_reference"] == CONSENT_REF
    admin_body = client.get(f"/api/case-studies/{study['id']}").json()
    assert admin_body["consents"][0]["consent_reference"] == CONSENT_REF

    _editor(client)
    editor_body = client.get(f"/api/case-studies/{study['id']}")
    assert editor_body.status_code == 200
    assert editor_body.json()["consents"][0]["consent_reference"] is None
    listed = client.get("/api/case-studies").json()
    listed_row = next(item for item in listed["case_studies"] if item["id"] == study["id"])
    assert listed_row["consents"][0]["consent_reference"] is None
    assert CONSENT_REF not in json.dumps(editor_body.json())
    assert CONSENT_REF not in json.dumps(listed_row)

    _reviewer(client)
    reviewer_body = client.get(f"/api/case-studies/{study['id']}").json()
    assert reviewer_body["consents"][0]["consent_reference"] is None
    assert CONSENT_REF not in json.dumps(reviewer_body)


def test_consent_actions_are_audited_and_delete_keeps_history(client, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="trustcopilot.audit")
    _admin(client)
    study = _create(client, title="Audit placeholder", quote=QUOTE, results=None, metrics=None)
    caplog.clear()
    granted = client.post(
        f"/api/case-studies/{study['id']}/consents",
        json={
            "organization_name": ORG,
            "consent_reference": CONSENT_REF,
            "expected_revision": study["revision"],
        },
    )
    assert granted.status_code == 200, granted.status_code
    study = granted.json()
    consent = next(item for item in study["consents"] if item["active"])
    consent_audit = next(
        item for item in _audit_events(caplog) if item["action"] == "case_study.consent"
    )
    assert consent_audit["organization_name"] == ORG
    assert consent_audit["consent_id"] == consent["id"]
    assert consent_audit["revision"] == study["revision"]
    assert "consent_reference" not in consent_audit
    assert CONSENT_REF not in json.dumps(consent_audit)

    caplog.clear()
    permitted = client.post(
        f"/api/case-studies/{study['id']}/result-permissions",
        json={
            "consent_id": consent["id"],
            "result_key": "quote",
            "expected_revision": study["revision"],
        },
    )
    assert permitted.status_code == 200, permitted.status_code
    study = permitted.json()
    permission = next(item for item in study["result_permissions"] if item["active"])
    permission_audit = next(
        item for item in _audit_events(caplog) if item["action"] == "case_study.result_permission"
    )
    assert permission_audit["consent_id"] == consent["id"]
    assert permission_audit["result_key"] == "quote"
    assert permission_audit["permission_id"] == permission["id"]
    assert permission_audit["revision"] == study["revision"]
    assert "consent_reference" not in permission_audit
    assert CONSENT_REF not in json.dumps(permission_audit)

    caplog.clear()
    revoked_permission = client.post(
        f"/api/case-studies/{study['id']}/result-permissions/{permission['id']}/revoke",
        json={"expected_revision": study["revision"]},
    )
    assert revoked_permission.status_code == 200, revoked_permission.status_code
    revoke_permission_audit = next(
        item
        for item in _audit_events(caplog)
        if item["action"] == "case_study.result_permission_revoke"
    )
    assert revoke_permission_audit["permission_id"] == permission["id"]
    assert revoke_permission_audit["result_key"] == "quote"
    assert revoke_permission_audit["consent_id"] == consent["id"]
    assert CONSENT_REF not in json.dumps(revoke_permission_audit)

    caplog.clear()
    study = revoked_permission.json()
    revoked_consent = client.post(
        f"/api/case-studies/{study['id']}/consents/{consent['id']}/revoke",
        json={"expected_revision": study["revision"]},
    )
    assert revoked_consent.status_code == 200, revoked_consent.status_code
    revoke_consent_audit = next(
        item for item in _audit_events(caplog) if item["action"] == "case_study.consent_revoke"
    )
    assert revoke_consent_audit["consent_id"] == consent["id"]
    assert revoke_consent_audit["organization_name"] == ORG
    assert CONSENT_REF not in json.dumps(revoke_consent_audit)

    caplog.clear()
    study = revoked_consent.json()
    submitted = client.post(
        f"/api/case-studies/{study['id']}/submit-review",
        json={"expected_revision": study["revision"]},
    )
    assert submitted.status_code == 200, submitted.status_code
    submit_audit = next(
        item for item in _audit_events(caplog) if item["action"] == "case_study.submit_review"
    )
    assert submit_audit["revision"] == study["revision"]
    assert submit_audit["review_status"] == "pending"
    assert CONSENT_REF not in json.dumps(submit_audit)

    caplog.clear()
    blocked = client.delete(f"/api/case-studies/{study['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "consent_history_retained"
    assert "consent" in blocked.json()["detail"]["message"].lower()
    engine.dispose()
    db = SessionLocal()
    try:
        remaining = db.execute(
            text("SELECT count(*) FROM case_study_organization_consents WHERE case_study_id = :id"),
            {"id": study["id"]},
        ).scalar()
        permissions = db.execute(
            text("SELECT count(*) FROM case_study_result_permissions WHERE case_study_id = :id"),
            {"id": study["id"]},
        ).scalar()
    finally:
        db.close()
    assert remaining >= 1
    assert permissions >= 1
    assert all(item["action"] != "case_study.delete" for item in _audit_events(caplog))

    caplog.clear()
    plain = _create(
        client,
        title="Deletable placeholder",
        company_name=None,
        quote=None,
        results=None,
        metrics=None,
    )
    deleted = client.delete(f"/api/case-studies/{plain['id']}")
    assert deleted.status_code == 200, deleted.status_code
    delete_audit = next(
        item for item in _audit_events(caplog) if item["action"] == "case_study.delete"
    )
    assert delete_audit["resource_id"] == plain["id"]
    assert "consent_reference" not in delete_audit


def test_case_study_index_names_match_the_database():
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import inspect

    from app.core.database import Base
    from app.models.case_study import (
        CaseStudy,
        CaseStudyOrganizationConsent,
        CaseStudyResultPermission,
    )

    tables = (
        CaseStudy.__table__,
        CaseStudyOrganizationConsent.__table__,
        CaseStudyResultPermission.__table__,
    )
    inspector = inspect(engine)
    for table in tables:
        model_indexes = {index.name for index in table.indexes}
        constraint_names = {constraint.name for constraint in table.constraints if constraint.name}
        db_indexes = {row["name"] for row in inspector.get_indexes(table.name)}
        assert model_indexes
        assert model_indexes <= db_indexes
        assert db_indexes - model_indexes - constraint_names == set()
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        diffs = compare_metadata(context, Base.metadata)
    index_diffs = [
        diff for diff in diffs if "case_stud" in repr(diff) and "index" in repr(diff).lower()
    ]
    assert index_diffs == []


def test_migration_backfill_and_rollback(admin_client):
    try:
        _alembic("downgrade", PARENT_REVISION)
        db = SessionLocal()
        try:
            inserted = db.execute(
                text(
                    """
                    INSERT INTO case_studies (workspace_id, title, status, published_at, company_name)
                    VALUES (1, 'legacy-placeholder-row', 'published', NOW(), :org)
                    RETURNING id
                    """
                ),
                {"org": ORG},
            ).scalar()
            db.commit()
        finally:
            db.close()

        _alembic("upgrade", "head")
        db = SessionLocal()
        try:
            row = db.execute(
                text(
                    """
                    SELECT status, published_at, pre_consent_status, customer_claim, synthetic, data_basis
                    FROM case_studies WHERE id = :id
                    """
                ),
                {"id": inserted},
            ).one()
            assert row.status == "draft"
            assert row.published_at is None
            assert row.pre_consent_status == "published"
            assert row.customer_claim is False
            assert row.synthetic is False
            assert row.data_basis == "unverified"
        finally:
            db.close()

        _alembic("downgrade", PARENT_REVISION)
        db = SessionLocal()
        try:
            restored = db.execute(
                text("SELECT status, published_at FROM case_studies WHERE id = :id"),
                {"id": inserted},
            ).one()
            assert restored.status == "published"
            assert restored.published_at is not None
            regclass = db.execute(
                text("SELECT to_regclass('public.case_study_organization_consents')")
            ).scalar()
            assert regclass is None
            archive = db.execute(
                text("SELECT to_regclass('public.case_study_consent_archive')")
            ).scalar()
            assert str(archive) == "case_study_consent_archive"
            still_there = db.execute(
                text("SELECT count(*) FROM case_studies WHERE id = :id"),
                {"id": inserted},
            ).scalar()
            assert still_there == 1
        finally:
            db.close()
    finally:
        _alembic("upgrade", "head")

    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT status, customer_claim, published_at
                FROM case_studies WHERE title = 'legacy-placeholder-row'
                ORDER BY id DESC LIMIT 1
                """
            )
        ).one()
        assert row.status == "draft"
        assert row.customer_claim is False
        assert row.published_at is None
        consent_table = db.execute(
            text("SELECT to_regclass('public.case_study_organization_consents')")
        ).scalar()
        assert consent_table == "case_study_organization_consents"
    finally:
        db.close()

    response = admin_client.get("/api/case-studies")
    assert response.status_code == 200
    legacy = next(
        item
        for item in response.json()["case_studies"]
        if item["title"] == "legacy-placeholder-row"
    )
    assert legacy["customer_claim"] is False
    assert legacy["status"] == "draft"
    assert legacy["display_label"] == "Not a customer claim."


def _aware(value):
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _rows(db, sql: str, params: dict | None = None) -> list[dict]:
    return [
        {key: _aware(value) for key, value in dict(mapping).items()}
        for mapping in db.execute(text(sql), params or {}).mappings()
    ]


def _case_study_ids(db) -> list[int]:
    return [row["id"] for row in _rows(db, "SELECT id FROM case_studies ORDER BY id")]


def test_migration_downgrade_round_trip_is_lossless(admin_client):
    """Upgrade, add consent and review data, downgrade, upgrade again.

    No case study row is deleted. Consent, permission, and review metadata
    survive in archive tables and come back. Snapshot status is restored only
    for a row still in the exact post-upgrade state. A later workflow change
    is not overwritten. A published claim with no consent is not resurrected.
    A study unpublished on the parent revision, and a study whose quote changed
    there, come back as drafts at revision+1 so the old consent does not cover
    them. Re-upgrade drops the archive tables.
    """
    exact_published_at = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    changed_snapshot_at = datetime(2026, 10, 27, 15, 30, tzinfo=timezone.utc)
    revoked_at = datetime(2026, 10, 27, 16, 0, tzinfo=timezone.utc)

    consented = _create(admin_client, title="roundtrip-consented-placeholder")
    consented = _grant_matrix(admin_client, consented)
    consented = _submit_and_approve(admin_client, consented)
    published = _publish(admin_client, consented)
    assert published.status_code == 200, published.status_code
    consented = published.json()
    assert consented["customer_claim"] is True
    assert consented["status"] == "published"

    changed = _create(
        admin_client,
        title="roundtrip-workflow-changed-placeholder",
        quote=None,
        results=None,
        metrics=None,
    )
    exact = _create(
        admin_client,
        title="roundtrip-exact-snapshot-placeholder",
        quote=None,
        results=None,
        metrics=None,
    )
    tampered = _create(admin_client, title="roundtrip-unconsented-claim-placeholder")
    unpublished_later = _create(admin_client, title="roundtrip-unpublished-at-parent-placeholder")
    unpublished_later = _grant_matrix(admin_client, unpublished_later)
    unpublished_later = _submit_and_approve(admin_client, unpublished_later)
    unpublished_published = _publish(admin_client, unpublished_later)
    assert unpublished_published.status_code == 200, unpublished_published.status_code
    unpublished_later = unpublished_published.json()
    edited_later = _create(admin_client, title="roundtrip-quote-edited-at-parent-placeholder")
    edited_later = _grant_matrix(admin_client, edited_later)
    edited_later = _submit_and_approve(admin_client, edited_later)
    edited_published = _publish(admin_client, edited_later)
    assert edited_published.status_code == 200, edited_published.status_code
    edited_later = edited_published.json()
    edited_quote = "SYNTHETIC-QUOTE-PLACEHOLDER-EDITED"
    unpublished_revision = unpublished_later["revision"]
    edited_revision = edited_later["revision"]

    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO case_study_organization_consents (
                    workspace_id, case_study_id, organization_name, consent_reference,
                    consent_granted, granted_revision, created_at, revoked_at
                ) VALUES (
                    :workspace_id, :case_id, :org, 'SYNTHETIC-CONSENT-REF-REVOKED',
                    TRUE, :revision, :revoked_at, :revoked_at
                )
                """
            ),
            {
                "workspace_id": consented["workspace_id"],
                "case_id": consented["id"],
                "org": ORG,
                "revision": consented["revision"],
                "revoked_at": revoked_at,
            },
        )
        revoked_consent_id = db.execute(
            text(
                """
                SELECT id FROM case_study_organization_consents
                WHERE case_study_id = :case_id AND consent_reference = 'SYNTHETIC-CONSENT-REF-REVOKED'
                """
            ),
            {"case_id": consented["id"]},
        ).scalar()
        db.execute(
            text(
                """
                INSERT INTO case_study_result_permissions (
                    workspace_id, case_study_id, consent_id, result_key, permitted,
                    granted_revision, created_at, revoked_at
                ) VALUES (
                    :workspace_id, :case_id, :consent_id, 'quote', TRUE,
                    :revision, :revoked_at, :revoked_at
                )
                """
            ),
            {
                "workspace_id": consented["workspace_id"],
                "case_id": consented["id"],
                "consent_id": revoked_consent_id,
                "revision": consented["revision"],
                "revoked_at": revoked_at,
            },
        )
        db.execute(
            text(
                """
                UPDATE case_studies
                SET pre_consent_status = 'published',
                    pre_consent_published_at = :snapshot_at,
                    status = 'in_review',
                    published_at = NULL,
                    synthetic = FALSE,
                    customer_claim = FALSE,
                    publication_authorized = FALSE,
                    data_basis = 'unverified',
                    review_status = 'none',
                    revision = 1,
                    schema_version = 'case-study.v2',
                    reviewed_by_user_id = NULL,
                    reviewed_at = NULL,
                    quoted_organizations_json = NULL
                WHERE id = :id
                """
            ),
            {"id": changed["id"], "snapshot_at": changed_snapshot_at},
        )
        db.execute(
            text(
                """
                UPDATE case_studies
                SET pre_consent_status = 'published',
                    pre_consent_published_at = :snapshot_at,
                    status = 'draft',
                    published_at = NULL,
                    synthetic = FALSE,
                    customer_claim = FALSE,
                    publication_authorized = FALSE,
                    data_basis = 'unverified',
                    review_status = 'none',
                    revision = 1,
                    schema_version = 'case-study.v2',
                    reviewed_by_user_id = NULL,
                    reviewed_at = NULL,
                    quoted_organizations_json = NULL
                WHERE id = :id
                """
            ),
            {"id": exact["id"], "snapshot_at": exact_published_at},
        )
        db.execute(
            text(
                """
                UPDATE case_studies
                SET status = 'published',
                    customer_claim = TRUE,
                    publication_authorized = TRUE,
                    review_status = 'approved',
                    data_basis = 'consented_customer',
                    published_at = :published_at
                WHERE id = :id
                """
            ),
            {"id": tampered["id"], "published_at": exact_published_at},
        )
        db.commit()
        before_ids = _case_study_ids(db)
        consents_before = _rows(
            db,
            """
            SELECT id, workspace_id, case_study_id, organization_name, consent_reference,
                   consent_granted, granted_revision, granted_by_user_id, created_at, revoked_at
            FROM case_study_organization_consents
            WHERE case_study_id = :case_id
            ORDER BY id
            """,
            {"case_id": consented["id"]},
        )
        permissions_before = _rows(
            db,
            """
            SELECT id, workspace_id, case_study_id, consent_id, result_key, permitted,
                   granted_revision, granted_by_user_id, created_at, revoked_at
            FROM case_study_result_permissions
            WHERE case_study_id = :case_id
            ORDER BY id
            """,
            {"case_id": consented["id"]},
        )
        review_before = _rows(
            db,
            """
            SELECT status, published_at, customer_claim, publication_authorized, review_status,
                   revision, reviewed_by_user_id, reviewed_at, data_basis, synthetic,
                   schema_version, quoted_organizations_json, title, quote
            FROM case_studies WHERE id = :id
            """,
            {"id": consented["id"]},
        )[0]
        consent_count = db.execute(
            text("SELECT count(*) FROM case_study_organization_consents")
        ).scalar()
        permission_count = db.execute(
            text("SELECT count(*) FROM case_study_result_permissions")
        ).scalar()
        assert consents_before
        assert any(row["revoked_at"] is not None for row in consents_before)
        assert permissions_before
    finally:
        db.close()

    try:
        _alembic("downgrade", PARENT_REVISION)
        db = SessionLocal()
        try:
            assert _case_study_ids(db) == before_ids
            assert (
                db.execute(
                    text("SELECT to_regclass('public.case_study_organization_consents')")
                ).scalar()
                is None
            )
            assert (
                db.execute(
                    text("SELECT to_regclass('public.case_study_result_permissions')")
                ).scalar()
                is None
            )
            for table in (
                "case_study_consent_archive",
                "case_study_result_permission_archive",
                "case_study_review_archive",
            ):
                assert (
                    str(
                        db.execute(
                            text("SELECT to_regclass(:name)"),
                            {"name": f"public.{table}"},
                        ).scalar()
                    )
                    == table
                )
                foreign_keys = db.execute(
                    text(
                        """
                        SELECT count(*) FROM pg_constraint
                        WHERE conrelid = CAST(:name AS regclass) AND contype = 'f'
                        """
                    ),
                    {"name": f"public.{table}"},
                ).scalar()
                assert foreign_keys == 0
            assert (
                db.execute(text("SELECT count(*) FROM case_study_consent_archive")).scalar()
                == consent_count
            )
            assert (
                db.execute(
                    text("SELECT count(*) FROM case_study_result_permission_archive")
                ).scalar()
                == permission_count
            )
            archived_consents = _rows(
                db,
                """
                SELECT id, workspace_id, case_study_id, organization_name, consent_reference,
                       consent_granted, granted_revision, granted_by_user_id, created_at, revoked_at
                FROM case_study_consent_archive
                WHERE case_study_id = :case_id
                ORDER BY id
                """,
                {"case_id": consented["id"]},
            )
            archived_permissions = _rows(
                db,
                """
                SELECT id, workspace_id, case_study_id, consent_id, result_key, permitted,
                       granted_revision, granted_by_user_id, created_at, revoked_at
                FROM case_study_result_permission_archive
                WHERE case_study_id = :case_id
                ORDER BY id
                """,
                {"case_id": consented["id"]},
            )
            assert archived_consents == consents_before
            assert archived_permissions == permissions_before
            archived_review = _rows(
                db,
                """
                SELECT review_status, revision, reviewed_by_user_id, reviewed_at,
                       customer_claim, status_at_archive, published_at_at_archive, snapshot_restored
                FROM case_study_review_archive WHERE case_study_id = :id
                """,
                {"id": consented["id"]},
            )[0]
            assert archived_review["review_status"] == review_before["review_status"]
            assert archived_review["revision"] == review_before["revision"]
            assert archived_review["reviewed_by_user_id"] == review_before["reviewed_by_user_id"]
            assert archived_review["reviewed_at"] == review_before["reviewed_at"]
            assert archived_review["customer_claim"] is True
            assert archived_review["status_at_archive"] == "published"
            assert archived_review["snapshot_restored"] is False
            changed_row = _rows(
                db,
                "SELECT status, published_at FROM case_studies WHERE id = :id",
                {"id": changed["id"]},
            )[0]
            assert changed_row["status"] == "in_review"
            assert changed_row["published_at"] is None
            exact_row = _rows(
                db,
                "SELECT status, published_at FROM case_studies WHERE id = :id",
                {"id": exact["id"]},
            )[0]
            assert exact_row["status"] == "published"
            assert exact_row["published_at"] == exact_published_at
            changed_flag = _rows(
                db,
                "SELECT snapshot_restored FROM case_study_review_archive WHERE case_study_id = :id",
                {"id": changed["id"]},
            )[0]
            exact_flag = _rows(
                db,
                "SELECT snapshot_restored FROM case_study_review_archive WHERE case_study_id = :id",
                {"id": exact["id"]},
            )[0]
            assert changed_flag["snapshot_restored"] is False
            assert exact_flag["snapshot_restored"] is True
            fingerprint = _rows(
                db,
                """
                SELECT title, quote, company_name, challenge, solution, results, metrics_json
                FROM case_study_review_archive WHERE case_study_id = :id
                """,
                {"id": consented["id"]},
            )[0]
            assert fingerprint["title"] == review_before["title"]
            assert fingerprint["quote"] == review_before["quote"]
            assert fingerprint["company_name"] == ORG
            db.execute(
                text(
                    """
                    UPDATE case_studies
                    SET status = 'draft', published_at = NULL
                    WHERE id = :id
                    """
                ),
                {"id": unpublished_later["id"]},
            )
            db.execute(
                text("UPDATE case_studies SET quote = :quote WHERE id = :id"),
                {"id": edited_later["id"], "quote": edited_quote},
            )
            db.commit()
        finally:
            db.close()

        _alembic("upgrade", "head")
        db = SessionLocal()
        try:
            assert _case_study_ids(db) == before_ids
            consents_after = _rows(
                db,
                """
                SELECT id, workspace_id, case_study_id, organization_name, consent_reference,
                       consent_granted, granted_revision, granted_by_user_id, created_at, revoked_at
                FROM case_study_organization_consents
                WHERE case_study_id = :case_id
                ORDER BY id
                """,
                {"case_id": consented["id"]},
            )
            permissions_after = _rows(
                db,
                """
                SELECT id, workspace_id, case_study_id, consent_id, result_key, permitted,
                       granted_revision, granted_by_user_id, created_at, revoked_at
                FROM case_study_result_permissions
                WHERE case_study_id = :case_id
                ORDER BY id
                """,
                {"case_id": consented["id"]},
            )
            assert consents_after == consents_before
            assert permissions_after == permissions_before
            assert (
                db.execute(text("SELECT count(*) FROM case_study_organization_consents")).scalar()
                == consent_count
            )
            assert (
                db.execute(text("SELECT count(*) FROM case_study_result_permissions")).scalar()
                == permission_count
            )
            review_after = _rows(
                db,
                """
                SELECT status, published_at, customer_claim, publication_authorized, review_status,
                       revision, reviewed_by_user_id, reviewed_at, data_basis, synthetic,
                       schema_version, quoted_organizations_json, title, quote
                FROM case_studies WHERE id = :id
                """,
                {"id": consented["id"]},
            )[0]
            assert review_after == review_before
            changed_after = _rows(
                db,
                """
                SELECT status, published_at, customer_claim, pre_consent_status, pre_consent_published_at
                FROM case_studies WHERE id = :id
                """,
                {"id": changed["id"]},
            )[0]
            assert changed_after["status"] == "in_review"
            assert changed_after["published_at"] is None
            assert changed_after["customer_claim"] is False
            assert changed_after["pre_consent_published_at"] == changed_snapshot_at
            exact_after = _rows(
                db,
                """
                SELECT status, published_at, customer_claim, pre_consent_status, title
                FROM case_studies WHERE id = :id
                """,
                {"id": exact["id"]},
            )[0]
            assert exact_after["status"] == "draft"
            assert exact_after["published_at"] is None
            assert exact_after["customer_claim"] is False
            assert exact_after["pre_consent_status"] == "published"
            assert exact_after["title"] == "roundtrip-exact-snapshot-placeholder"
            tampered_after = _rows(
                db,
                """
                SELECT status, published_at, customer_claim, publication_authorized, data_basis, title, quote
                FROM case_studies WHERE id = :id
                """,
                {"id": tampered["id"]},
            )[0]
            assert tampered_after["customer_claim"] is False
            assert tampered_after["publication_authorized"] is False
            assert tampered_after["status"] == "draft"
            assert tampered_after["published_at"] is None
            assert tampered_after["data_basis"] != "consented_customer"
            assert tampered_after["title"] == "roundtrip-unconsented-claim-placeholder"
            assert tampered_after["quote"] == QUOTE
            assert (
                db.execute(
                    text(
                        "SELECT count(*) FROM case_study_organization_consents WHERE case_study_id = :id"
                    ),
                    {"id": tampered["id"]},
                ).scalar()
                == 0
            )
            restored_unpublished = _rows(
                db,
                """
                SELECT status, published_at, customer_claim, publication_authorized, revision
                FROM case_studies WHERE id = :id
                """,
                {"id": unpublished_later["id"]},
            )[0]
            assert restored_unpublished["status"] == "draft"
            assert restored_unpublished["published_at"] is None
            assert restored_unpublished["publication_authorized"] is False
            assert restored_unpublished["customer_claim"] is False
            assert restored_unpublished["revision"] == unpublished_revision + 1
            unpublished_grants = _rows(
                db,
                """
                SELECT granted_revision FROM case_study_organization_consents
                WHERE case_study_id = :id AND revoked_at IS NULL
                """,
                {"id": unpublished_later["id"]},
            )
            assert unpublished_grants
            assert all(
                row["granted_revision"] != restored_unpublished["revision"]
                for row in unpublished_grants
            )
            restored_edited = _rows(
                db,
                """
                SELECT status, published_at, customer_claim, publication_authorized, revision, quote
                FROM case_studies WHERE id = :id
                """,
                {"id": edited_later["id"]},
            )[0]
            assert restored_edited["status"] == "draft"
            assert restored_edited["published_at"] is None
            assert restored_edited["publication_authorized"] is False
            assert restored_edited["customer_claim"] is False
            assert restored_edited["revision"] == edited_revision + 1
            assert restored_edited["quote"] == edited_quote
            edited_grants = _rows(
                db,
                """
                SELECT granted_revision FROM case_study_organization_consents
                WHERE case_study_id = :id AND revoked_at IS NULL
                """,
                {"id": edited_later["id"]},
            )
            assert edited_grants
            assert all(
                row["granted_revision"] != restored_edited["revision"] for row in edited_grants
            )
            for table in (
                "case_study_consent_archive",
                "case_study_result_permission_archive",
                "case_study_review_archive",
            ):
                assert (
                    db.execute(
                        text("SELECT to_regclass(:name)"),
                        {"name": f"public.{table}"},
                    ).scalar()
                    is None
                )
        finally:
            db.close()
    finally:
        _alembic("upgrade", "head")
