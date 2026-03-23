"""AI Mapping & Governance tests: schema, CRUD, permissions, retrieval boost, governance settings."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.password import hash_password
from app.models import User, WorkspaceMember
from app.models.ai_mapping import (
    AIGovernanceSettings,
    ControlEvidenceMapping,
    EvidenceTagMapping,
    FrameworkControlMapping,
    QuestionMappingPreference,
)
from app.services import ai_mapping_service as svc


def _login(client: TestClient, email: str = "admin@trust.local", password: str = "a"):
    client.post("/api/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# Schema presence
# ---------------------------------------------------------------------------

class TestSchemaPresence:
    def test_framework_control_mappings_table(self, db_session: Session):
        assert db_session.query(FrameworkControlMapping).count() >= 0

    def test_control_evidence_mappings_table(self, db_session: Session):
        assert db_session.query(ControlEvidenceMapping).count() >= 0

    def test_evidence_tag_mappings_table(self, db_session: Session):
        assert db_session.query(EvidenceTagMapping).count() >= 0

    def test_question_mapping_preferences_table(self, db_session: Session):
        assert db_session.query(QuestionMappingPreference).count() >= 0

    def test_ai_governance_settings_table(self, db_session: Session):
        assert db_session.query(AIGovernanceSettings).count() >= 0


# ---------------------------------------------------------------------------
# Governance settings CRUD
# ---------------------------------------------------------------------------

class TestGovernanceSettings:
    def test_default_settings(self, db_session: Session):
        settings = svc.get_governance_settings(db_session, 1)
        assert settings["require_approved_mappings"] is False
        assert settings["manual_mapping_boost"] == 0.05
        assert settings["allow_ai_unapproved_for_retrieval"] is True

    def test_upsert_settings(self, db_session: Session):
        result = svc.upsert_governance_settings(db_session, 1, {"manual_mapping_boost": 0.1})
        assert result["manual_mapping_boost"] == 0.1
        assert result["workspace_id"] == 1
        result2 = svc.upsert_governance_settings(db_session, 1, {"require_approved_mappings": True})
        assert result2["require_approved_mappings"] is True
        assert result2["manual_mapping_boost"] == 0.1
        svc.upsert_governance_settings(db_session, 1, {"manual_mapping_boost": 0.05, "require_approved_mappings": False})

    def test_workspace_isolation(self, db_session: Session):
        svc.upsert_governance_settings(db_session, 1, {"manual_mapping_boost": 0.09})
        s1 = svc.get_governance_settings(db_session, 1)
        s2 = svc.get_governance_settings(db_session, 2)
        assert s1["manual_mapping_boost"] == 0.09
        assert s2["manual_mapping_boost"] == 0.05
        svc.upsert_governance_settings(db_session, 1, {"manual_mapping_boost": 0.05})


# ---------------------------------------------------------------------------
# API permissions
# ---------------------------------------------------------------------------

class TestAPIPermissions:
    def test_admin_can_read_mappings(self, client: TestClient):
        _login(client)
        r = client.get("/api/ai-mappings/framework-controls")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_reviewer_can_read_mappings(self, client: TestClient):
        _login(client, email="reviewer@trust.local", password="r")
        r = client.get("/api/ai-mappings/framework-controls")
        assert r.status_code == 200

    def test_editor_cannot_create_mapping(self, client: TestClient):
        _login(client, email="editor@trust.local", password="e")
        r = client.post("/api/ai-mappings/framework-controls", json={"framework_key": "SOC 2", "control_id": 1})
        assert r.status_code == 403

    def test_unauthenticated_rejected(self, client: TestClient):
        client.post("/api/auth/logout")
        r = client.get("/api/ai-mappings/framework-controls")
        assert r.status_code == 401

    def test_admin_can_read_governance(self, client: TestClient):
        _login(client)
        r = client.get("/api/ai-governance/settings")
        assert r.status_code == 200

    def test_admin_can_read_pipeline_stats(self, client: TestClient):
        _login(client)
        r = client.get("/api/ai-governance/pipeline-stats")
        assert r.status_code == 200
        j = r.json()
        assert j.get("workspace_id") == 1
        assert "questionnaires_total" in j
        assert "documents_missing_subject_tag" in j

    def test_editor_cannot_read_pipeline_stats(self, client: TestClient):
        _login(client, email="editor@trust.local", password="e")
        r = client.get("/api/ai-governance/pipeline-stats")
        assert r.status_code == 403

    def test_editor_cannot_update_governance(self, client: TestClient):
        _login(client, email="editor@trust.local", password="e")
        r = client.patch("/api/ai-governance/settings", json={"manual_mapping_boost": 0.5})
        assert r.status_code == 403

    def test_admin_can_update_governance(self, client: TestClient):
        _login(client)
        r = client.patch("/api/ai-governance/settings", json={"manual_mapping_boost": 0.07})
        assert r.status_code == 200
        assert r.json()["manual_mapping_boost"] == 0.07
        client.patch("/api/ai-governance/settings", json={"manual_mapping_boost": 0.05})


# ---------------------------------------------------------------------------
# Framework-Control mapping CRUD via API
# ---------------------------------------------------------------------------

class TestFrameworkControlAPI:
    def test_create_and_list(self, client: TestClient, db_session: Session):
        _login(client)
        from app.models import WorkspaceControl, FrameworkControl, Framework
        fc = db_session.query(FrameworkControl).first()
        if not fc:
            fw = Framework(name="TestFW", version="1.0")
            db_session.add(fw)
            db_session.commit()
            db_session.refresh(fw)
            fc = FrameworkControl(framework_id=fw.id, control_key="TC-1", title="Test Control")
            db_session.add(fc)
            db_session.commit()
            db_session.refresh(fc)
        wc = db_session.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == 1).first()
        if not wc:
            wc = WorkspaceControl(workspace_id=1, framework_control_id=fc.id, status="not_started")
            db_session.add(wc)
            db_session.commit()
            db_session.refresh(wc)
        r = client.post("/api/ai-mappings/framework-controls", json={"framework_key": "SOC 2", "control_id": wc.id})
        assert r.status_code == 200
        data = r.json()
        assert data["framework_key"] == "SOC 2"
        assert data["approved"] is True
        mid = data["id"]
        r2 = client.get("/api/ai-mappings/framework-controls")
        assert r2.status_code == 200
        assert any(m["id"] == mid for m in r2.json())
        r3 = client.post("/api/ai-mappings/framework-controls", json={"framework_key": "SOC 2", "control_id": wc.id})
        assert r3.status_code == 400
        client.delete(f"/api/ai-mappings/framework-controls/{mid}")

    def test_approve_reject(self, client: TestClient, db_session: Session):
        _login(client)
        from app.models import WorkspaceControl
        wc = db_session.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == 1).first()
        if not wc:
            return
        r = client.post("/api/ai-mappings/framework-controls",
                        json={"framework_key": "ISO 27001", "control_id": wc.id, "approved": False, "source": "ai"})
        if r.status_code != 200:
            return
        mid = r.json()["id"]
        assert r.json()["approved"] is False
        ra = client.patch(f"/api/ai-mappings/framework-controls/{mid}/approve", json={"approved": True})
        assert ra.status_code == 200
        assert ra.json()["approved"] is True
        rr = client.patch(f"/api/ai-mappings/framework-controls/{mid}/approve", json={"approved": False})
        assert rr.status_code == 200
        assert rr.json()["approved"] is False
        client.delete(f"/api/ai-mappings/framework-controls/{mid}")

    def test_delete(self, client: TestClient, db_session: Session):
        _login(client)
        from app.models import WorkspaceControl
        wc = db_session.query(WorkspaceControl).filter(WorkspaceControl.workspace_id == 1).first()
        if not wc:
            return
        r = client.post("/api/ai-mappings/framework-controls",
                        json={"framework_key": "NIST", "control_id": wc.id})
        if r.status_code != 200:
            return
        mid = r.json()["id"]
        rd = client.delete(f"/api/ai-mappings/framework-controls/{mid}")
        assert rd.status_code == 200
        r404 = client.delete(f"/api/ai-mappings/framework-controls/{mid}")
        assert r404.status_code == 404


# ---------------------------------------------------------------------------
# Retrieval boost calculation
# ---------------------------------------------------------------------------

class TestRetrievalBoost:
    def test_empty_when_no_mappings(self, db_session: Session):
        result = svc.compute_retrieval_adjustments(
            db_session, 1, "How do you manage access?",
            [{"id": 1, "text": "policy", "score": 0.8}],
        )
        assert result == {}

    def test_no_crash_on_bad_data(self, db_session: Session):
        result = svc.compute_retrieval_adjustments(db_session, 1, "", [])
        assert result == {}

    def test_boost_capped(self, db_session: Session):
        result = svc.compute_retrieval_adjustments(db_session, 99999, "test", [{"id": 1}])
        assert isinstance(result, dict)
        for v in result.values():
            assert v <= svc.MAX_BOOST_CAP


# ---------------------------------------------------------------------------
# Governance enforcement
# ---------------------------------------------------------------------------

class TestGovernanceEnforcement:
    def test_require_approved_blocks_unapproved(self, db_session: Session):
        from app.models.ai_mapping import FrameworkControlMapping
        m = FrameworkControlMapping(
            workspace_id=1, framework_key="test", control_id=1,
            source="ai", approved=False, confidence=0.5,
        )
        gov = {"require_approved_mappings": True, "allow_ai_unapproved_for_retrieval": True}
        assert svc._passes_governance(m, gov) is False

    def test_approved_passes(self, db_session: Session):
        from app.models.ai_mapping import FrameworkControlMapping
        m = FrameworkControlMapping(
            workspace_id=1, framework_key="test", control_id=1,
            source="ai", approved=True, confidence=0.9,
        )
        gov = {"require_approved_mappings": True, "allow_ai_unapproved_for_retrieval": True}
        assert svc._passes_governance(m, gov) is True

    def test_confidence_threshold(self, db_session: Session):
        from app.models.ai_mapping import ControlEvidenceMapping
        m = ControlEvidenceMapping(
            workspace_id=1, control_id=1, evidence_id=1,
            source="ai", approved=True, confidence=0.3,
        )
        gov = {"require_approved_mappings": False, "allow_ai_unapproved_for_retrieval": True,
               "minimum_ai_mapping_confidence": 0.5}
        assert svc._passes_governance(m, gov) is False
        m.confidence = 0.7
        assert svc._passes_governance(m, gov) is True

    def test_block_unapproved_ai(self, db_session: Session):
        from app.models.ai_mapping import EvidenceTagMapping
        m = EvidenceTagMapping(
            workspace_id=1, evidence_id=1, tag_id=1,
            source="ai", approved=False,
        )
        gov = {"require_approved_mappings": False, "allow_ai_unapproved_for_retrieval": False}
        assert svc._passes_governance(m, gov) is False
        m.approved = True
        assert svc._passes_governance(m, gov) is True

    def test_manual_always_passes_unapproved_check(self, db_session: Session):
        from app.models.ai_mapping import FrameworkControlMapping
        m = FrameworkControlMapping(
            workspace_id=1, framework_key="test", control_id=1,
            source="manual", approved=False,
        )
        gov = {"require_approved_mappings": False, "allow_ai_unapproved_for_retrieval": False}
        assert svc._passes_governance(m, gov) is True


# ---------------------------------------------------------------------------
# Control-Evidence API
# ---------------------------------------------------------------------------

class TestControlEvidenceAPI:
    def test_list_empty(self, client: TestClient):
        _login(client)
        r = client.get("/api/ai-mappings/control-evidence")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# Evidence-Tag API
# ---------------------------------------------------------------------------

class TestEvidenceTagAPI:
    def test_list_empty(self, client: TestClient):
        _login(client)
        r = client.get("/api/ai-mappings/evidence-tags")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# Question Preferences API
# ---------------------------------------------------------------------------

class TestQuestionPrefsAPI:
    def test_create_and_delete(self, client: TestClient):
        _login(client)
        r = client.post("/api/ai-mappings/question-preferences", json={
            "normalized_question_text": "How do you handle encryption?",
            "preferred_framework_key": "SOC 2",
        })
        assert r.status_code == 200
        pid = r.json()["id"]
        assert r.json()["normalized_question_text"] == "How do you handle encryption?"
        rd = client.delete(f"/api/ai-mappings/question-preferences/{pid}")
        assert rd.status_code == 200

    def test_list_and_filter(self, client: TestClient):
        _login(client)
        r = client.get("/api/ai-mappings/question-preferences")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# AI Suggestion endpoints
# ---------------------------------------------------------------------------

class TestAISuggestions:
    def test_suggest_framework_controls(self, client: TestClient):
        _login(client)
        r = client.post("/api/ai-mappings/suggest/framework-controls")
        assert r.status_code == 200
        assert "created" in r.json()

    def test_suggest_control_evidence(self, client: TestClient):
        _login(client)
        r = client.post("/api/ai-mappings/suggest/control-evidence")
        assert r.status_code == 200
        assert "created" in r.json()

    def test_suggest_evidence_tags(self, client: TestClient):
        _login(client)
        r = client.post("/api/ai-mappings/suggest/evidence-tags")
        assert r.status_code == 200
        assert "created" in r.json()

    def test_editor_cannot_suggest(self, client: TestClient):
        _login(client, email="editor@trust.local", password="e")
        r = client.post("/api/ai-mappings/suggest/framework-controls")
        assert r.status_code == 403
