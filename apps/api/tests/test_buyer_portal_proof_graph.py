"""Buyer portal (E4) and proof graph (E5) API tests."""

import pytest

from app.models.workspace import Workspace
from app.services import buyer_portal_service as bps
from app.services import golden_answer_service as ga
from app.services import proof_graph_service as pgs


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


class TestBuyerPortalService:
    def test_match_questions_finds_golden(self, db_session):
        ws = db_session.query(Workspace).first()
        ga.create_golden_answer(
            db_session,
            ws.id,
            "Do you enforce MFA for all users?",
            "Yes, MFA is required for all accounts.",
            confidence=0.9,
        )
        db_session.commit()
        out = bps.match_questions(
            db_session, ws.id, ["What about multi-factor authentication for users?"]
        )
        assert len(out) == 1
        assert out[0]["golden_answer_id"] is not None
        assert out[0]["need_seller_review"] is False

    def test_snapshots_and_change_summary(self, db_session):
        ws = db_session.query(Workspace).first()
        p = bps.create_portal(db_session, ws.id, "Test Portal")
        db_session.commit()
        portal = bps.get_portal_by_token(db_session, p["portal_token"])
        bps.capture_snapshot(db_session, portal)
        bps.capture_snapshot(db_session, portal)
        db_session.commit()
        summary = bps.get_latest_change_summary(db_session, portal)
        assert summary is not None
        assert "deltas" in summary


class TestBuyerPortalAPI:
    def test_public_manifest_and_instant_match(self, admin_client):
        gr = admin_client.post(
            "/api/golden-answers",
            json={
                "question_text": "SOC 2 Type II audit scope question",
                "answer_text": "Annual audit covers prod.",
                "confidence": 0.95,
            },
            headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
        )
        assert gr.status_code == 200
        r = admin_client.post(
            "/api/buyer-portal/portals",
            json={"display_name": "Acme Review"},
            headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
        )
        assert r.status_code == 200
        token = r.json()["portal_token"]

        m = admin_client.get(f"/public/buyer-portal/{token}/manifest")
        assert m.status_code == 200
        assert m.json()["features"]["instant_questionnaire_match"] is True

        im = admin_client.post(
            f"/public/buyer-portal/{token}/instant-match",
            json={"questions": ["SOC 2 Type II audit scope question"]},
        )
        assert im.status_code == 200
        matches = im.json()["matches"]
        assert len(matches) == 1
        assert matches[0]["golden_answer_id"] is not None
        assert matches[0]["answer_text"] == "Annual audit covers prod."

    def test_escalation_and_satisfaction(self, admin_client, db_session):
        r = admin_client.post(
            "/api/buyer-portal/portals",
            json={"display_name": "Esc Portal"},
            headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
        )
        assert r.status_code == 200
        token = r.json()["portal_token"]

        er = admin_client.post(
            f"/public/buyer-portal/{token}/escalations",
            json={
                "buyer_email": "buyer@co.com",
                "escalation_type": "insufficient_evidence",
                "message": "Need pen test report",
            },
        )
        assert er.status_code == 200
        eid = er.json()["id"]

        sr = admin_client.post(
            f"/public/buyer-portal/{token}/satisfaction",
            json={
                "accepted_without_edits": True,
                "follow_up_count": 0,
                "cycle_hours": 12.5,
                "deal_closed": True,
            },
        )
        assert sr.status_code == 200

        lst = admin_client.get(
            "/api/buyer-portal/escalations",
            headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
        )
        assert lst.status_code == 200
        ids = [x["id"] for x in lst.json()["escalations"]]
        assert eid in ids

        pr = admin_client.patch(
            f"/api/buyer-portal/escalations/{eid}",
            json={"status": "resolved", "seller_notes": "Sent link"},
            headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
        )
        assert pr.status_code == 200
        assert pr.json()["status"] == "resolved"


class TestProofGraphAPI:
    def test_sync_chain_freshness_hash_diff_reuse(self, admin_client):
        gr = admin_client.post(
            "/api/golden-answers",
            json={"question_text": "Q graph unique xyz", "answer_text": "A graph"},
            headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
        )
        assert gr.status_code == 200

        sr = admin_client.post(
            "/api/proof-graph/sync",
            headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
        )
        assert sr.status_code == 200
        assert sr.json()["nodes"] >= 1

        nodes = admin_client.get(
            "/api/proof-graph/nodes",
            params={"node_type": "golden_answer", "limit": 50},
        ).json()["nodes"]
        gnode = next(
            (n for n in nodes if n.get("node_type") == "golden_answer"),
            None,
        )
        assert gnode
        fr = admin_client.get(f"/api/proof-graph/freshness/node/{gnode['id']}")
        assert fr.status_code == 200
        assert fr.json()["freshness"] in ("live", "recent", "aging", "stale")

        hr = admin_client.post(
            "/api/proof-graph/artifacts/hash",
            json={
                "artifact_kind": "evidence_item",
                "artifact_id": 1,
                "content_text": "hello proof",
            },
            headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
        )
        assert hr.status_code == 200

        vr = admin_client.post(
            "/api/proof-graph/artifacts/verify",
            json={
                "artifact_kind": "evidence_item",
                "artifact_id": 1,
                "content_text": "hello proof",
            },
        )
        assert vr.status_code == 200
        assert vr.json()["ok"] is True

        dr = admin_client.get("/api/proof-graph/diffs")
        assert dr.status_code == 200
        assert len(dr.json()["diffs"]) >= 1

        rr = admin_client.post(
            "/api/proof-graph/reuse-provenance",
            json={"answer_id": 42, "buyer_ref": "buyer@x.com", "evidence_ids": [1, 2]},
            headers={"Origin": "http://localhost", "Referer": "http://localhost/"},
        )
        assert rr.status_code == 200

        lr = admin_client.get("/api/proof-graph/reuse-provenance/answer/42")
        assert lr.status_code == 200
        assert len(lr.json()["instances"]) >= 1
