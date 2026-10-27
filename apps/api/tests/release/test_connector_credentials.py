"""TC-20-002 credential lifecycle. Probes are injected; no provider network."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import inspect, text

from app.core.idempotency import scoped_key, try_claim
from app.models.credential_store import CredentialStore
from app.models.user import User, WorkspaceMember
from app.models.workspace import Workspace
from app.services import credential_store_service as cs
from app.services.credential_lifecycle import probes
from app.services.credential_lifecycle.binding import CredentialBindingError
from app.services.credential_lifecycle.scopes import PROBES, least_privilege
from app.services.credential_lifecycle.service import connect, revoke, rotate, verify
from app.services.provider_adapter.contract import (
    ObservationState,
    ProvenanceKind,
    make_observation,
)
from app.services.provider_adapter.persistence import (
    CollectedEvidenceRejected,
    store_successful_observation,
)

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = API_ROOT / "alembic" / "versions" / "tc20002_connector_credentials.py"
PARENT = "tc24001_stripe_webhook_events"
HEAD = "tc20002_connector_credentials"

EXAMPLE_GITHUB = "test-example-github-value-aaaa"
EXAMPLE_GITHUB_NEXT = "test-example-github-value-bbbb"
EXAMPLE_SLACK = "test-example-slack-value-cccc"
EXAMPLE_GMAIL = "test-example-gmail-value-dddd"
EXAMPLE_AWS = "test-example-aws-value-eeee"
EXAMPLE_AWS_KEY = "EXAMPLEKEYTEST"
EXAMPLE_OTHER = "test-example-other-workspace-ffff"


def _workspace(db) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.id == 1).one()
    return ws


def _success_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "login": "example",
                "emailAddress": "person@example.com",
                "channels": [{"id": "Cexample", "name": "example"}],
                "labels": [{"id": "INBOX", "name": "INBOX"}],
                "users": [],
                "value": [{"id": "example"}],
                "results": [],
                "name": "Opportunity",
            },
        )

    return httpx.MockTransport(handler)


def _status_transport(status: int, body: dict):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler), seen


def _aws_factory(plan: dict):
    import boto3
    from botocore.stub import Stubber

    cache: dict = {}

    def factory(service: str):
        if service in cache:
            return cache[service]
        client = boto3.client(
            service,
            region_name="us-east-1",
            aws_access_key_id=EXAMPLE_AWS_KEY,
            aws_secret_access_key=EXAMPLE_AWS,
        )
        stubber = Stubber(client)
        for method, payload in plan.get(service, []):
            if isinstance(payload, dict) and "__error__" in payload:
                stubber.add_client_error(
                    method,
                    service_error_code=payload["__error__"],
                    service_message="example failure",
                    http_status_code=payload.get("status", 400),
                )
            else:
                stubber.add_response(method, payload)
        stubber.activate()
        cache[service] = client
        return client

    return factory


def _aws_ok():
    return _aws_factory(
        {
            "sts": [
                (
                    "get_caller_identity",
                    {
                        "UserId": "EXAMPLE",
                        "Account": "000000000000",
                        "Arn": "arn:aws:iam::000000000000:user/example",
                    },
                )
            ],
            "iam": [("get_account_summary", {"SummaryMap": {"Users": 1}})],
        }
    )


def _material(source: str) -> dict:
    base = {"secret": EXAMPLE_GITHUB}
    if source == "gcp":
        base["external_account_id"] = "example-project"
    elif source == "okta":
        base["external_account_id"] = "example.okta.test"
    elif source == "gitlab":
        base["base_url"] = "https://gitlab.example"
    elif source == "salesforce":
        base["base_url"] = "https://example.my.salesforce.com"
    elif source == "aws":
        base["secret"] = EXAMPLE_AWS
        base["access_key_id"] = EXAMPLE_AWS_KEY
    elif source == "slack":
        base["secret"] = EXAMPLE_SLACK
    elif source == "gmail":
        base["secret"] = EXAMPLE_GMAIL
    return base


HTTP_SOURCES = (
    "github",
    "google_workspace",
    "gcp",
    "azure",
    "gitlab",
    "okta",
    "salesforce",
    "hubspot",
)


class TestScopes:
    def test_every_connector_documents_verify_and_empty_revoke(self):
        for source, spec in PROBES.items():
            table = least_privilege(source)
            assert table["verify_scopes"] == list(spec.scopes)
            assert table["verify_calls"] == list(spec.calls)
            assert table["revoke_scopes"] == []
            assert table["revoke_calls"]
        assert least_privilege("google")["source_type"] == "google_workspace"
        assert "read:org" in least_privilege("github")["verify_scopes"]
        assert "Organization.Read.All" in least_privilege("azure")["verify_scopes"]
        assert PROBES["hris"].kind == "unsupported"


class TestBinding:
    def test_other_workspace_cannot_open(self):
        token = cs.encrypt(
            EXAMPLE_GITHUB,
            workspace_id=1,
            source_type="github",
            credential_type="personal_token",
        )
        assert EXAMPLE_GITHUB not in token
        with pytest.raises(CredentialBindingError):
            cs.decrypt(
                token,
                workspace_id=2,
                source_type="github",
                credential_type="personal_token",
            )
        with pytest.raises(CredentialBindingError):
            cs.decrypt(
                token,
                workspace_id=1,
                source_type="github",
                credential_type="other",
            )

    def test_legacy_fernet_rewraps_for_the_owning_workspace(self, db_session):
        ws = _workspace(db_session)
        legacy = cs._get_fernet().encrypt(EXAMPLE_GITHUB.encode()).decode()
        row = CredentialStore(
            workspace_id=ws.id,
            source_type="legacy_example",
            credential_type="personal_token",
            encrypted_value=legacy,
            status="active",
        )
        db_session.add(row)
        db_session.commit()
        with pytest.raises(CredentialBindingError):
            cs.decrypt(
                legacy,
                workspace_id=ws.id,
                source_type="legacy_example",
                credential_type="personal_token",
            )
        assert (
            cs.get_credential(db_session, ws.id, "legacy_example", "personal_token")
            == EXAMPLE_GITHUB
        )
        db_session.refresh(row)
        assert row.encrypted_value.startswith("tc20002:v1:")
        assert row.credential_ref.startswith("key-purpose:connector_encryption:v0:")


class TestProbes:
    def test_live_probe_disabled_does_not_open_a_socket(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise AssertionError("socket opened")

        monkeypatch.setattr(socket, "create_connection", boom)
        outcome = probes.probe_credential(
            "github",
            _material("github"),
            action="verify",
            workspace_id=1,
            credential_type="personal_token",
        )
        assert outcome.state == "failure"
        assert outcome.error_code == "live_probe_disabled"
        assert EXAMPLE_GITHUB not in json.dumps(outcome.observation)

    @pytest.mark.parametrize("source", HTTP_SOURCES)
    def test_http_success(self, source):
        outcome = probes.probe_credential(
            source,
            _material(source),
            action="verify",
            workspace_id=1,
            credential_type="personal_token",
            transport=_success_transport(),
        )
        assert outcome.state == "success"
        assert outcome.observation["provenance"]["kind"] == "credential_custody"
        assert outcome.observation["normalized_value"] == {"probe": "read_only", "action": "verify"}
        assert EXAMPLE_GITHUB not in json.dumps(outcome.observation)

    @pytest.mark.parametrize(
        ("status", "body", "state", "code"),
        [
            (401, {"error": "expired example"}, "failure", "credential_expired"),
            (401, {"error": "revoked example"}, "failure", "credential_revoked"),
            (403, {"error": "example denied"}, "missing_permission", "missing_permission"),
            (500, {"error": "example"}, "failure", "provider_failure"),
        ],
    )
    def test_http_classification(self, status, body, state, code):
        transport, seen = _status_transport(status, body)
        outcome = probes.probe_credential(
            "github",
            _material("github"),
            action="verify",
            workspace_id=1,
            credential_type="personal_token",
            transport=transport,
        )
        assert outcome.state == state
        assert outcome.error_code == code
        assert seen
        for request in seen:
            assert EXAMPLE_GITHUB not in str(request.url)
            assert request.headers["authorization"].startswith("Bearer ")

    def test_provider_body_echo_is_not_copied(self):
        transport, _seen = _status_transport(401, {"error": "revoked", "echo": EXAMPLE_GITHUB})
        outcome = probes.probe_credential(
            "github",
            _material("github"),
            action="verify",
            workspace_id=1,
            credential_type="personal_token",
            transport=transport,
        )
        blob = json.dumps(outcome.observation)
        assert EXAMPLE_GITHUB not in blob
        assert "echo" not in blob

    def test_gcp_missing_account_skips_http(self):
        called = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            called["n"] += 1
            return httpx.Response(200, json={})

        outcome = probes.probe_credential(
            "gcp",
            {"secret": EXAMPLE_GITHUB},
            action="verify",
            workspace_id=1,
            credential_type="oauth_token",
            transport=httpx.MockTransport(handler),
        )
        assert called["n"] == 0
        assert outcome.error_code == "missing_credentials"

    def test_hris_is_unsupported_and_does_not_call(self):
        called = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            called["n"] += 1
            return httpx.Response(200, json={})

        outcome = probes.probe_credential(
            "hris",
            {"secret": EXAMPLE_GITHUB},
            action="verify",
            workspace_id=1,
            credential_type="api_token",
            transport=httpx.MockTransport(handler),
        )
        assert called["n"] == 0
        assert outcome.state == "unsupported"
        assert outcome.error_code == "vendor_not_selected"

    def test_aws_stubber_matrix(self):
        ok = probes.probe_credential(
            "aws",
            _material("aws"),
            action="connect",
            workspace_id=1,
            credential_type="access_key",
            aws_factory=_aws_ok(),
        )
        assert ok.state == "success"
        cases = [
            ("AccessDenied", 403, "missing_permission", "missing_permission"),
            ("ExpiredToken", 400, "failure", "credential_expired"),
            ("InvalidClientTokenId", 403, "failure", "credential_revoked"),
            ("InternalError", 500, "failure", "provider_failure"),
        ]
        for error, status, state, code in cases:
            factory = _aws_factory(
                {"sts": [("get_caller_identity", {"__error__": error, "status": status})]}
            )
            outcome = probes.probe_credential(
                "aws",
                _material("aws"),
                action="verify",
                workspace_id=1,
                credential_type="access_key",
                aws_factory=factory,
            )
            assert outcome.state == state, error
            assert outcome.error_code == code, error
            assert EXAMPLE_AWS not in json.dumps(outcome.observation)

    @pytest.mark.parametrize(
        ("source", "token", "body", "state", "code"),
        [
            (
                "slack",
                EXAMPLE_SLACK,
                {"ok": True, "channels": [{"id": "C1", "name": "example"}]},
                "success",
                None,
            ),
            (
                "slack",
                EXAMPLE_SLACK,
                {"ok": False, "error": "missing_scope"},
                "missing_permission",
                "missing_permission",
            ),
            (
                "slack",
                EXAMPLE_SLACK,
                {"ok": False, "error": "token_expired"},
                "failure",
                "credential_expired",
            ),
            (
                "slack",
                EXAMPLE_SLACK,
                {"ok": False, "error": "token_revoked"},
                "failure",
                "credential_revoked",
            ),
            (
                "gmail",
                EXAMPLE_GMAIL,
                {
                    "emailAddress": "person@example.com",
                    "labels": [{"id": "INBOX", "name": "INBOX"}],
                },
                "success",
                None,
            ),
            (
                "gmail",
                EXAMPLE_GMAIL,
                {"error": {"status": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}},
                "missing_permission",
                "missing_permission",
            ),
            (
                "gmail",
                EXAMPLE_GMAIL,
                {"error": {"status": "token_expired"}},
                "failure",
                "credential_expired",
            ),
        ],
    )
    def test_slack_and_gmail_use_http_providers(self, source, token, body, state, code):
        def handler(request: httpx.Request) -> httpx.Response:
            assert token not in str(request.url)
            status = 200 if body.get("ok") is not False and "error" not in body else 401
            if body.get("error") == "missing_scope" or (
                isinstance(body.get("error"), dict)
                and body["error"].get("status") == "ACCESS_TOKEN_SCOPE_INSUFFICIENT"
            ):
                status = 403
            return httpx.Response(status, json=body)

        outcome = probes.probe_credential(
            source,
            {"secret": token},
            action="verify",
            workspace_id=1,
            credential_type="bot_token" if source == "slack" else "oauth_token",
            transport=httpx.MockTransport(handler),
        )
        assert outcome.state == state
        assert outcome.error_code == code
        assert token not in json.dumps(outcome.observation)

    def test_slack_provider_failure(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"ok": False})

        outcome = probes.probe_credential(
            "slack",
            {"secret": EXAMPLE_SLACK},
            action="verify",
            workspace_id=1,
            credential_type="bot_token",
            transport=httpx.MockTransport(handler),
        )
        assert outcome.state == "failure"
        assert outcome.error_code == "provider_failure"


class TestLifecycle:
    def test_connect_verify_rotate_revoke(self, db_session):
        ws = _workspace(db_session)
        transport = _success_transport()
        connected = connect(
            db_session,
            ws.id,
            "github",
            "personal_token",
            EXAMPLE_GITHUB,
            transport=transport,
        )
        db_session.commit()
        assert connected["status"] == "active"
        assert connected["secret_last4"] == EXAMPLE_GITHUB[-4:]
        assert EXAMPLE_GITHUB not in json.dumps(connected)
        assert cs.get_credential(db_session, ws.id, "github", "personal_token") == EXAMPLE_GITHUB

        checked = verify(
            db_session,
            ws.id,
            source_type="github",
            credential_type="personal_token",
            transport=transport,
        )
        assert checked["observation"]["state"] == "success"

        failed = rotate(
            db_session,
            ws.id,
            EXAMPLE_GITHUB_NEXT,
            source_type="github",
            credential_type="personal_token",
            transport=_status_transport(403, {"error": "example"})[0],
        )
        db_session.commit()
        assert failed["observation"]["state"] == "missing_permission"
        assert cs.get_credential(db_session, ws.id, "github", "personal_token") == EXAMPLE_GITHUB

        rotated = rotate(
            db_session,
            ws.id,
            EXAMPLE_GITHUB_NEXT,
            source_type="github",
            credential_type="personal_token",
            transport=transport,
        )
        db_session.commit()
        assert rotated["observation"]["state"] == "success"
        assert (
            cs.get_credential(db_session, ws.id, "github", "personal_token") == EXAMPLE_GITHUB_NEXT
        )

        destroyed = revoke(
            db_session,
            ws.id,
            source_type="github",
            credential_type="personal_token",
        )
        db_session.commit()
        assert destroyed["status"] == "revoked"
        assert destroyed["secret_last4"] is None
        row = db_session.query(CredentialStore).filter(CredentialStore.id == destroyed["id"]).one()
        assert row.encrypted_value == "destroyed"
        assert cs.get_credential(db_session, ws.id, "github", "personal_token") is None
        assert EXAMPLE_GITHUB_NEXT not in json.dumps(destroyed)

    def test_rotate_flush_failure_keeps_the_previous_secret(self, db_session, monkeypatch):
        ws = _workspace(db_session)
        connect(
            db_session,
            ws.id,
            "hubspot",
            "private_app_token",
            EXAMPLE_GITHUB,
            transport=_success_transport(),
        )
        db_session.commit()

        def boom(*_args, **_kwargs):
            raise RuntimeError("example flush failure")

        monkeypatch.setattr(db_session, "flush", boom)
        with pytest.raises(RuntimeError):
            rotate(
                db_session,
                ws.id,
                EXAMPLE_GITHUB_NEXT,
                source_type="hubspot",
                credential_type="private_app_token",
                transport=_success_transport(),
            )
        db_session.rollback()
        assert (
            cs.get_credential(db_session, ws.id, "hubspot", "private_app_token") == EXAMPLE_GITHUB
        )

    def test_idempotent_rotate_replays_without_a_second_write(self, db_session):
        ws = _workspace(db_session)
        connect(
            db_session,
            ws.id,
            "azure",
            "oauth_token",
            EXAMPLE_GITHUB,
            transport=_success_transport(),
        )
        db_session.commit()
        key = scoped_key(
            ws.id,
            "credentials.rotate",
            "azure:oauth_token",
            f"example-rotate-{uuid.uuid4().hex}",
        )
        first = rotate(
            db_session,
            ws.id,
            EXAMPLE_GITHUB_NEXT,
            source_type="azure",
            credential_type="oauth_token",
            idempotency_key=key,
            transport=_success_transport(),
        )
        assert first["secret_last4"] == EXAMPLE_GITHUB_NEXT[-4:]
        second = rotate(
            db_session,
            ws.id,
            "test-example-should-not-apply-zzzz",
            source_type="azure",
            credential_type="oauth_token",
            idempotency_key=key,
            transport=_success_transport(),
        )
        assert second == first
        assert cs.get_credential(db_session, ws.id, "azure", "oauth_token") == EXAMPLE_GITHUB_NEXT
        stored = db_session.execute(
            text("SELECT response_body FROM idempotency_keys WHERE idempotency_key = :k"),
            {"k": key},
        ).scalar()
        assert EXAMPLE_GITHUB_NEXT not in stored
        assert "test-example-should-not-apply-zzzz" not in stored

    def test_in_progress_claim_does_not_rotate(self, db_session):
        ws = _workspace(db_session)
        connect(
            db_session,
            ws.id,
            "okta",
            "api_token",
            EXAMPLE_GITHUB,
            extra={"external_account_id": "example.okta.test"},
            transport=_success_transport(),
        )
        db_session.commit()
        key = scoped_key(ws.id, "okta.rotate", "okta:api_token", f"example-busy-{uuid.uuid4().hex}")
        assert try_claim(db_session, key)
        with pytest.raises(Exception) as caught:
            rotate(
                db_session,
                ws.id,
                EXAMPLE_GITHUB_NEXT,
                source_type="okta",
                credential_type="api_token",
                extra={"external_account_id": "example.okta.test"},
                idempotency_key=key,
                transport=_success_transport(),
            )
        assert "in progress" in str(caught.value).lower()
        assert cs.get_credential(db_session, ws.id, "okta", "api_token") == EXAMPLE_GITHUB

    def test_probe_success_is_not_collected_evidence(self, db_session):
        ws = _workspace(db_session)
        observation, _connection = make_observation(
            provider="github",
            resource_id="credential-probe:github:verify",
            state=ObservationState.SUCCESS,
            provenance_kind=ProvenanceKind.CREDENTIAL_CUSTODY,
            workspace_id=ws.id,
            credential_type="personal_token",
            normalized_value={"probe": "read_only", "action": "verify"},
        )
        with pytest.raises(CollectedEvidenceRejected) as caught:
            store_successful_observation(db_session, ws.id, observation)
        assert caught.value.code == "not_evidence"


class TestApi:
    @pytest.fixture
    def admin_client(self, client):
        client.cookies.clear()
        response = client.post(
            "/api/auth/login", json={"email": "admin@trust.local", "password": "a"}
        )
        assert response.status_code == 200
        return client

    @pytest.mark.parametrize(
        "path",
        [
            "/api/credentials/connect",
            "/api/connectors/aws/connect",
            "/api/connectors/github/connect",
            "/api/connectors/google/connect",
            "/api/connectors/cloud/gcp/connect",
            "/api/crm/salesforce/connect",
            "/api/crm/hubspot/connect",
            "/api/connector-wizard/connect",
        ],
    )
    def test_connect_requires_a_value(self, admin_client, path):
        body = {"value": "  "}
        if path.endswith("/credentials/connect"):
            body["source_type"] = "github"
        if "wizard" in path:
            body["connector_type"] = "github"
        response = admin_client.post(path, json=body)
        assert response.status_code == 400

    def test_testing_mode_does_not_store_or_echo(self, admin_client):
        response = admin_client.post(
            "/api/connectors/github/connect",
            json={"value": EXAMPLE_GITHUB},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "not_stored"
        assert payload["observation"]["error_code"] == "live_probe_disabled"
        assert EXAMPLE_GITHUB not in response.text

    def test_cross_workspace_is_not_found_either_way(self, admin_client, db_session):
        ws = _workspace(db_session)
        other = db_session.query(Workspace).filter(Workspace.id == 2).one()
        own = cs.store_credential(db_session, ws.id, "gitlab", "personal_token", EXAMPLE_GITHUB)
        theirs = cs.store_credential(
            db_session, other.id, "gitlab", "personal_token", EXAMPLE_OTHER
        )
        db_session.commit()
        missing = admin_client.get(f"/api/credentials/{theirs['id']}")
        assert missing.status_code == 404
        assert missing.json()["detail"] == "Credential not found"
        listed = admin_client.get("/api/credentials").json()["credentials"]
        assert all(item["id"] != theirs["id"] for item in listed)
        assert all(item.get("secret_last4") != EXAMPLE_OTHER[-4:] for item in listed)
        health = admin_client.get("/api/connector-health")
        assert health.status_code == 200
        assert "credential_custody" in health.json()
        assert EXAMPLE_OTHER not in health.text
        assert EXAMPLE_GITHUB not in health.text

        admin = db_session.query(User).filter(User.email == "admin@trust.local").one()
        membership = (
            db_session.query(WorkspaceMember)
            .filter(
                WorkspaceMember.user_id == admin.id,
                WorkspaceMember.workspace_id == other.id,
            )
            .first()
        )
        created = membership is None
        if created:
            db_session.add(WorkspaceMember(workspace_id=other.id, user_id=admin.id, role="admin"))
            db_session.commit()
        try:
            switched = admin_client.post(
                "/api/auth/switch-workspace", json={"workspace_id": other.id}
            )
            assert switched.status_code == 200, switched.text
            hidden = admin_client.get(f"/api/credentials/{own['id']}")
            assert hidden.status_code == 404
            assert hidden.json()["detail"] == "Credential not found"
            other_list = admin_client.get("/api/credentials").json()["credentials"]
            assert all(item["id"] != own["id"] for item in other_list)
            assert all(item.get("secret_last4") != EXAMPLE_GITHUB[-4:] for item in other_list)
            assert EXAMPLE_GITHUB not in json.dumps(other_list)
        finally:
            if created:
                db_session.query(WorkspaceMember).filter(
                    WorkspaceMember.user_id == admin.id,
                    WorkspaceMember.workspace_id == other.id,
                ).delete()
                db_session.commit()

    def test_wizard_stays_disabled_until_the_probe_succeeds(self, admin_client, db_session):
        db_session.query(CredentialStore).filter(
            CredentialStore.workspace_id == 1,
            CredentialStore.source_type == "gmail",
        ).delete()
        db_session.commit()
        started = admin_client.post("/api/connector-wizard/start", json={"connector_type": "gmail"})
        if started.status_code == 400:
            admin_client.post("/api/connector-wizard/disable", json={"connector_type": "gmail"})
            started = admin_client.post(
                "/api/connector-wizard/start", json={"connector_type": "gmail"}
            )
        assert started.status_code == 200, started.text
        blocked = admin_client.post(
            "/api/connector-wizard/validate", json={"connector_type": "gmail"}
        )
        assert blocked.status_code == 200
        assert blocked.json()["enabled"] is False
        assert blocked.json()["probe"]["state"] == "missing_permission"
        assert "error" not in blocked.json()
        ws = _workspace(db_session)
        cs.store_credential(db_session, ws.id, "gmail", "oauth_token", EXAMPLE_GMAIL)
        db_session.commit()
        with probes.probe_overrides(transport=_success_transport()):
            enabled = admin_client.post(
                "/api/connector-wizard/validate", json={"connector_type": "gmail"}
            )
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["enabled"] is True
        assert enabled.json()["status"] == "validated"
        assert EXAMPLE_GMAIL not in enabled.text

    def test_rotate_route_conflict_and_replay(self, admin_client, db_session):
        ws = _workspace(db_session)
        connect_key = f"example-connect-{uuid.uuid4().hex}"
        busy_key = f"example-busy-{uuid.uuid4().hex}"
        with probes.probe_overrides(transport=_success_transport()):
            created = admin_client.post(
                "/api/credentials/connect",
                json={
                    "source_type": "salesforce",
                    "credential_type": "oauth_token",
                    "value": EXAMPLE_GITHUB,
                    "base_url": "https://example.my.salesforce.com",
                },
                headers={"Idempotency-Key": connect_key},
            )
        assert created.status_code == 200, created.text
        cred_id = created.json()["id"]
        key = scoped_key(ws.id, "credentials.rotate", str(cred_id), busy_key)
        assert try_claim(db_session, key)
        busy = admin_client.post(
            f"/api/credentials/{cred_id}/rotate",
            json={
                "value": EXAMPLE_GITHUB_NEXT,
                "base_url": "https://example.my.salesforce.com",
            },
            headers={"Idempotency-Key": busy_key},
        )
        assert busy.status_code == 409
        assert EXAMPLE_GITHUB_NEXT not in busy.text
        assert cs.get_credential(db_session, ws.id, "salesforce", "oauth_token") == EXAMPLE_GITHUB


class TestMigration:
    def test_revision_is_frozen_and_the_only_head(self):
        source = MIGRATION.read_text(encoding="utf-8")
        assert "import app" not in source
        assert "from app" not in source
        assert "alembic_version" not in source
        assert len(HEAD) <= 32
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(API_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
        script = ScriptDirectory.from_config(cfg)
        assert script.get_heads() == [HEAD]
        revision = script.get_revision(HEAD)
        assert revision is not None
        assert revision.down_revision == PARENT

    def test_upgrade_and_downgrade(self):
        url = os.environ.get("TC_TEST_DATABASE_URL") or os.environ["DATABASE_URL"]
        env = {**os.environ, "DATABASE_URL": url, "TRUST_COPILOT_TESTING": "1"}

        def alembic(*args: str) -> None:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                cwd=str(API_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            assert result.returncode == 0, result.stderr

        from sqlalchemy import create_engine

        engine = create_engine(url)
        try:
            alembic("downgrade", PARENT)
            columns = {column["name"] for column in inspect(engine).get_columns("credential_store")}
            assert "secret_fingerprint" not in columns
            alembic("upgrade", "head")
            columns = {column["name"] for column in inspect(engine).get_columns("credential_store")}
            assert "secret_fingerprint" in columns
            assert "destroyed_at" in columns
            with engine.connect() as conn:
                assert (
                    conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD
                )
        finally:
            alembic("upgrade", "head")
            engine.dispose()
