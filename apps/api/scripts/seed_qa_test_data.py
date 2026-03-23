"""
Seed data for QA test sheet (docs/QA_TEST_SHEET.md).

Creates:
- Two workspaces (1 = Default, 2 = QA Workspace B)
- Users: admin, editor, reviewer, suspended, and demo (admin in ws1, editor in ws2)
- Per workspace: documents, questionnaires + questions + answers, controls + evidence,
  trust articles (published + unpublished), trust requests, vendor requests,
  custom role, notification policies, audit events

Slack/Gmail: Not seeded (require real OAuth). Connect manually for those checks.

Run from apps/api: python scripts/seed_qa_test_data.py
Requires: Postgres running (e.g. docker compose up -d postgres). Optional: MinIO for document storage;
if MinIO is down, documents are still created with placeholder keys so lists and controls seed correctly.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from dotenv import load_dotenv
load_dotenv(API_ROOT / ".env")

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import (
    Answer,
    AuditEvent,
    Control,
    ControlEvidence,
    CustomRole,
    Document,
    NotificationPolicy,
    Question,
    Questionnaire,
    TrustArticle,
    TrustRequest,
    User,
    VendorRequest,
    Workspace,
    WorkspaceMember,
)
from app.services.file_service import make_key
from app.services.storage import StorageClient
from app.services.xlsx_questionnaire_parser import parse_xlsx_questionnaire

DEMO_EMAIL = "demo@trust.local"
DEMO_PASSWORD = "j"
ADMIN_EMAIL = "admin@trust.local"
ADMIN_PASSWORD = "Admin123!"
EDITOR_EMAIL = "editor@trust.local"
EDITOR_PASSWORD = "Editor123!"
REVIEWER_EMAIL = "reviewer@trust.local"
REVIEWER_PASSWORD = "Reviewer123!"
SUSPENDED_EMAIL = "suspended@trust.local"
SUSPENDED_PASSWORD = "Suspended123!"

WORKSPACE_1_ID = 1
WORKSPACE_2_ID = 2
FIXTURE_XLSX = API_ROOT / "tests" / "fixtures" / "questionnaires" / "simple_soc2.xlsx"


def ensure_user(db: Session, email: str, password: str, display_name: str) -> User:
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"  Created user: {email}")
    return user


def ensure_workspace(db: Session, id: int, name: str, slug: str) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.id == id).first()
    if not ws:
        ws = Workspace(id=id, name=name, slug=slug)
        db.add(ws)
        db.commit()
        db.refresh(ws)
        print(f"  Created workspace: {name} (id={id})")
    return ws


def ensure_member(db: Session, user_id: int, workspace_id: int, role: str, suspended: bool = False) -> None:
    m = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.workspace_id == workspace_id,
    ).first()
    if not m:
        m = WorkspaceMember(
            user_id=user_id,
            workspace_id=workspace_id,
            role=role,
            suspended=suspended,
        )
        db.add(m)
        db.commit()
        print(f"  Added member to workspace {workspace_id} as {role}" + (" (suspended)" if suspended else ""))
    else:
        m.role = role
        m.suspended = suspended
        db.commit()


def seed_users_and_workspaces(db: Session) -> tuple[User, User, User, User, User]:
    ensure_workspace(db, WORKSPACE_1_ID, "Default", "default")
    ensure_workspace(db, WORKSPACE_2_ID, "QA Workspace B", "qa-workspace-b")

    admin_u = ensure_user(db, ADMIN_EMAIL, ADMIN_PASSWORD, "Admin")
    editor_u = ensure_user(db, EDITOR_EMAIL, EDITOR_PASSWORD, "Editor")
    reviewer_u = ensure_user(db, REVIEWER_EMAIL, REVIEWER_PASSWORD, "Reviewer")
    suspended_u = ensure_user(db, SUSPENDED_EMAIL, SUSPENDED_PASSWORD, "Suspended")
    demo_u = ensure_user(db, DEMO_EMAIL, DEMO_PASSWORD, "Demo User")

    ensure_member(db, admin_u.id, WORKSPACE_1_ID, "admin")
    ensure_member(db, editor_u.id, WORKSPACE_1_ID, "editor")
    ensure_member(db, reviewer_u.id, WORKSPACE_1_ID, "reviewer")
    ensure_member(db, suspended_u.id, WORKSPACE_1_ID, "reviewer", suspended=True)
    ensure_member(db, demo_u.id, WORKSPACE_1_ID, "admin")
    ensure_member(db, demo_u.id, WORKSPACE_2_ID, "editor")

    return admin_u, editor_u, reviewer_u, suspended_u, demo_u


def seed_documents(db: Session, storage: StorageClient | None, workspace_id: int, prefix: str) -> list[Document]:
    docs = []
    for i, (name, content, ctype) in enumerate([
        (f"{prefix}_evidence_1.txt", f"Evidence document 1 for workspace {workspace_id}.", "text/plain"),
        (f"{prefix}_evidence_2.txt", f"Evidence document 2 for workspace {workspace_id}.", "text/plain"),
    ]):
        existing = db.query(Document).filter(
            Document.workspace_id == workspace_id,
            Document.filename == name,
        ).first()
        if existing:
            docs.append(existing)
            continue
        key = make_key(workspace_id, "raw", name)
        if storage:
            try:
                storage.upload(storage.bucket_raw, key, content.encode("utf-8"), content_type=ctype)
            except Exception:
                pass
        doc = Document(
            workspace_id=workspace_id,
            storage_key=key,
            filename=name,
            content_type=ctype,
            status="indexed" if i == 0 else "uploaded",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        docs.append(doc)
    return docs


def seed_questionnaires(db: Session, storage: StorageClient | None, workspace_id: int, prefix: str) -> list[Questionnaire]:
    qnrs = []
    if not FIXTURE_XLSX.exists():
        q = Questionnaire(
            workspace_id=workspace_id,
            storage_key=make_key(workspace_id, "raw", f"{prefix}_qnr.xlsx"),
            filename=f"{prefix}_questionnaire.xlsx",
            status="parsed",
            parse_metadata=json.dumps({"source": "seed", "question_count": 3}),
        )
        db.add(q)
        db.commit()
        db.refresh(q)
        for i, text in enumerate(["Question A?", "Question B?", "Question C?"], 1):
            qu = Question(questionnaire_id=q.id, text=text, section="Seed", source_location=json.dumps({}), confidence=90)
            db.add(qu)
        db.commit()
        qnrs.append(q)
        return qnrs

    questions_data = parse_xlsx_questionnaire(FIXTURE_XLSX)
    xlsx_content = FIXTURE_XLSX.read_bytes()
    for idx in range(2):
        name = f"{prefix}_soc2_{idx + 1}.xlsx"
        key = make_key(workspace_id, "raw", name)
        if storage:
            try:
                storage.upload(storage.bucket_raw, key, xlsx_content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            except Exception:
                pass
        existing = db.query(Questionnaire).filter(
            Questionnaire.workspace_id == workspace_id,
            Questionnaire.filename == name,
        ).first()
        if existing:
            qnrs.append(existing)
            continue
        qnr = Questionnaire(
            workspace_id=workspace_id,
            storage_key=key,
            filename=name,
            status="parsed",
            parse_metadata=json.dumps({"source": "seed", "question_count": len(questions_data)}),
        )
        db.add(qnr)
        db.commit()
        db.refresh(qnr)
        for qd in questions_data[:10]:
            sl = qd.get("source_location")
            sl_json = json.dumps(sl) if isinstance(sl, dict) else (sl or "{}")
            q = Question(
                questionnaire_id=qnr.id,
                text=qd["text"],
                section=qd.get("section"),
                answer_type=qd.get("answer_type"),
                source_location=sl_json,
                confidence=qd.get("confidence"),
            )
            db.add(q)
        db.commit()
        qnrs.append(qnr)
    return qnrs


def seed_answers(db: Session, questionnaire: Questionnaire) -> None:
    questions = db.query(Question).filter(Question.questionnaire_id == questionnaire.id).all()
    for i, qu in enumerate(questions[:5]):
        if db.query(Answer).filter(Answer.question_id == qu.id).first():
            continue
        a = Answer(
            question_id=qu.id,
            text=f"Seed answer for question {i + 1}.",
            status="approved" if i % 2 == 0 else "draft",
            confidence=85,
        )
        db.add(a)
    db.commit()


def seed_controls_and_evidence(db: Session, workspace_id: int, documents: list[Document], prefix: str) -> list[Control]:
    controls = []
    for i, (fw, cid, name, status) in enumerate([
        (f"{prefix} SOC2", "CC6.1", "Logical access", "implemented"),
        (f"{prefix} SOC2", "CC6.2", "Access removal", "in_review"),
        (f"{prefix} ISO27001", "A.9.2.1", "Registration", "implemented"),
    ]):
        c = db.query(Control).filter(
            Control.workspace_id == workspace_id,
            Control.framework == fw,
            Control.control_id == cid,
        ).first()
        if not c:
            c = Control(workspace_id=workspace_id, framework=fw, control_id=cid, name=name, status=status)
            db.add(c)
            db.commit()
            db.refresh(c)
        controls.append(c)

    if documents and controls:
        ce = db.query(ControlEvidence).filter(
            ControlEvidence.control_id == controls[0].id,
            ControlEvidence.document_id == documents[0].id,
        ).first()
        if not ce:
            db.add(ControlEvidence(control_id=controls[0].id, document_id=documents[0].id))
            db.commit()
    return controls


def seed_trust_articles(db: Session, workspace_id: int, prefix: str) -> None:
    for slug, title, published in [
        (f"{prefix}-published", f"{prefix} Published Article", True),
        (f"{prefix}-draft", f"{prefix} Unpublished Article", False),
    ]:
        if db.query(TrustArticle).filter(TrustArticle.workspace_id == workspace_id, TrustArticle.slug == slug).first():
            continue
        db.add(TrustArticle(
            workspace_id=workspace_id,
            slug=slug,
            title=title,
            content=f"Content for {title}.",
            published=1 if published else 0,
            category="Security",
        ))
    db.commit()


def seed_trust_requests(db: Session, workspace_id: int, assignee_id: int | None) -> None:
    if db.query(TrustRequest).filter(TrustRequest.workspace_id == workspace_id).first():
        return
    db.add(TrustRequest(
        workspace_id=workspace_id,
        assignee_id=assignee_id,
        requester_email="requester@example.com",
        requester_name="QA Requester",
        subject="SOC 2 questionnaire",
        message="Please share your SOC 2 report.",
        status="in_progress",
    ))
    db.commit()


def seed_vendor_requests(db: Session, workspace_id: int, questionnaire_id: int | None) -> None:
    if db.query(VendorRequest).filter(VendorRequest.workspace_id == workspace_id).first():
        return
    db.add(VendorRequest(
        workspace_id=workspace_id,
        vendor_email="vendor@example.com",
        questionnaire_id=questionnaire_id,
        status="sent",
    ))
    db.commit()


def seed_custom_role(db: Session, workspace_id: int, name: str) -> CustomRole:
    r = db.query(CustomRole).filter(CustomRole.workspace_id == workspace_id, CustomRole.name == name).first()
    if r:
        return r
    r = CustomRole(
        workspace_id=workspace_id,
        name=name,
        description="QA custom role",
        can_edit=True,
        can_review=True,
        can_export=False,
        can_admin=False,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def seed_notification_policies(db: Session, workspace_id: int, prefix: str) -> None:
    for event_type in ["member.invited", "export.completed"]:
        if db.query(NotificationPolicy).filter(
            NotificationPolicy.workspace_id == workspace_id,
            NotificationPolicy.event_type == event_type,
        ).first():
            continue
        db.add(NotificationPolicy(
            workspace_id=workspace_id,
            event_type=event_type,
            enabled=True,
            recipient_type="admins",
            recipient_value=None,
        ))
    db.commit()


def seed_audit_events(db: Session, workspace_id: int, user_id: int, email: str) -> None:
    actions = [
        "auth.login",
        "auth.workspace_switch",
        "notification.policy_created",
        "role.created",
        "member.invited",
    ]
    base = datetime.now(timezone.utc) - timedelta(hours=2)
    for i, action in enumerate(actions):
        ev = AuditEvent(
            action=action,
            user_id=user_id,
            email=email,
            workspace_id=workspace_id,
            resource_type=None,
            resource_id=None,
            details=json.dumps({"seed": True, "idx": i}),
        )
        ev.occurred_at = base + timedelta(minutes=i * 15)
        db.add(ev)
    db.commit()


def main() -> None:
    print("QA seed starting...", flush=True)
    db = SessionLocal()
    storage = None
    try:
        storage = StorageClient()
        storage.ensure_buckets()
    except Exception as e:
        print("MinIO/S3 not available; documents will use placeholder keys:", e, flush=True)

    try:
        print("Seeding users and workspaces...", flush=True)
        admin_u, editor_u, reviewer_u, suspended_u, demo_u = seed_users_and_workspaces(db)

        for ws_id, prefix in [(WORKSPACE_1_ID, "ws1"), (WORKSPACE_2_ID, "ws2")]:
            print(f"\nSeeding workspace {ws_id} ({prefix})...")
            docs = seed_documents(db, storage, ws_id, prefix)
            print(f"  Documents: {len(docs)}")
            qnrs = seed_questionnaires(db, storage, ws_id, prefix)
            print(f"  Questionnaires: {len(qnrs)}")
            for qnr in qnrs:
                seed_answers(db, qnr)
            controls = seed_controls_and_evidence(db, ws_id, docs, prefix)
            print(f"  Controls: {len(controls)}")
            seed_trust_articles(db, ws_id, prefix)
            seed_trust_requests(db, ws_id, admin_u.id)
            seed_vendor_requests(db, ws_id, qnrs[0].id if qnrs else None)
            seed_custom_role(db, ws_id, "qa-custom")
            seed_notification_policies(db, ws_id, prefix)
            seed_audit_events(db, ws_id, admin_u.id, admin_u.email)
            print(f"  Audit events: 5")

        print("\n--- QA test accounts ---", flush=True)
        print(f"  Admin:    {ADMIN_EMAIL} / {ADMIN_PASSWORD}", flush=True)
        print(f"  Editor:   {EDITOR_EMAIL} / {EDITOR_PASSWORD}", flush=True)
        print(f"  Reviewer: {REVIEWER_EMAIL} / {REVIEWER_PASSWORD}", flush=True)
        print(f"  Suspended:{SUSPENDED_EMAIL} / {SUSPENDED_PASSWORD} (blocked from app)", flush=True)
        print(f"  Demo:     {DEMO_EMAIL} / {DEMO_PASSWORD} (admin in Workspace 1, editor in Workspace 2)", flush=True)
        print("---", flush=True)
        print("Slack/Gmail: Connect manually in the app for those QA checks.", flush=True)
        print("QA seed complete.", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
