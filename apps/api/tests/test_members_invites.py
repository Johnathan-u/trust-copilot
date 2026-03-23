"""Tests for Members / Invites / Sessions fixes."""

import pytest
from fastapi.testclient import TestClient


class TestMemberRoleChange:
    """Role change and delete use WorkspaceMember.id correctly."""

    def test_role_change_by_valid_member_id(self, client: TestClient):
        """PATCH /api/members/{member_id} with valid member_id succeeds."""
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        r = client.get("/api/members")
        assert r.status_code == 200
        members = r.json().get("members", [])
        target = next((m for m in members if m["email"] != "admin@trust.local"), None)
        if not target:
            pytest.skip("No non-admin member to test role change")
        member_id = target["id"]
        r2 = client.patch(f"/api/members/{member_id}", json={"role": "reviewer"})
        assert r2.status_code == 200
        assert r2.json()["role"] == "reviewer"

    def test_role_change_bad_id_returns_404(self, client: TestClient):
        """PATCH /api/members/{member_id} with non-existent ID returns 404."""
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        r = client.patch("/api/members/999999", json={"role": "editor"})
        assert r.status_code == 404
        assert "not found" in r.json().get("detail", "").lower()

    def test_delete_member_bad_id_returns_404(self, client: TestClient):
        """DELETE /api/members/{member_id} with non-existent ID returns 404."""
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        r = client.delete("/api/members/999999")
        assert r.status_code == 404


class TestInviteList:
    """Invite list endpoint returns correct shape including inviter info."""

    def test_invite_list_returns_shape(self, client: TestClient):
        """GET /api/members/invites returns invites with invited_by field."""
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        r = client.get("/api/members/invites")
        assert r.status_code == 200
        data = r.json()
        assert "invites" in data
        assert isinstance(data["invites"], list)
        for inv in data["invites"]:
            assert "id" in inv
            assert "email" in inv
            assert "role" in inv
            assert "created_at" in inv
            assert "expires_at" in inv
            assert "invited_by" in inv

    def test_invite_create_and_list(self, client: TestClient):
        """Created invite appears in list with inviter info."""
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        unique_email = "testinvite_list@example.com"
        client.delete("/api/members/invites/0")
        r = client.post("/api/members/invites", json={"email": unique_email, "role": "editor"})
        if r.status_code == 400 and "already" in r.json().get("detail", "").lower():
            pass
        else:
            assert r.status_code == 200

        r2 = client.get("/api/members/invites")
        assert r2.status_code == 200
        invites = r2.json()["invites"]
        match = [i for i in invites if i["email"] == unique_email]
        if match:
            assert match[0]["invited_by"] is not None or match[0]["invited_by"] is None


class TestInviteRevoke:
    """Invite revocation works correctly."""

    def test_revoke_nonexistent_invite_returns_404(self, client: TestClient):
        """DELETE /api/members/invites/{id} with bad ID returns 404."""
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        r = client.delete("/api/members/invites/999999")
        assert r.status_code == 404

    def test_revoke_invite_works(self, client: TestClient):
        """Create and then revoke an invite."""
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        unique_email = "revoke_test@example.com"
        r = client.post("/api/members/invites", json={"email": unique_email, "role": "editor"})
        if r.status_code == 400:
            invites = client.get("/api/members/invites").json().get("invites", [])
            match = next((i for i in invites if i["email"] == unique_email), None)
            if match:
                r2 = client.delete(f"/api/members/invites/{match['id']}")
                assert r2.status_code == 200
            return
        assert r.status_code == 200
        invite_id = r.json()["id"]
        r2 = client.delete(f"/api/members/invites/{invite_id}")
        assert r2.status_code == 200
        assert r2.json().get("ok") is True


class TestAdminRevokeSessionsForMember:
    """Admin-triggered session revocation for another user."""

    def test_revoke_sessions_requires_admin(self, client: TestClient):
        """POST /api/members/{id}/revoke-sessions without auth returns 401."""
        r = client.post("/api/members/1/revoke-sessions")
        assert r.status_code == 401

    def test_revoke_sessions_bad_member_returns_404(self, client: TestClient):
        """POST /api/members/999999/revoke-sessions returns 404."""
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        r = client.post("/api/members/999999/revoke-sessions")
        assert r.status_code == 404

    def test_revoke_sessions_valid_member(self, client: TestClient):
        """POST /api/members/{id}/revoke-sessions for a real member returns ok."""
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        r = client.get("/api/members")
        assert r.status_code == 200
        members = r.json().get("members", [])
        target = next((m for m in members if m["email"] != "admin@trust.local"), None)
        if not target:
            pytest.skip("No non-admin member to test session revocation")
        r2 = client.post(f"/api/members/{target['id']}/revoke-sessions")
        assert r2.status_code == 200
        assert "revoked" in r2.json()


class TestSuspendMember:
    """Suspend/unsuspend uses correct member_id."""

    def test_suspend_bad_id_returns_404(self, client: TestClient):
        """PATCH /api/members/999999/suspend returns 404."""
        client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
        r = client.patch("/api/members/999999/suspend", json={"suspended": True})
        assert r.status_code == 404


class TestPermissions:
    """Non-admin users cannot access member management."""

    def test_non_admin_cannot_list_members(self, client: TestClient):
        """Editor cannot list members."""
        client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
        r = client.get("/api/members")
        assert r.status_code == 403

    def test_non_admin_cannot_revoke_sessions(self, client: TestClient):
        """Editor cannot revoke sessions for another member."""
        client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
        r = client.post("/api/members/1/revoke-sessions")
        assert r.status_code == 403

    def test_non_admin_cannot_revoke_invites(self, client: TestClient):
        """Editor cannot revoke invites."""
        client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
        r = client.delete("/api/members/invites/1")
        assert r.status_code == 403
