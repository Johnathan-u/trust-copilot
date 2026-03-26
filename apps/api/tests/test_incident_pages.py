"""Tests for incident/status/vulnerability disclosure pages (P2-100)."""

import pytest
from app.services import incident_page_service as ips


class TestIncidentPageService:
    def test_system_status(self):
        result = ips.get_system_status()
        assert result["status"] == "operational"
        assert len(result["components"]) >= 5

    def test_vulnerability_disclosure(self):
        result = ips.get_vulnerability_disclosure()
        assert result["program_type"] == "Responsible Disclosure"
        assert result["safe_harbor"] is True

    def test_report_vulnerability(self):
        result = ips.report_vulnerability("Test", "test@test.com", "XSS found", "high")
        assert result["status"] == "received"
        assert result["reference_id"].startswith("VD-")


class TestIncidentPagesAPI:
    def test_status_public(self, client):
        r = client.get("/api/status")
        assert r.status_code == 200
        assert r.json()["status"] == "operational"

    def test_disclosure_public(self, client):
        r = client.get("/api/status/vulnerability-disclosure")
        assert r.status_code == 200
        assert "scope" in r.json()

    def test_report_public(self, client):
        r = client.post("/api/status/vulnerability-report", json={
            "reporter_name": "Bug Hunter",
            "reporter_email": "hunter@test.com",
            "description": "Found XSS",
            "severity": "medium",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "received"
