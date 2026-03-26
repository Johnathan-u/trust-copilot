"""Tests for AWS connector (P1-17, P1-18, P1-19, P1-20, P1-21)."""

import pytest
from app.models.workspace import Workspace
from app.services import aws_collector_service as aws


@pytest.fixture
def admin_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "admin@trust.local", "password": "a"})
    assert r.status_code == 200
    return client


@pytest.fixture
def editor_client(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "editor@trust.local", "password": "e"})
    assert r.status_code == 200
    return client


class TestAwsCollectorService:
    def test_authenticate_missing_creds(self):
        result = aws.authenticate_aws()
        assert result["authenticated"] is False

    def test_authenticate_with_creds(self):
        result = aws.authenticate_aws("AKID123", "secret123")
        assert result["authenticated"] is True
        assert result["method"] == "access_key"

    def test_authenticate_with_role(self):
        result = aws.authenticate_aws("AKID123", "secret123", role_arn="arn:aws:iam::role/test")
        assert result["method"] == "assume_role"

    def test_collect_iam(self):
        result = aws.collect_iam_posture()
        assert result["source"] == "aws.iam"
        assert len(result["findings"]) >= 3

    def test_collect_s3(self):
        result = aws.collect_s3_posture()
        assert result["source"] == "aws.s3"
        assert len(result["findings"]) >= 3

    def test_collect_logging(self):
        result = aws.collect_logging_posture()
        assert result["source"] == "aws.cloudtrail"

    def test_run_sync(self, db_session):
        ws = db_session.query(Workspace).first()
        result = aws.run_aws_sync(db_session, ws.id)
        assert result["total_findings"] >= 8
        assert "aws.iam" in result["sources_checked"]


class TestAwsConnectorAPI:
    def test_iam(self, admin_client):
        r = admin_client.get("/api/connectors/aws/iam")
        assert r.status_code == 200
        assert r.json()["source"] == "aws.iam"

    def test_s3(self, admin_client):
        r = admin_client.get("/api/connectors/aws/s3")
        assert r.status_code == 200

    def test_logging(self, admin_client):
        r = admin_client.get("/api/connectors/aws/logging")
        assert r.status_code == 200

    def test_sync(self, admin_client):
        r = admin_client.post("/api/connectors/aws/sync")
        assert r.status_code == 200
        assert r.json()["total_findings"] >= 8

    def test_editor_cannot_sync(self, editor_client):
        r = editor_client.post("/api/connectors/aws/sync")
        assert r.status_code == 403
