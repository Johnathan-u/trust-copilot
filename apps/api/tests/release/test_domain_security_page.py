"""TC-17-003: owner-approved, evidence-backed public security claims.

Synthetic data only, with exact row cleanup. Runs on the real PostgreSQL test
database through the HTTP API and the service, covering success, denial,
foreign references, partial failure (proof withdrawn) and restart/retry.
"""

import secrets

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.session import sign_session
from app.models import (
    AuditEvent,
    EvidenceItem,
    SecurityClaim,
    User,
    UserSession,
    Workspace,
    WorkspaceMember,
)
from app.services import security_page_service as sp

TABLES = (
    "workspaces",
    "users",
    "workspace_members",
    "user_sessions",
    "security_claims",
    "evidence_items",
    "audit_events",
)


@pytest.fixture
def domain(client, db_session):
    before = {t: db_session.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in TABLES}
    suffix = secrets.token_hex(8)
    ids = [700_000_000 + secrets.randbelow(100_000_000) for _ in range(2)]
    db_session.add_all(
        [Workspace(id=i, slug=f"claims-{suffix}-{i}", name="Synthetic claims") for i in ids]
    )
    actors = {}
    for role in ("admin", "reviewer", "editor"):
        user = User(
            email=f"claims-{suffix}-{role}@example.com",
            password_hash="unused-synthetic",
            display_name="Claims test",
        )
        db_session.add(user)
        db_session.flush()
        db_session.add(WorkspaceMember(workspace_id=ids[0], user_id=user.id, role=role))
        db_session.add(UserSession(user_id=user.id, session_id=f"claims-{suffix}-{role}"))
        actors[role] = user.id
    approved = EvidenceItem(
        workspace_id=ids[0],
        source_type="manual",
        title=f"SOC 2 report {suffix}",
        approval_status="approved",
    )
    pending = EvidenceItem(
        workspace_id=ids[0],
        source_type="manual",
        title=f"Draft policy {suffix}",
        approval_status="pending",
    )
    foreign = EvidenceItem(
        workspace_id=ids[1],
        source_type="manual",
        title=f"Foreign report {suffix}",
        approval_status="approved",
    )
    db_session.add_all([approved, pending, foreign])
    db_session.commit()
    state = {
        "client": client,
        "db": db_session,
        "ws": ids[0],
        "foreign_ws": ids[1],
        "actors": actors,
        "approved": approved.id,
        "pending": pending.id,
        "foreign": foreign.id,
    }

    def login(role="admin"):
        client.cookies.clear()
        client.cookies.set(
            "tc_session",
            sign_session(
                actors[role],
                f"claims-{suffix}-{role}@example.com",
                ids[0],
                role,
                session_id=f"claims-{suffix}-{role}",
                max_age_seconds=3600,
            ),
        )

    state["login"] = login
    login()
    yield state
    client.cookies.clear()
    db_session.rollback()
    db_session.query(AuditEvent).filter(AuditEvent.workspace_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(SecurityClaim).filter(SecurityClaim.workspace_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(EvidenceItem).filter(EvidenceItem.workspace_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(WorkspaceMember).filter(WorkspaceMember.workspace_id.in_(ids)).delete(
        synchronize_session=False
    )
    db_session.query(UserSession).filter(UserSession.user_id.in_(actors.values())).delete(
        synchronize_session=False
    )
    db_session.query(User).filter(User.id.in_(actors.values())).delete(synchronize_session=False)
    db_session.query(Workspace).filter(Workspace.id.in_(ids)).delete(synchronize_session=False)
    db_session.commit()
    after = {t: db_session.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in TABLES}
    assert after == before


def _put(d, key, **body):
    body.setdefault("expected_revision", 0)
    return d["client"].put(f"/api/security-page/claims/{key}", json=body)


def _page(d):
    r = d["client"].get("/api/security-page")
    assert r.status_code == 200, r.text
    return r.json()


def _cert(page, name):
    return next(c for c in page["certifications"] if c["name"] == name)


def _claim(page, key):
    return next(c for c in page["claims"] if c["key"] == key)


def test_default_page_asserts_nothing(domain):
    page = _page(domain)
    assert page["schema_version"] == 2
    assert {c["status"] for c in page["certifications"]} == {"not_attested"}
    assert all(c["proof"] is None for c in page["certifications"])
    assert page["contact"] == {
        "security_email": None,
        "dpa_available": False,
        "subprocessor_list_available": False,
    }
    deployment = [h for h in page["infrastructure_highlights"] if "AES" in h or "TLS" in h]
    assert deployment and all(
        h.startswith("Deployment-dependent, not yet verified") for h in deployment
    )
    assert {c["key"] for c in page["claims"]} == set(sp.CATALOGUE)
    assert not any(c["verified"] for c in page["claims"])


def test_no_hardcoded_contact_or_attestation_in_service_source():
    source = open(sp.__file__, encoding="utf-8").read()
    assert "@trustcopilot.io" not in source


def test_owner_approved_claim_with_proof_is_attested(domain):
    r = _put(
        domain,
        "soc2_type2",
        status="claimed",
        statement="SOC 2 Type II report, period 2026",
        evidence_item_id=domain["approved"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True and r.json()["revision"] == 1
    cert = _cert(_page(domain), "SOC 2 Type II")
    assert cert["status"] == "attested"
    assert cert["description"] == "SOC 2 Type II report, period 2026"
    assert cert["proof"]["evidence_item_id"] == domain["approved"]
    row = (
        domain["db"]
        .query(SecurityClaim)
        .filter_by(workspace_id=domain["ws"], claim_key="soc2_type2")
        .one()
    )
    assert row.decided_by_user_id == domain["actors"]["admin"] and row.decided_at is not None
    audit = (
        domain["db"]
        .query(AuditEvent)
        .filter_by(
            workspace_id=domain["ws"], resource_type="security_claim", resource_id="soc2_type2"
        )
        .all()
    )
    assert [a.action for a in audit] == ["security_claim.claimed"]


def test_infrastructure_claim_replaces_unverified_wording(domain):
    r = _put(
        domain,
        "encryption_at_rest",
        status="claimed",
        statement="AES-256 encryption at rest (managed Postgres and object storage)",
        evidence_item_id=domain["approved"],
    )
    assert r.status_code == 200, r.text
    highlights = _page(domain)["infrastructure_highlights"]
    assert "AES-256 encryption at rest (managed Postgres and object storage)" in highlights
    assert not any(
        h.endswith("AES-256 encryption at rest") and "not yet verified" in h for h in highlights
    )


def test_security_contact_is_owner_configured(domain):
    bad = _put(domain, "security_contact", status="claimed", value="not-an-email")
    assert bad.status_code == 422
    ok = _put(domain, "security_contact", status="claimed", value="security@example.com")
    assert ok.status_code == 200, ok.text
    assert _page(domain)["contact"]["security_email"] == "security@example.com"


@pytest.mark.parametrize("which", ["foreign", "pending", "missing"])
def test_unusable_proof_is_rejected_identically(domain, which):
    evidence = {"foreign": domain["foreign"], "pending": domain["pending"], "missing": 2147483000}[
        which
    ]
    r = _put(domain, "iso27001", status="claimed", evidence_item_id=evidence)
    assert r.status_code == 422
    assert r.json()["detail"] == "That evidence is not available as approved proof"
    assert domain["db"].query(SecurityClaim).filter_by(workspace_id=domain["ws"]).count() == 0
    assert _cert(_page(domain), "ISO 27001")["status"] == "not_attested"


def test_claim_without_proof_is_rejected(domain):
    r = _put(domain, "gdpr", status="claimed")
    assert r.status_code == 422
    assert domain["db"].query(SecurityClaim).filter_by(workspace_id=domain["ws"]).count() == 0


def test_unknown_claim_key_is_not_found(domain):
    assert (
        _put(domain, "pci_dss", status="claimed", evidence_item_id=domain["approved"]).status_code
        == 404
    )


@pytest.mark.parametrize("role", ["editor", "reviewer"])
def test_only_admins_decide_or_list_claims(domain, role):
    domain["login"](role)
    assert domain["client"].get("/api/security-page/claims").status_code == 403
    r = _put(domain, "soc2_type2", status="claimed", evidence_item_id=domain["approved"])
    assert r.status_code == 403
    assert domain["db"].query(SecurityClaim).filter_by(workspace_id=domain["ws"]).count() == 0
    assert _page(domain)["title"] == "Security & Data Handling"


def test_unauthenticated_requests_are_refused(domain):
    domain["client"].cookies.clear()
    assert domain["client"].get("/api/security-page").status_code == 401
    assert domain["client"].get("/api/security-page/claims").status_code == 401


def test_idempotent_retry_and_stale_conflict(domain):
    body = dict(status="claimed", evidence_item_id=domain["approved"])
    first = _put(domain, "backups", **body)
    retry = _put(domain, "backups", **body)
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json() and retry.json()["revision"] == 1
    stale = _put(domain, "backups", status="not_claimed")
    assert stale.status_code == 409
    withdrawn = _put(domain, "backups", status="not_claimed", expected_revision=1)
    assert withdrawn.status_code == 200 and withdrawn.json()["revision"] == 2
    assert withdrawn.json()["verified"] is False
    rows = (
        domain["db"]
        .query(SecurityClaim)
        .filter_by(workspace_id=domain["ws"], claim_key="backups")
        .all()
    )
    assert len(rows) == 1 and rows[0].revision == 2 and rows[0].evidence_item_id is None


def test_proof_withdrawn_later_falls_back_without_deleting_decision(domain):
    assert (
        _put(
            domain, "soc2_type2", status="claimed", evidence_item_id=domain["approved"]
        ).status_code
        == 200
    )
    db = domain["db"]
    db.execute(
        text("UPDATE evidence_items SET approval_status = 'rejected' WHERE id = :id"),
        {"id": domain["approved"]},
    )
    db.commit()
    page = _page(domain)
    assert _cert(page, "SOC 2 Type II")["status"] == "not_attested"
    assert _claim(page, "soc2_type2")["reason"] == "proof_unavailable"
    db.execute(text("DELETE FROM evidence_items WHERE id = :id"), {"id": domain["approved"]})
    db.commit()
    row = db.query(SecurityClaim).filter_by(workspace_id=domain["ws"], claim_key="soc2_type2").one()
    db.refresh(row)
    assert row.status == "claimed" and row.evidence_item_id is None
    assert _cert(_page(domain), "SOC 2 Type II")["status"] == "not_attested"


def test_claims_never_leak_across_workspaces(domain):
    assert (
        _put(domain, "iso27001", status="claimed", evidence_item_id=domain["approved"]).status_code
        == 200
    )
    foreign_page = sp.get_public_security_page(domain["db"], domain["foreign_ws"])
    assert _cert(foreign_page, "ISO 27001")["status"] == "not_attested"
    domain["db"].add(
        SecurityClaim(
            workspace_id=domain["ws"],
            claim_key="gdpr",
            status="claimed",
            evidence_item_id=domain["foreign"],
            decided_at=sp.datetime.now(sp.timezone.utc),
        )
    )
    domain["db"].commit()
    assert _claim(_page(domain), "gdpr")["reason"] == "proof_unavailable"


def test_api_service_and_fresh_session_agree_after_restart(domain):
    assert (
        _put(domain, "dpa", status="claimed", evidence_item_id=domain["approved"]).status_code
        == 200
    )
    api_page = _page(domain)
    fresh = Session(bind=domain["db"].get_bind())
    try:
        assert sp.get_public_security_page(fresh, domain["ws"]) == api_page
    finally:
        fresh.close()
    assert api_page["contact"]["dpa_available"] is True
    listed = domain["client"].get("/api/security-page/claims").json()["claims"]
    dpa = next(c for c in listed if c["key"] == "dpa")
    assert dpa["revision"] == 1 and dpa["evidence_item_id"] == domain["approved"]


def test_database_guards(domain):
    db = domain["db"]
    db.add(SecurityClaim(workspace_id=domain["ws"], claim_key="soc2_type2", status="bogus"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(SecurityClaim(workspace_id=domain["ws"], claim_key="soc2_type2", status="claimed"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add_all(
        [
            SecurityClaim(workspace_id=domain["ws"], claim_key="gdpr"),
            SecurityClaim(workspace_id=domain["ws"], claim_key="gdpr"),
        ]
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_schema_matches_migration(db_session):
    insp = inspect(db_session.get_bind())
    cols = {c["name"] for c in insp.get_columns("security_claims")}
    assert {
        "workspace_id",
        "claim_key",
        "status",
        "statement",
        "value",
        "evidence_item_id",
        "decided_by_user_id",
        "decided_at",
        "revision",
        "updated_at",
    } <= cols
    uniques = {u["name"] for u in insp.get_unique_constraints("security_claims")}
    assert "uq_security_claims_workspace_key" in uniques
    checks = {c["name"] for c in insp.get_check_constraints("security_claims")}
    assert {
        "ck_security_claims_status",
        "ck_security_claims_revision",
        "ck_security_claims_claimed_decided",
    } <= checks
