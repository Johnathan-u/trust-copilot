"""
Seed a demo workspace with:
- Sample questionnaire (from simple_soc2.xlsx fixture)
- Sample evidence document (minimal placeholder)
- Trust articles (a few published)

Run from apps/api: python -m scripts.seed_demo_workspace
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure apps/api is on path so app imports work
API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# Load apps/api/.env so DATABASE_URL and S3_* are set when run from apps/api
from dotenv import load_dotenv
load_dotenv(API_ROOT / ".env")

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import Document, Question, Questionnaire, TrustArticle, User, Workspace, WorkspaceMember
from app.services.file_service import make_key
from app.services.storage import StorageClient
from app.services.xlsx_questionnaire_parser import parse_xlsx_questionnaire

DEMO_EMAIL = "demo@trust.local"
DEMO_PASSWORD = "j"
ADMIN_EMAIL = "admin@trust.local"
ADMIN_PASSWORD = "Admin123!"
DEFAULT_WORKSPACE_ID = 1
FIXTURE_XLSX = API_ROOT / "tests" / "fixtures" / "questionnaires" / "simple_soc2.xlsx"


def seed_demo_user(db: Session) -> None:
    """Create demo user and workspace membership if not present (AUTH-201 seed)."""
    user = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if not user:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name="Demo User",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Created demo user: {user.email} (id={user.id})")
    existing = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == DEFAULT_WORKSPACE_ID,
    ).first()
    if not existing:
        db.add(WorkspaceMember(
            user_id=user.id,
            workspace_id=DEFAULT_WORKSPACE_ID,
            role="editor",
        ))
        db.commit()
        print(f"Added demo user to workspace {DEFAULT_WORKSPACE_ID}")
    elif existing.role != "editor":
        # E2E and local demos assume demo can edit (bulk selection, uploads). Reset if DB was tweaked.
        existing.role = "editor"
        db.commit()
        print(f"Reset demo user role to editor in workspace {DEFAULT_WORKSPACE_ID}")


def seed_admin_user(db: Session) -> None:
    """Create admin user for Trust Center and full dashboard access. Credentials printed at end."""
    user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    if not user:
        user = User(
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            display_name="Admin",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Created admin user: {user.email} (id={user.id})")
    mem = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == DEFAULT_WORKSPACE_ID,
    ).first()
    if not mem:
        db.add(WorkspaceMember(user_id=user.id, workspace_id=DEFAULT_WORKSPACE_ID, role="admin"))
        db.commit()
        print("Added admin to workspace 1 as admin role.")
    else:
        mem.role = "admin"
        db.commit()
        print("Admin already in workspace 1 (role=admin).")
    print("")
    print("--- Admin login credentials ---")
    print(f"  Email:    {ADMIN_EMAIL}")
    print(f"  Password: {ADMIN_PASSWORD}")
    print("  Use these to sign in at /login and access Trust Center, Settings, Members, etc.")
    print("---")


TRUST_ARTICLES = [
    {
        "slug": "demo-security-overview",
        "title": "Security Overview",
        "category": "Security Overview",
        "content": """## Our commitment to security

This Trust Center is where we share how we protect your data and maintain a secure, reliable platform. We believe transparency builds trust—so we publish our security practices, compliance posture, and privacy approach here for customers, prospects, and auditors.

### Security program

Our organization maintains a **comprehensive security program** aligned with industry best practices and recognized frameworks. We focus on:

- **Infrastructure security** — Production systems run in trusted cloud environments with encryption, network controls, and continuous monitoring.
- **Access control** — Role-based access, strong authentication (including MFA where appropriate), and least-privilege principles.
- **Secure development** — Secure SDLC practices, code review, and dependency management to reduce risk in our products.
- **Incident response** — Documented procedures and a dedicated team to detect, contain, and communicate security incidents.

### Availability and reliability

We design for availability and resilience. Our services are built to meet committed uptime targets, with redundancy, backups, and tested recovery procedures so your data and workflows stay available when you need them.

### Questions or need more detail?

Use **Request trust information** on this page to ask for specific documentation (e.g., security questionnaires, penetration test summaries, or compliance reports). We respond to legitimate requests from customers and prospects as part of our trust program.""",
    },
    {
        "slug": "demo-compliance-soc2",
        "title": "SOC 2 Compliance",
        "category": "SOC 2",
        "content": """## SOC 2 Type II certification

We have achieved **SOC 2 Type II** certification and undergo annual audits conducted by an independent third party. This demonstrates that our security, availability, and confidentiality controls are not only designed appropriately but **operate effectively** over time.

### What is SOC 2?

SOC 2 (Service Organization Control 2) is a framework developed by the AICPA. It focuses on five trust service criteria: Security, Availability, Processing Integrity, Confidentiality, and Privacy. Our report addresses the criteria relevant to the services we provide to customers.

- **Type I** — A point-in-time assessment of the design of controls.
- **Type II** — An assessment over a period (e.g., 12 months) of whether those controls operated effectively.

We maintain a **Type II** report so you can rely on both design and operating effectiveness.

### Audit cycle and scope

We complete a full SOC 2 Type II audit annually. The report covers our production environment, access management, change management, risk assessment, and other areas specified in the scope. The audit is performed by a qualified CPA firm.

### How to request our report

Many customers and prospects request a copy of our latest SOC 2 report as part of their vendor or security review. To request the report (under NDA where required), use **Request trust information** on this page. We’ll respond with instructions or the report according to our sharing policy.""",
    },
    {
        "slug": "demo-data-privacy",
        "title": "Data Privacy",
        "category": "Data Privacy",
        "content": """## How we handle personal data

We process personal data in accordance with **applicable privacy regulations** (including GDPR, CCPA, and other laws where we operate) and our published **Privacy Policy**. This page summarizes our approach so you can understand how we treat data in our systems.

### Principles we follow

- **Lawfulness and purpose** — We collect and use personal data only where we have a lawful basis and for clear, stated purposes (e.g., providing our services, supporting your account, improving our product).
- **Minimization and retention** — We limit collection to what is necessary and retain data only as long as needed for those purposes or to meet legal obligations.
- **Security** — We protect personal data with technical and organizational measures consistent with our [Security Overview](/trust) and compliance programs.
- **Rights** — We support data subject rights (access, correction, deletion, portability, objection, and restriction) as required by applicable law.

### Roles and responsibilities

Where we act as a **processor** (e.g., processing data on your behalf when you use our product), we do so under our Data Processing Agreement (DPA) and only in line with your instructions. Where we act as a **controller** (e.g., for account and billing data), we describe our practices in our Privacy Policy.

### Subprocessors and international transfers

We use a limited set of subprocessors for infrastructure and service operations. We maintain a list of subprocessors and use appropriate safeguards (including Standard Contractual Clauses where relevant) for international transfers of personal data.

### Questions or a DPA

To request our DPA, subprocessor list, or other privacy-related documentation, use **Request trust information** on this page. We’re here to support your compliance and procurement reviews.""",
    },
]


def seed_demo_workspace(db: Session, storage: StorageClient) -> Workspace:
    """Seed default workspace (id=1) with questionnaire, document, trust articles."""
    ws = db.query(Workspace).filter(Workspace.id == DEFAULT_WORKSPACE_ID).first()
    if not ws:
        raise RuntimeError(f"Workspace id={DEFAULT_WORKSPACE_ID} not found. Run migrations first.")
    print(f"Seeding workspace: {ws.name} (id={ws.id})")

    if not FIXTURE_XLSX.exists():
        raise FileNotFoundError(f"Fixture not found: {FIXTURE_XLSX}")
    questions_data = parse_xlsx_questionnaire(FIXTURE_XLSX)
    xlsx_content = FIXTURE_XLSX.read_bytes()
    key = make_key(ws.id, "raw", "simple_soc2.xlsx")
    storage.upload(storage.bucket_raw, key, xlsx_content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    qnr = Questionnaire(workspace_id=ws.id, storage_key=key, filename="simple_soc2.xlsx", status="parsed", parse_metadata=json.dumps({"source": "seed", "question_count": len(questions_data)}))
    db.add(qnr)
    db.commit()
    db.refresh(qnr)
    for qd in questions_data:
        sl = qd.get("source_location")
        sl_json = json.dumps(sl) if isinstance(sl, dict) else sl
        q = Question(questionnaire_id=qnr.id, text=qd["text"], section=qd.get("section"), answer_type=qd.get("answer_type"), source_location=sl_json, confidence=qd.get("confidence"))
        db.add(q)
    db.commit()
    print(f"Created questionnaire: {qnr.filename} (id={qnr.id}, {len(questions_data)} questions)")

    doc_key = make_key(ws.id, "raw", "sample_evidence.txt")
    storage.upload(storage.bucket_raw, doc_key, b"Sample evidence document. Placeholder for demo workspace.", content_type="text/plain")
    doc = Document(workspace_id=ws.id, storage_key=doc_key, filename="sample_evidence.txt", content_type="text/plain", status="uploaded")
    db.add(doc)
    db.commit()
    db.refresh(doc)
    print(f"Created document: {doc.filename} (id={doc.id})")

    for ta in TRUST_ARTICLES:
        art = db.query(TrustArticle).filter(TrustArticle.slug == ta["slug"]).first()
        if art:
            art.title = ta["title"]
            art.content = ta["content"]
            art.category = ta.get("category")
            art.published = 1
        else:
            art = TrustArticle(
                workspace_id=ws.id,
                slug=ta["slug"],
                title=ta["title"],
                content=ta["content"],
                published=1,
                category=ta.get("category"),
            )
            db.add(art)
    db.commit()
    print("Created or updated trust articles")

    return ws


def seed_dev_compliance_catalog_for_demo(db: Session, workspace_id: int = DEFAULT_WORKSPACE_ID) -> None:
    """Link multi-framework dev catalog controls into the demo workspace (compliance tables)."""
    try:
        from scripts.seed_dev_compliance_catalog import seed_dev_compliance_catalog

        fc_n, wc_n = seed_dev_compliance_catalog(db, workspace_id=workspace_id)
        print(
            f"Dev compliance catalog: processed {fc_n} framework control definitions, "
            f"created {wc_n} new workspace_control link(s)."
        )
    except Exception as e:
        print(f"Dev compliance catalog seed skipped (compliance tables or data issue): {e}")


def main() -> None:
    db = SessionLocal()
    try:
        seed_demo_user(db)
        seed_admin_user(db)
        try:
            storage = StorageClient()
            storage.ensure_buckets()
            seed_demo_workspace(db, storage)
            print("Demo workspace questionnaire/documents seed complete.")
        except Exception as e:
            print("S3/MinIO unavailable or workspace seed failed: %s" % e)
            print("Demo user (demo@trust.local / j) and admin were created; login will work.")
        seed_dev_compliance_catalog_for_demo(db, workspace_id=DEFAULT_WORKSPACE_ID)
        print("Demo workspace seeding complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
