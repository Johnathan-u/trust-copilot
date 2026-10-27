"""TC-25-011 evidence-backed demonstration proof summaries.

Runs against PostgreSQL. Inserted rows are synthetic test placeholders in the
database; the product has no per-row provenance flag, so it counts them as
stored workspace records and never as commercial traction. The hardcoded sample
questionnaire is the synthetic placeholder and must not enter proof metrics.
"""

import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

REPO_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = Path(__file__).resolve().parents[2]
PRESENTER = REPO_ROOT / "apps" / "web" / "lib" / "demoProofSummary.mjs"
WHEN = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
PASSWORD = "tc25011-pass"

METRIC_FIELDS = (
    "name",
    "value",
    "unit",
    "source",
    "origin",
    "basis",
    "data_window",
    "numerator",
    "denominator",
    "currency",
    "freshness",
    "commercial_traction",
    "state",
)
BANNED_NUMERIC_KEYS = {
    "revenue",
    "customers",
    "arr",
    "mrr",
    "traffic",
    "hours_saved",
    "hours_saved_estimate",
    "roi",
    "roi_multiple",
}


def _present(payload: dict) -> dict:
    script = (
        "import { presentDemoProof } from './apps/web/lib/demoProofSummary.mjs';"
        "import { readFileSync } from 'node:fs';"
        "const payload = JSON.parse(readFileSync(0, 'utf8'));"
        "process.stdout.write(JSON.stringify(presentDemoProof(payload)));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _walk_traction(obj, path="$"):
    if isinstance(obj, dict):
        if "commercial_traction" in obj:
            assert obj["commercial_traction"] is False, path
        for key, value in obj.items():
            if (
                key in BANNED_NUMERIC_KEYS
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                raise AssertionError(f"{path}.{key} has a numeric value")
            _walk_traction(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            _walk_traction(value, f"{path}[{index}]")


def _metric(summary: dict, name: str) -> dict:
    found = [row for row in summary["metrics"] if row["name"] == name]
    assert len(found) == 1, name
    return found[0]


def _login(client, email: str, password: str = PASSWORD) -> dict:
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _sync_id_sequence(db, table: str) -> None:
    """Explicit seed ids do not advance the serial, so the next insert would collide."""
    if table not in {"workspaces", "users"}:
        raise ValueError(table)
    db.execute(
        text(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"GREATEST(COALESCE((SELECT MAX(id) FROM {table}), 1), 1))"
        )
    )
    db.commit()


def _new_workspace(db, slug: str, name: str):
    from app.models import Workspace

    _sync_id_sequence(db, "workspaces")
    workspace = Workspace(name=name, slug=slug)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def _new_user(db, email: str, workspace_id: int | None, role: str | None):
    from app.core.password import hash_password
    from app.models import User, WorkspaceMember

    _sync_id_sequence(db, "users")
    user = User(
        email=email,
        password_hash=hash_password(PASSWORD),
        display_name="SYNTHETIC TEST PLACEHOLDER user",
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if workspace_id is not None and role is not None:
        db.add(
            WorkspaceMember(
                workspace_id=workspace_id,
                user_id=user.id,
                role=role,
                suspended=False,
            )
        )
        db.commit()
    return user


def _cleanup(workspace_ids: list[int], user_ids: list[int]) -> None:
    from app.core.database import SessionLocal
    from app.models import User, Workspace

    db = SessionLocal()
    try:
        for workspace_id in workspace_ids:
            db.query(Workspace).filter(Workspace.id == workspace_id).delete()
        db.commit()
        for user_id in user_ids:
            db.query(User).filter(User.id == user_id).delete()
        db.commit()
    finally:
        db.close()


def _stamp(row, when: datetime = WHEN) -> None:
    row.created_at = when


@pytest.fixture
def auth_client(client):
    client.cookies.clear()
    response = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert response.status_code == 200, response.text
    return client


def test_legacy_package_keeps_schema_and_labels_synthetic_sample(auth_client):
    response = auth_client.get("/api/demo-proof")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "1"
    assert body["commercial_traction"] is False
    assert body["sample_data_origin"] == "synthetic"
    for key in (
        "sample_questionnaire",
        "coverage_report",
        "gap_list",
        "walkthrough",
        "live_stats",
        "proof_summary",
    ):
        assert key in body
    sample = body["sample_questionnaire"]
    assert sample["total_questions"] >= 10
    assert sample["origin"] == "synthetic"
    assert sample["basis"] == "not_measured"
    assert sample["commercial_traction"] is False
    assert sample["data_window"]["applicable"] is False
    assert sample["questions"][0]["evidence_sources_are_real"] is False
    coverage = body["coverage_report"]
    assert coverage["coverage_pct"] == 100.0
    assert coverage["origin"] == "synthetic"
    assert coverage["commercial_traction"] is False
    assert len(body["walkthrough"]["steps"]) == 5
    assert body["walkthrough"]["origin"] == "synthetic"
    proof = body["proof_summary"]
    assert proof["schema_version"] == "1"
    assert proof["commercial_traction"] is False
    assert "AES-256" not in json.dumps(proof)
    assert "coverage_pct" not in proof
    _walk_traction(body)
    for metric in proof["metrics"]:
        for field in METRIC_FIELDS:
            assert field in metric
        assert metric["currency"] is None
        assert metric["data_window"]["timezone"] == "UTC"
    live = body["live_stats"]
    assert live["commercial_traction"] is False
    assert live["questionnaires_processed"] == _metric(proof, "questionnaires_stored")["value"]
    assert live["questions_answered"] == _metric(proof, "questions_stored")["value"]
    assert live["ai_answers_generated"] == _metric(proof, "answers_stored")["value"]
    assert live["evidence_gaps_identified"] == _metric(proof, "evidence_gaps_stored")["value"]
    assert "not approved answers" in live["legacy_field_notes"]["questions_answered"]


def test_subresource_endpoints_are_synthetic(auth_client):
    questionnaire = auth_client.get("/api/demo-proof/questionnaire")
    coverage = auth_client.get("/api/demo-proof/coverage")
    gaps = auth_client.get("/api/demo-proof/gaps")
    walkthrough = auth_client.get("/api/demo-proof/walkthrough")
    assert questionnaire.status_code == 200
    assert coverage.status_code == 200
    assert gaps.status_code == 200
    assert walkthrough.status_code == 200
    for response in (questionnaire, coverage, gaps, walkthrough):
        body = response.json()
        assert body["origin"] == "synthetic"
        assert body["basis"] == "not_measured"
        assert body["commercial_traction"] is False
        assert body["estimated"] is False
        assert body["measured"] is False


def test_unauthenticated_is_rejected(client):
    client.cookies.clear()
    response = client.get("/api/demo-proof")
    assert response.status_code == 401


def test_invalid_window_uses_api_error(auth_client):
    missing = auth_client.get("/api/demo-proof", params={"window_start": "2026-01-01T00:00:00Z"})
    assert missing.status_code == 400
    body = missing.json()
    assert body["code"] == "invalid_window"
    assert body["retryable"] is False
    assert body["request_id"]
    assert "window_end" in body["field_errors"]
    assert "password" not in json.dumps(body).lower()

    ordered = auth_client.get(
        "/api/demo-proof",
        params={"window_start": "2026-02-01T00:00:00Z", "window_end": "2026-01-01T00:00:00Z"},
    )
    assert ordered.status_code == 400
    assert ordered.json()["code"] == "invalid_window"

    naive = auth_client.get(
        "/api/demo-proof",
        params={"window_start": "2026-01-01T00:00:00", "window_end": "2026-02-01T00:00:00"},
    )
    assert naive.status_code == 400
    assert naive.json()["field_errors"]["window_start"]

    malformed = auth_client.get("/api/demo-proof", params={"workspace_id": "not-an-id"})
    assert malformed.status_code == 422


def test_positive_measured_summary_retry_restart_and_ui(client):
    from app.core.database import SessionLocal
    from app.models import (
        Answer,
        Document,
        EvidenceGap,
        EvidenceItem,
        ExportRecord,
        Question,
        Questionnaire,
    )

    token = uuid.uuid4().hex[:10]
    slug = f"tc25011p{token}"[:64]
    email = f"tc25011-admin-{token}@example.com"
    reviewer_email = f"tc25011-reviewer-{token}@example.com"
    workspace_ids: list[int] = []
    user_ids: list[int] = []
    db = SessionLocal()
    try:
        workspace = _new_workspace(db, slug, "SYNTHETIC TEST PLACEHOLDER workspace")
        workspace_ids.append(workspace.id)
        admin = _new_user(db, email, workspace.id, "admin")
        reviewer = _new_user(db, reviewer_email, workspace.id, "reviewer")
        user_ids.extend([admin.id, reviewer.id])

        deleted_doc = Document(
            workspace_id=workspace.id,
            storage_key=f"synthetic-test/{token}/deleted",
            filename="SYNTHETIC TEST PLACEHOLDER deleted.txt",
            status="indexed",
            deleted_at=WHEN,
        )
        _stamp(deleted_doc)
        indexed = Document(
            workspace_id=workspace.id,
            storage_key=f"synthetic-test/{token}/indexed",
            filename="SYNTHETIC TEST PLACEHOLDER indexed.txt",
            status="indexed",
        )
        _stamp(indexed)
        uploaded = Document(
            workspace_id=workspace.id,
            storage_key=f"synthetic-test/{token}/uploaded",
            filename="SYNTHETIC TEST PLACEHOLDER uploaded.txt",
            status="uploaded",
        )
        _stamp(uploaded)
        deleted_q = Questionnaire(
            workspace_id=workspace.id,
            filename="SYNTHETIC TEST PLACEHOLDER deleted-q.xlsx",
            status="uploaded",
            deleted_at=WHEN,
        )
        _stamp(deleted_q)
        questionnaire = Questionnaire(
            workspace_id=workspace.id,
            filename="SYNTHETIC TEST PLACEHOLDER questionnaire.xlsx",
            status="parsed",
        )
        _stamp(questionnaire)
        db.add_all([deleted_doc, indexed, uploaded, deleted_q, questionnaire])
        db.commit()
        for row in (deleted_doc, indexed, uploaded, deleted_q, questionnaire):
            db.refresh(row)

        questions = []
        for text_value in (
            "SYNTHETIC TEST PLACEHOLDER question one",
            "SYNTHETIC TEST PLACEHOLDER question two",
        ):
            question = Question(
                questionnaire_id=questionnaire.id, text=text_value, section="Access"
            )
            _stamp(question)
            questions.append(question)
        hidden = Question(
            questionnaire_id=deleted_q.id,
            text="SYNTHETIC TEST PLACEHOLDER deleted question",
            section="Access",
        )
        _stamp(hidden)
        db.add_all([*questions, hidden])
        db.commit()
        for question in questions:
            db.refresh(question)

        approved = Answer(
            question_id=questions[0].id,
            text="stored approved answer",
            status="approved",
            confidence=10,
        )
        draft = Answer(
            question_id=questions[1].id, text="stored draft answer", status="draft", confidence=10
        )
        _stamp(approved)
        _stamp(draft)
        approved_evidence = EvidenceItem(
            workspace_id=workspace.id,
            document_id=indexed.id,
            source_type="document",
            title="SYNTHETIC TEST PLACEHOLDER approved evidence",
            approval_status="approved",
        )
        pending_evidence = EvidenceItem(
            workspace_id=workspace.id,
            document_id=None,
            source_type="manual",
            title="SYNTHETIC TEST PLACEHOLDER pending evidence",
            approval_status="pending",
        )
        _stamp(approved_evidence)
        _stamp(pending_evidence)
        completed = ExportRecord(
            workspace_id=workspace.id,
            questionnaire_id=questionnaire.id,
            storage_key=f"synthetic-test/{token}/export",
            filename="SYNTHETIC TEST PLACEHOLDER export.xlsx",
            status="completed",
        )
        failed = ExportRecord(
            workspace_id=workspace.id,
            questionnaire_id=None,
            storage_key=f"synthetic-test/{token}/failed",
            filename="SYNTHETIC TEST PLACEHOLDER failed-export.xlsx",
            status="failed",
        )
        _stamp(completed)
        _stamp(failed)
        gap = EvidenceGap(
            workspace_id=workspace.id,
            questionnaire_id=questionnaire.id,
            question_id=questions[0].id,
            gap_type="missing_evidence",
            reason="SYNTHETIC TEST PLACEHOLDER gap",
            status="open",
        )
        _stamp(gap)
        db.add_all([approved, draft, approved_evidence, pending_evidence, completed, failed, gap])
        db.commit()
    finally:
        db.close()

    try:
        _login(client, email)
        preview = client.get("/api/demo-proof")
        assert preview.status_code == 200, preview.text
        assert preview.json()["proof_summary"]["persisted"] is False
        assert preview.json()["proof_summary"]["summary_id"] is None
        from app.core.database import SessionLocal
        from app.models import DemoProofSummary

        counted = SessionLocal()
        try:
            assert (
                counted.query(DemoProofSummary)
                .filter(DemoProofSummary.workspace_id == workspace_ids[0])
                .count()
                == 0
            )
        finally:
            counted.close()
        first = client.post("/api/demo-proof")
        assert first.status_code == 200, first.text
        body = first.json()
        proof = body["proof_summary"]
        expected = {
            "questionnaires_stored": 1,
            "questions_stored": 2,
            "answers_stored": 2,
            "answers_approved": 1,
            "documents_stored": 2,
            "documents_indexed": 1,
            "evidence_items_stored": 2,
            "evidence_items_approved": 1,
            "exports_stored": 2,
            "exports_completed": 1,
            "evidence_gaps_stored": 1,
        }
        for name, value in expected.items():
            metric = _metric(proof, name)
            assert metric["value"] == value, name
            assert metric["origin"] == "real"
            assert metric["basis"] == "measured"
            assert metric["measured"] is True
            assert metric["estimated"] is False
            assert metric["commercial_traction"] is False
            assert metric["state"] == "measured"
            assert metric["data_window"]["start"].startswith("2026-01-15")
            assert metric["data_window"]["end"].startswith("2026-01-15")
            assert metric["data_window"]["timezone"] == "UTC"
        assert _metric(proof, "answers_approved")["denominator"] == 2
        assert _metric(proof, "documents_indexed")["denominator"] == 2
        assert _metric(proof, "exports_completed")["numerator"] == 1
        assert _metric(proof, "questionnaires_stored")["exclusions"]["deleted"] == 1
        assert proof["status"] == "complete"
        assert proof["partial_failures"] == []
        assert proof["summary_id"]
        assert proof["content_hash"]
        assert {row["name"] for row in proof["unsupported"]} >= {"customers", "revenue", "traffic"}
        for row in proof["unsupported"]:
            assert row["value"] is None
            assert row["state"] == "unsupported"
            assert row["commercial_traction"] is False
        for row in proof["synthetic_placeholders"]:
            assert row["origin"] == "synthetic"
            assert row["basis"] == "not_measured"
            assert row["value"] is None
            assert row["commercial_traction"] is False
        assert proof["commercial_traction"] is False
        assert "AES-256" not in json.dumps(proof)
        sample_total = body["sample_questionnaire"]["total_questions"]
        assert sample_total not in {metric["value"] for metric in proof["metrics"]}
        _walk_traction(body)

        second = client.post("/api/demo-proof")
        assert second.status_code == 200
        again = second.json()["proof_summary"]
        assert again == proof
        assert again["summary_id"] == proof["summary_id"]
        assert again["generated_at"] == proof["generated_at"]

        from app.core.database import SessionLocal
        from app.models import DemoProofSummary

        restarted = SessionLocal()
        try:
            stored = restarted.get(DemoProofSummary, proof["summary_id"])
            assert stored is not None
            assert stored.workspace_id == workspace_ids[0]
            assert json.loads(stored.summary_json) == proof
            count = (
                restarted.query(DemoProofSummary)
                .filter(DemoProofSummary.idempotency_key == proof["idempotency_key"])
                .count()
            )
            assert count == 1
        finally:
            restarted.close()

        _login(client, reviewer_email)
        reviewed = client.get("/api/demo-proof")
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["proof_summary"]["summary_id"] == proof["summary_id"]

        by_id = client.get(f"/api/demo-proof/summaries/{proof['summary_id']}")
        assert by_id.status_code == 200
        assert by_id.json() == proof

        presented = _present(body)
        assert presented["summaryId"] == proof["summary_id"]
        assert presented["contentHash"] == proof["content_hash"]
        assert presented["commercialTraction"] is False
        assert presented["tractionLabel"] == "Not commercial traction"
        assert presented["status"] == "complete"
        assert [row["name"] for row in presented["rows"]] == [
            metric["name"] for metric in proof["metrics"]
        ]
        for row, metric in zip(presented["rows"], proof["metrics"]):
            assert row["value"] == metric["value"]
            assert row["origin"] == metric["origin"]
            assert row["basis"] == metric["basis"]
            assert row["state"] == metric["state"]
            assert row["commercialTraction"] is False
            assert row["displayValue"] == str(metric["value"])
            assert row["windowStart"] == metric["data_window"]["start"]
            assert row["windowEnd"] == metric["data_window"]["end"]
            assert row["timezone"] == "UTC"
        assert all(item["value"] is None for item in presented["synthetic"])
        assert all(item["value"] is None for item in presented["unsupported"])
        assert "AES-256" not in json.dumps(presented)
        assert "coverage_pct" not in json.dumps(presented)
    finally:
        _cleanup(workspace_ids, user_ids)


def test_no_data_workspace_is_not_filled_from_the_sample(client):
    token = uuid.uuid4().hex[:10]
    email = f"tc25011-empty-{token}@example.com"
    workspace_ids: list[int] = []
    user_ids: list[int] = []
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        workspace = _new_workspace(db, f"tc25011e{token}"[:64], "SYNTHETIC TEST PLACEHOLDER empty")
        workspace_ids.append(workspace.id)
        user = _new_user(db, email, workspace.id, "editor")
        user_ids.append(user.id)
    finally:
        db.close()
    try:
        _login(client, email)
        response = client.get("/api/demo-proof")
        assert response.status_code == 200, response.text
        body = response.json()
        proof = body["proof_summary"]
        assert proof["status"] == "no_data"
        assert proof["partial_failures"] == []
        assert proof["data_window"]["start"] is None
        assert proof["data_window"]["end"] is None
        for metric in proof["metrics"]:
            assert metric["value"] == 0
            assert metric["state"] == "no_data"
            assert metric["origin"] == "real"
            assert metric["basis"] == "measured"
            assert metric["commercial_traction"] is False
        for row in proof["unsupported"]:
            assert row["value"] is None
            assert row["state"] == "unsupported"
        assert body["sample_questionnaire"]["total_questions"] >= 10
        assert body["live_stats"]["questionnaires_processed"] == 0
        presented = _present(body)
        assert presented["status"] == "no_data"
        assert {row["displayValue"] for row in presented["rows"]} == {"No data"}
        assert all(row["value"] == 0 for row in presented["rows"])
        _walk_traction(body)
    finally:
        _cleanup(workspace_ids, user_ids)


def test_requested_window_excludes_rows_outside_it(client):
    from app.core.database import SessionLocal
    from app.models import Questionnaire

    token = uuid.uuid4().hex[:10]
    email = f"tc25011-window-{token}@example.com"
    workspace_ids: list[int] = []
    user_ids: list[int] = []
    early = datetime(2026, 1, 1, tzinfo=timezone.utc)
    late = datetime(2026, 6, 1, tzinfo=timezone.utc)
    db = SessionLocal()
    try:
        workspace = _new_workspace(db, f"tc25011w{token}"[:64], "SYNTHETIC TEST PLACEHOLDER window")
        workspace_ids.append(workspace.id)
        user = _new_user(db, email, workspace.id, "admin")
        user_ids.append(user.id)
        older = Questionnaire(
            workspace_id=workspace.id,
            filename="SYNTHETIC TEST PLACEHOLDER early.xlsx",
            status="uploaded",
        )
        newer = Questionnaire(
            workspace_id=workspace.id,
            filename="SYNTHETIC TEST PLACEHOLDER late.xlsx",
            status="uploaded",
        )
        _stamp(older, early)
        _stamp(newer, late)
        db.add_all([older, newer])
        db.commit()
    finally:
        db.close()
    try:
        _login(client, email)
        bounded = client.get(
            "/api/demo-proof",
            params={"window_start": "2026-05-01T00:00:00Z", "window_end": "2026-07-01T00:00:00Z"},
        )
        assert bounded.status_code == 200, bounded.text
        proof = bounded.json()["proof_summary"]
        assert _metric(proof, "questionnaires_stored")["value"] == 1
        assert _metric(proof, "questionnaires_stored")["exclusions"]["outside_window"] == 1
        assert proof["data_window"]["start"].startswith("2026-05-01")
        assert proof["data_window"]["timezone"] == "UTC"
        open_window = client.get("/api/demo-proof")
        assert _metric(open_window.json()["proof_summary"], "questionnaires_stored")["value"] == 2
    finally:
        _cleanup(workspace_ids, user_ids)


def test_foreign_reference_partial_failure_excludes_other_workspace(client):
    from app.core.database import SessionLocal
    from app.models import (
        Document,
        EvidenceGap,
        EvidenceItem,
        ExportRecord,
        Question,
        Questionnaire,
    )

    token = uuid.uuid4().hex[:10]
    owner_email = f"tc25011-owner-{token}@example.com"
    other_email = f"tc25011-other-{token}@example.com"
    marker = f"SYNTHETIC TEST PLACEHOLDER other-workspace-{token}"
    workspace_ids: list[int] = []
    user_ids: list[int] = []
    db = SessionLocal()
    try:
        own = _new_workspace(db, f"tc25011o{token}"[:64], "SYNTHETIC TEST PLACEHOLDER own")
        other = _new_workspace(db, f"tc25011x{token}"[:64], "SYNTHETIC TEST PLACEHOLDER other")
        workspace_ids.extend([own.id, other.id])
        owner = _new_user(db, owner_email, own.id, "admin")
        stranger = _new_user(db, other_email, other.id, "admin")
        user_ids.extend([owner.id, stranger.id])
        own_doc = Document(
            workspace_id=own.id,
            storage_key=f"synthetic-test/{token}/own",
            filename="SYNTHETIC TEST PLACEHOLDER own.txt",
            status="indexed",
        )
        other_doc = Document(
            workspace_id=other.id,
            storage_key=f"synthetic-test/{token}/other",
            filename=marker,
            status="indexed",
        )
        deleted_doc = Document(
            workspace_id=own.id,
            storage_key=f"synthetic-test/{token}/gone",
            filename="SYNTHETIC TEST PLACEHOLDER gone.txt",
            status="indexed",
            deleted_at=WHEN,
        )
        _stamp(own_doc)
        _stamp(other_doc)
        _stamp(deleted_doc)
        own_q = Questionnaire(
            workspace_id=own.id, filename="SYNTHETIC TEST PLACEHOLDER own.xlsx", status="parsed"
        )
        other_q = Questionnaire(workspace_id=other.id, filename=marker + ".xlsx", status="parsed")
        _stamp(own_q)
        _stamp(other_q)
        db.add_all([own_doc, other_doc, deleted_doc, own_q, other_q])
        db.commit()
        for row in (own_doc, other_doc, deleted_doc, own_q, other_q):
            db.refresh(row)
        other_question = Question(questionnaire_id=other_q.id, text=marker, section="Other")
        _stamp(other_question)
        db.add(other_question)
        db.commit()
        db.refresh(other_question)
        valid = EvidenceItem(
            workspace_id=own.id,
            document_id=own_doc.id,
            source_type="document",
            title="SYNTHETIC TEST PLACEHOLDER valid",
            approval_status="approved",
        )
        foreign_evidence = EvidenceItem(
            workspace_id=own.id,
            document_id=other_doc.id,
            source_type="document",
            title="SYNTHETIC TEST PLACEHOLDER foreign evidence",
            approval_status="approved",
        )
        deleted_evidence = EvidenceItem(
            workspace_id=own.id,
            document_id=deleted_doc.id,
            source_type="document",
            title="SYNTHETIC TEST PLACEHOLDER deleted evidence",
            approval_status="approved",
        )
        valid_export = ExportRecord(
            workspace_id=own.id,
            questionnaire_id=own_q.id,
            storage_key=f"synthetic-test/{token}/ok",
            filename="SYNTHETIC TEST PLACEHOLDER ok.xlsx",
            status="completed",
        )
        foreign_export = ExportRecord(
            workspace_id=own.id,
            questionnaire_id=other_q.id,
            storage_key=f"synthetic-test/{token}/foreign",
            filename="SYNTHETIC TEST PLACEHOLDER foreign-export.xlsx",
            status="completed",
        )
        foreign_gap = EvidenceGap(
            workspace_id=own.id,
            question_id=other_question.id,
            gap_type="missing_evidence",
            reason=marker,
            status="open",
        )
        for row in (
            valid,
            foreign_evidence,
            deleted_evidence,
            valid_export,
            foreign_export,
            foreign_gap,
        ):
            _stamp(row)
        db.add_all(
            [valid, foreign_evidence, deleted_evidence, valid_export, foreign_export, foreign_gap]
        )
        db.commit()
        for row in (foreign_evidence, deleted_evidence, foreign_export, foreign_gap):
            db.refresh(row)
        foreign_ids = {
            "evidence": foreign_evidence.id,
            "deleted": deleted_evidence.id,
            "export": foreign_export.id,
            "gap": foreign_gap.id,
            "other_doc": other_doc.id,
        }
    finally:
        db.close()

    try:
        _login(client, owner_email)
        response = client.post("/api/demo-proof")
        assert response.status_code == 200, response.text
        body = response.json()
        proof = body["proof_summary"]
        assert proof["status"] == "partial"
        assert _metric(proof, "evidence_items_stored")["value"] == 1
        assert _metric(proof, "evidence_items_approved")["value"] == 1
        assert _metric(proof, "evidence_items_stored")["exclusions"]["foreign_reference"] == 2
        assert _metric(proof, "exports_completed")["value"] == 1
        assert _metric(proof, "exports_stored")["value"] == 1
        assert _metric(proof, "evidence_gaps_stored")["value"] == 0
        failures = {row["source"]: row for row in proof["partial_failures"]}
        assert failures["evidence_items"]["code"] == "foreign_reference_rejected"
        assert failures["evidence_items"]["retryable"] is False
        assert set(failures["evidence_items"]["record_ids"]) == {
            foreign_ids["evidence"],
            foreign_ids["deleted"],
        }
        assert "other_workspace" in failures["evidence_items"]["reasons"]
        assert "deleted" in failures["evidence_items"]["reasons"]
        assert failures["exports"]["record_ids"] == [foreign_ids["export"]]
        assert failures["evidence_gaps"]["record_ids"] == [foreign_ids["gap"]]
        assert marker not in response.text
        assert proof["commercial_traction"] is False

        second = client.post("/api/demo-proof")
        assert second.json()["proof_summary"] == proof
        from app.core.database import SessionLocal
        from app.models import DemoProofSummary

        restarted = SessionLocal()
        try:
            stored = json.loads(restarted.get(DemoProofSummary, proof["summary_id"]).summary_json)
        finally:
            restarted.close()
        assert stored == proof

        _login(client, other_email)
        denied = client.get(f"/api/demo-proof/summaries/{proof['summary_id']}")
        assert denied.status_code == 404
        assert denied.json()["code"] == "summary_not_found"
        mismatch = client.get("/api/demo-proof", params={"workspace_id": workspace_ids[0]})
        assert mismatch.status_code == 404
        assert mismatch.json()["code"] == "workspace_mismatch"
        stranger_body = client.get("/api/demo-proof")
        assert stranger_body.status_code == 200
        assert marker not in stranger_body.text
        assert _metric(stranger_body.json()["proof_summary"], "documents_stored")["value"] == 1
    finally:
        _cleanup(workspace_ids, user_ids)


def test_source_unavailable_is_partial_and_not_zero(client, monkeypatch):
    from app.core.database import SessionLocal
    from app.models import Questionnaire
    from app.services import demo_proof_service

    token = uuid.uuid4().hex[:10]
    email = f"tc25011-partial-{token}@example.com"
    workspace_ids: list[int] = []
    user_ids: list[int] = []
    secret = f"boom-secret-{token}"
    db = SessionLocal()
    try:
        workspace = _new_workspace(
            db, f"tc25011s{token}"[:64], "SYNTHETIC TEST PLACEHOLDER partial"
        )
        workspace_ids.append(workspace.id)
        user = _new_user(db, email, workspace.id, "admin")
        user_ids.append(user.id)
        questionnaire = Questionnaire(
            workspace_id=workspace.id,
            filename="SYNTHETIC TEST PLACEHOLDER partial.xlsx",
            status="uploaded",
        )
        _stamp(questionnaire)
        db.add(questionnaire)
        db.commit()
    finally:
        db.close()

    def _boom(_db, _workspace_id, _window):
        raise RuntimeError(secret)

    monkeypatch.setitem(demo_proof_service.COLLECTORS, "exports", _boom)
    try:
        _login(client, email)
        response = client.post("/api/demo-proof")
        assert response.status_code == 200, response.text
        assert secret not in response.text
        proof = response.json()["proof_summary"]
        assert proof["status"] == "partial"
        assert _metric(proof, "questionnaires_stored")["value"] == 1
        assert _metric(proof, "questionnaires_stored")["state"] == "measured"
        for name in ("exports_stored", "exports_completed"):
            metric = _metric(proof, name)
            assert metric["value"] is None
            assert metric["state"] == "unavailable"
            assert metric["basis"] is None
            assert metric["commercial_traction"] is False
        unavailable = [
            row for row in proof["partial_failures"] if row["code"] == "source_unavailable"
        ]
        assert len(unavailable) == 1
        assert unavailable[0]["source"] == "exports"
        assert unavailable[0]["retryable"] is True
        retry = client.post("/api/demo-proof")
        assert retry.json()["proof_summary"] == proof
        from app.core.database import SessionLocal
        from app.models import DemoProofSummary

        restarted = SessionLocal()
        try:
            stored = json.loads(restarted.get(DemoProofSummary, proof["summary_id"]).summary_json)
        finally:
            restarted.close()
        assert stored == proof
    finally:
        _cleanup(workspace_ids, user_ids)


def test_permission_and_api_key_checks(client):
    from app.core.database import SessionLocal
    from app.models import ApiKey, CustomRole, DemoProofSummary, WorkspaceMember

    token = uuid.uuid4().hex[:10]
    member_email = f"tc25011-member-{token}@example.com"
    reviewer_email = f"tc25011-reviewer-{token}@example.com"
    no_perm_email = f"tc25011-noperm-{token}@example.com"
    removed_email = f"tc25011-removed-{token}@example.com"
    suspended_email = f"tc25011-suspended-{token}@example.com"
    lonely_email = f"tc25011-lonely-{token}@example.com"
    workspace_ids: list[int] = []
    user_ids: list[int] = []
    raw_read_key = f"tc25011-synthetic-read-{token}"
    raw_reviewer_key = f"tc25011-synthetic-reviewer-{token}"
    raw_editor_key = f"tc25011-synthetic-editor-{token}"
    raw_bad_key = f"tc25011-synthetic-bad-{token}"
    db = SessionLocal()
    try:
        workspace = _new_workspace(
            db, f"tc25011m{token}"[:64], "SYNTHETIC TEST PLACEHOLDER members"
        )
        workspace_ids.append(workspace.id)
        member = _new_user(db, member_email, workspace.id, "editor")
        reviewer = _new_user(db, reviewer_email, workspace.id, "reviewer")
        no_perm = _new_user(db, no_perm_email, workspace.id, "no-permission")
        removed = _new_user(db, removed_email, workspace.id, "editor")
        suspended = _new_user(db, suspended_email, workspace.id, "admin")
        lonely = _new_user(db, lonely_email, None, None)
        removed_user_id = removed.id
        user_ids.extend(
            [member.id, reviewer.id, no_perm.id, removed_user_id, suspended.id, lonely.id]
        )
        db.add(
            CustomRole(
                workspace_id=workspace.id,
                name="no-permission",
                description="SYNTHETIC TEST PLACEHOLDER no permissions",
                can_edit=False,
                can_review=False,
                can_export=False,
                can_admin=False,
            )
        )
        db.add_all(
            [
                ApiKey(
                    workspace_id=workspace.id,
                    key_hash=hashlib.sha256(raw_read_key.encode()).hexdigest(),
                    label="SYNTHETIC TEST PLACEHOLDER read key",
                    role="read",
                ),
                ApiKey(
                    workspace_id=workspace.id,
                    key_hash=hashlib.sha256(raw_reviewer_key.encode()).hexdigest(),
                    label="SYNTHETIC TEST PLACEHOLDER reviewer key",
                    role="reviewer",
                ),
                ApiKey(
                    workspace_id=workspace.id,
                    key_hash=hashlib.sha256(raw_editor_key.encode()).hexdigest(),
                    label="SYNTHETIC TEST PLACEHOLDER editor key",
                    role="editor",
                ),
                ApiKey(
                    workspace_id=workspace.id,
                    key_hash=hashlib.sha256(raw_bad_key.encode()).hexdigest(),
                    label="SYNTHETIC TEST PLACEHOLDER unknown role",
                    role="not-a-role",
                ),
            ]
        )
        db.query(WorkspaceMember).filter(WorkspaceMember.user_id == suspended.id).update(
            {"suspended": True}
        )
        db.commit()
    finally:
        db.close()

    try:
        _login(client, suspended_email)
        suspended_response = client.get("/api/demo-proof")
        assert suspended_response.status_code == 403
        assert "suspended" in suspended_response.text.lower()

        _login(client, removed_email)
        db = SessionLocal()
        try:
            db.query(WorkspaceMember).filter(WorkspaceMember.user_id == removed_user_id).delete()
            db.commit()
        finally:
            db.close()
        removed_response = client.get("/api/demo-proof")
        assert removed_response.status_code == 403
        assert removed_response.json()["code"] == "not_a_member"

        _login(client, lonely_email)
        lonely_response = client.get("/api/demo-proof")
        assert lonely_response.status_code == 403
        assert lonely_response.json()["code"] == "not_a_member"

        client.cookies.clear()
        allowed = client.get("/api/demo-proof", headers={"Authorization": f"Bearer {raw_read_key}"})
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["workspace_id"] == workspace_ids[0]
        assert allowed.json()["commercial_traction"] is False
        mismatch = client.get(
            "/api/demo-proof",
            params={"workspace_id": 1},
            headers={"Authorization": f"Bearer {raw_read_key}"},
        )
        assert mismatch.status_code == 404
        assert mismatch.json()["code"] == "workspace_mismatch"
        saved = client.post("/api/demo-proof", headers={"Authorization": f"Bearer {raw_read_key}"})
        assert saved.status_code == 403, saved.text
        assert saved.json()["code"] == "api_key_cannot_save"
        mismatch_post = client.post(
            "/api/demo-proof",
            params={"workspace_id": 1},
            headers={"Authorization": f"Bearer {raw_read_key}"},
        )
        assert mismatch_post.status_code == 404
        assert mismatch_post.json()["code"] == "workspace_mismatch"
        for raw_key in (raw_reviewer_key, raw_editor_key, raw_bad_key):
            client.cookies.clear()
            rejected = client.get("/api/demo-proof", headers={"Authorization": f"Bearer {raw_key}"})
            assert rejected.status_code == 403, rejected.text
            assert rejected.json()["code"] == "api_key_not_read_scoped"
            rejected_post = client.post(
                "/api/demo-proof", headers={"Authorization": f"Bearer {raw_key}"}
            )
            assert rejected_post.status_code == 403, rejected_post.text
            assert rejected_post.json()["code"] == "api_key_cannot_save"

        _login(client, reviewer_email)
        reviewer_read = client.get("/api/demo-proof")
        assert reviewer_read.status_code == 200, reviewer_read.text
        reviewer_save = client.post("/api/demo-proof")
        assert reviewer_save.status_code == 403, reviewer_save.text
        assert "Insufficient permissions" in reviewer_save.text

        _login(client, no_perm_email)
        no_perm_read = client.get("/api/demo-proof")
        assert no_perm_read.status_code == 200, no_perm_read.text
        no_perm_save = client.post("/api/demo-proof")
        assert no_perm_save.status_code == 403, no_perm_save.text
        assert "Insufficient permissions" in no_perm_save.text

        counted = SessionLocal()
        try:
            assert (
                counted.query(DemoProofSummary)
                .filter(DemoProofSummary.workspace_id == workspace_ids[0])
                .count()
                == 0
            )
        finally:
            counted.close()
    finally:
        _cleanup(workspace_ids, user_ids)


def test_snapshot_history_stays_stable_when_evidence_changes(client):
    from app.core.database import SessionLocal
    from app.models import Questionnaire

    token = uuid.uuid4().hex[:10]
    email = f"tc25011-hist-{token}@example.com"
    workspace_ids: list[int] = []
    user_ids: list[int] = []
    db = SessionLocal()
    try:
        workspace = _new_workspace(
            db, f"tc25011h{token}"[:64], "SYNTHETIC TEST PLACEHOLDER history"
        )
        workspace_ids.append(workspace.id)
        user = _new_user(db, email, workspace.id, "admin")
        user_ids.append(user.id)
        first_row = Questionnaire(
            workspace_id=workspace.id,
            filename="SYNTHETIC TEST PLACEHOLDER history-1.xlsx",
            status="uploaded",
        )
        _stamp(first_row)
        db.add(first_row)
        db.commit()
    finally:
        db.close()
    try:
        _login(client, email)
        original = client.post("/api/demo-proof").json()["proof_summary"]
        assert _metric(original, "questionnaires_stored")["value"] == 1
        db = SessionLocal()
        try:
            extra = Questionnaire(
                workspace_id=workspace_ids[0],
                filename="SYNTHETIC TEST PLACEHOLDER history-2.xlsx",
                status="uploaded",
            )
            _stamp(extra)
            db.add(extra)
            db.commit()
        finally:
            db.close()
        latest = client.post("/api/demo-proof").json()["proof_summary"]
        assert latest["summary_id"] != original["summary_id"]
        assert _metric(latest, "questionnaires_stored")["value"] == 2
        stored = client.get(f"/api/demo-proof/summaries/{original['summary_id']}")
        assert stored.status_code == 200
        assert stored.json() == original
        from app.core.database import SessionLocal as Restart
        from app.models import DemoProofSummary

        restarted = Restart()
        try:
            assert (
                json.loads(restarted.get(DemoProofSummary, original["summary_id"]).summary_json)
                == original
            )
        finally:
            restarted.close()
    finally:
        _cleanup(workspace_ids, user_ids)


def test_unreadable_snapshot_is_not_replaced(client):
    from app.core.database import SessionLocal
    from app.models import DemoProofSummary

    token = uuid.uuid4().hex[:10]
    email = f"tc25011-badjson-{token}@example.com"
    workspace_ids: list[int] = []
    user_ids: list[int] = []
    db = SessionLocal()
    try:
        workspace = _new_workspace(
            db, f"tc25011b{token}"[:64], "SYNTHETIC TEST PLACEHOLDER unreadable"
        )
        workspace_ids.append(workspace.id)
        user = _new_user(db, email, workspace.id, "admin")
        user_ids.append(user.id)
    finally:
        db.close()
    try:
        _login(client, email)
        created = client.post("/api/demo-proof")
        summary_id = created.json()["proof_summary"]["summary_id"]
        db = SessionLocal()
        try:
            row = db.get(DemoProofSummary, summary_id)
            row.summary_json = "{"
            db.commit()
        finally:
            db.close()
        response = client.get(f"/api/demo-proof/summaries/{summary_id}")
        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "summary_unreadable"
        assert body["retryable"] is True
        assert "{" not in body["message"]
        assert "Traceback" not in response.text
    finally:
        _cleanup(workspace_ids, user_ids)


def test_foreign_keys_reject_unknown_workspace_and_user(client):
    from app.core.database import SessionLocal
    from app.models import DemoProofSummary

    db = SessionLocal()
    try:
        bad_workspace = DemoProofSummary(
            workspace_id=9_999_999,
            schema_version="1",
            idempotency_key="a" * 64,
            content_hash="b" * 64,
            status="no_data",
            timezone="UTC",
            summary_json="{}",
        )
        db.add(bad_workspace)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        token = uuid.uuid4().hex[:10]
        workspace = _new_workspace(db, f"tc25011f{token}"[:64], "SYNTHETIC TEST PLACEHOLDER fk")
        bad_user = DemoProofSummary(
            workspace_id=workspace.id,
            schema_version="1",
            idempotency_key="c" * 64,
            content_hash="d" * 64,
            status="no_data",
            timezone="UTC",
            summary_json="{}",
            created_by_user_id=9_999_999,
        )
        db.add(bad_user)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.query(type(workspace)).filter_by(id=workspace.id).delete()
        db.commit()
    finally:
        db.close()


def test_zz_migration_rollback_drops_snapshots_and_keeps_evidence(client):
    from app.core.database import SessionLocal, engine
    from app.models import Document, Questionnaire

    token = uuid.uuid4().hex[:10]
    email = f"tc25011-roll-{token}@example.com"
    workspace_ids: list[int] = []
    user_ids: list[int] = []
    db = SessionLocal()
    try:
        workspace = _new_workspace(
            db, f"tc25011r{token}"[:64], "SYNTHETIC TEST PLACEHOLDER rollback"
        )
        workspace_ids.append(workspace.id)
        user = _new_user(db, email, workspace.id, "admin")
        user_ids.append(user.id)
        questionnaire = Questionnaire(
            workspace_id=workspace.id,
            filename="SYNTHETIC TEST PLACEHOLDER rollback.xlsx",
            status="uploaded",
        )
        document = Document(
            workspace_id=workspace.id,
            storage_key=f"synthetic-test/{token}/rollback",
            filename="SYNTHETIC TEST PLACEHOLDER rollback.txt",
            status="uploaded",
        )
        _stamp(questionnaire)
        _stamp(document)
        db.add_all([questionnaire, document])
        db.commit()
        db.refresh(questionnaire)
        questionnaire_id = questionnaire.id
    finally:
        db.close()

    def _alembic(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=str(API_ROOT),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=180,
        )

    def _table_exists(name: str) -> bool:
        probe = SessionLocal()
        try:
            found = probe.execute(
                text("SELECT to_regclass(:name)"),
                {"name": name},
            ).scalar()
            return found is not None
        finally:
            probe.close()

    try:
        _login(client, email)
        created = client.post("/api/demo-proof")
        assert created.status_code == 200, created.text
        summary_id = created.json()["proof_summary"]["summary_id"]
        engine.dispose()
        downgraded = _alembic("downgrade", "tc11001_model_outcome_codes")
        assert downgraded.returncode == 0, downgraded.stderr
        engine.dispose()
        assert _table_exists("demo_proof_summaries") is False
        assert _table_exists("documents") is True
        assert _table_exists("questionnaires") is True
        column = SessionLocal()
        try:
            outcome = column.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'answers' AND column_name = 'outcome_code'
                    """
                )
            ).scalar()
        finally:
            column.close()
        assert outcome == 1
        upgraded = _alembic("upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        engine.dispose()
        assert _table_exists("demo_proof_summaries") is True
        probe = SessionLocal()
        try:
            still = probe.get(Questionnaire, questionnaire_id)
            assert still is not None
            assert still.filename.startswith("SYNTHETIC TEST PLACEHOLDER")
            from app.models import DemoProofSummary

            assert probe.get(DemoProofSummary, summary_id) is None
        finally:
            probe.close()
        rebuilt = client.post("/api/demo-proof")
        assert rebuilt.status_code == 200, rebuilt.text
        proof = rebuilt.json()["proof_summary"]
        assert proof["summary_id"] != summary_id
        assert _metric(proof, "questionnaires_stored")["value"] == 1
        assert _metric(proof, "documents_stored")["value"] == 1
        assert proof["commercial_traction"] is False
        constraints = SessionLocal()
        try:
            names = {
                row[0]
                for row in constraints.execute(
                    text(
                        """
                        SELECT con.conname
                        FROM pg_constraint con
                        JOIN pg_class rel ON rel.oid = con.conrelid
                        WHERE rel.relname = 'demo_proof_summaries'
                        """
                    )
                )
            }
        finally:
            constraints.close()
        assert "uq_demo_proof_summary_workspace_key" in names
        assert any("workspace" in name for name in names)
        assert any("user" in name for name in names)
    finally:
        engine.dispose()
        restored = _alembic("upgrade", "head")
        assert restored.returncode == 0, restored.stderr
        engine.dispose()
        _cleanup(workspace_ids, user_ids)
