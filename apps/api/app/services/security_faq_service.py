"""Security and data-handling FAQ service — seed, CRUD, and search."""

import logging

from sqlalchemy.orm import Session

from app.models.security_faq import SecurityFAQ

logger = logging.getLogger(__name__)

DEFAULT_FAQ: list[dict] = [
    {
        "category": "data_storage",
        "question": "Where is customer data stored?",
        "answer": "All customer data is stored in PostgreSQL databases hosted on DigitalOcean infrastructure within US data centers. File uploads (documents, evidence) are stored in S3-compatible object storage with server-side encryption enabled. No customer data is stored on local machines or developer workstations.",
        "framework_tags": "SOC2,ISO27001,HIPAA,GDPR",
    },
    {
        "category": "data_storage",
        "question": "Is data encrypted at rest?",
        "answer": "Yes. All data at rest is encrypted using AES-256 encryption. Database volumes use full-disk encryption provided by the infrastructure provider. Object storage uses server-side encryption (SSE) with managed keys. Encryption keys are managed by the infrastructure provider and rotated according to their key management policies.",
        "framework_tags": "SOC2,ISO27001,HIPAA,PCI-DSS",
    },
    {
        "category": "data_storage",
        "question": "Is data encrypted in transit?",
        "answer": "Yes. All data in transit is encrypted using TLS 1.2 or higher. The application is served behind a reverse proxy (Caddy) that enforces HTTPS with automatic certificate management via Let's Encrypt. Internal service-to-service communication within the container network uses encrypted connections. API endpoints reject non-HTTPS connections.",
        "framework_tags": "SOC2,ISO27001,HIPAA,PCI-DSS",
    },
    {
        "category": "access_control",
        "question": "How is access to customer data controlled?",
        "answer": "Access is controlled through a multi-layer approach: (1) Role-based access control (RBAC) with admin, editor, and reviewer roles, each with specific permissions. (2) Workspace-level tenant isolation ensures users can only access data in their assigned workspaces. (3) Session-based authentication with configurable session timeouts. (4) Optional multi-factor authentication (TOTP) with recovery codes. (5) API key authentication for programmatic access with scoped permissions.",
        "framework_tags": "SOC2,ISO27001,HIPAA,NIST",
    },
    {
        "category": "access_control",
        "question": "Do you support multi-factor authentication (MFA)?",
        "answer": "Yes. We support TOTP-based multi-factor authentication compatible with any authenticator app (Google Authenticator, Authy, 1Password, etc.). MFA can be enforced at the workspace level by administrators. Recovery codes are generated during MFA setup for account recovery. MFA tokens have a 5-minute expiry window.",
        "framework_tags": "SOC2,ISO27001,HIPAA,NIST",
    },
    {
        "category": "access_control",
        "question": "Do you support Single Sign-On (SSO)?",
        "answer": "Yes. We support OIDC-based Single Sign-On for enterprise customers. SSO can be configured with providers like Okta, Auth0, Azure AD, and Google Workspace. Just-in-time (JIT) user provisioning is supported so users are automatically created on first SSO login. SAML support is on our roadmap.",
        "framework_tags": "SOC2,ISO27001,NIST",
    },
    {
        "category": "data_retention",
        "question": "What is your data retention policy?",
        "answer": "Customer data is retained for the duration of the active subscription. Upon account cancellation or termination, all customer data including documents, questionnaires, answers, and evidence items are scheduled for deletion within 30 days. Customers can request immediate data deletion at any time. Backup data is purged within 90 days of the primary data deletion. Audit logs are retained for 12 months for compliance purposes.",
        "framework_tags": "SOC2,ISO27001,GDPR,HIPAA",
    },
    {
        "category": "data_retention",
        "question": "Can I request deletion of my data?",
        "answer": "Yes. Workspace administrators can delete individual documents, questionnaires, and evidence items at any time through the application. For complete account deletion, contact our support team. We process deletion requests within 5 business days and provide written confirmation once all data has been removed from primary storage. Backup data is purged within 90 days.",
        "framework_tags": "GDPR,CCPA,SOC2",
    },
    {
        "category": "audit_logging",
        "question": "Do you maintain audit logs?",
        "answer": "Yes. All significant actions are recorded in a comprehensive audit log including: user authentication events, workspace membership changes, document uploads and deletions, questionnaire processing, answer generation and approvals, export operations, admin configuration changes, and API key usage. Audit logs include timestamps, user identity, action type, and affected resources. Logs are retained for 12 months and are accessible to workspace administrators.",
        "framework_tags": "SOC2,ISO27001,HIPAA,NIST",
    },
    {
        "category": "infrastructure",
        "question": "What is your infrastructure architecture?",
        "answer": "The application runs as containerized services (Docker) on DigitalOcean infrastructure. The architecture includes: a FastAPI backend application server, PostgreSQL database with pgvector extension for semantic search, S3-compatible object storage for files, and a Next.js frontend served via CDN. All services run within a private network with only the application endpoints exposed publicly behind a TLS-terminating reverse proxy.",
        "framework_tags": "SOC2,ISO27001",
    },
    {
        "category": "infrastructure",
        "question": "How do you handle backups?",
        "answer": "Database backups are performed automatically on a daily basis by the managed database service. Backups are encrypted and stored in a separate geographic location from the primary database. Point-in-time recovery is available for the most recent 7-day window. Object storage uses built-in redundancy with automatic replication. Backup restoration procedures are documented and tested quarterly.",
        "framework_tags": "SOC2,ISO27001,HIPAA",
    },
    {
        "category": "incident_response",
        "question": "Do you have an incident response plan?",
        "answer": "Yes. Our incident response process includes: (1) Detection through application monitoring, error tracking (Sentry), and log analysis. (2) Classification by severity (critical, high, medium, low). (3) Containment and investigation. (4) Resolution and recovery. (5) Post-incident review and documentation. For security incidents affecting customer data, we notify affected customers within 72 hours as required by GDPR and consistent with industry best practices.",
        "framework_tags": "SOC2,ISO27001,HIPAA,GDPR,NIST",
    },
    {
        "category": "incident_response",
        "question": "How do you handle vulnerability management?",
        "answer": "We employ a multi-layered vulnerability management approach: (1) Automated dependency scanning for known vulnerabilities in third-party packages. (2) Regular application security reviews. (3) Infrastructure-level security patches applied automatically by managed service providers. (4) Responsible disclosure policy for external security researchers. Critical vulnerabilities are prioritized for immediate remediation; high-severity issues are addressed within 7 days.",
        "framework_tags": "SOC2,ISO27001,NIST,PCI-DSS",
    },
    {
        "category": "data_privacy",
        "question": "How do you handle personal data under GDPR?",
        "answer": "We process personal data as a data processor on behalf of our customers (data controllers). We maintain a Data Processing Agreement (DPA) template available upon request. Personal data processing is limited to what is necessary for service delivery. We do not sell, share, or use customer data for advertising or training purposes beyond the customer's own workspace. Data subjects can exercise their rights (access, rectification, erasure, portability) through the customer's workspace administrator.",
        "framework_tags": "GDPR,CCPA,SOC2",
    },
    {
        "category": "data_privacy",
        "question": "Do you use customer data to train AI models?",
        "answer": "No. Customer documents, questionnaires, and answers are never used to train AI models. The AI features (answer generation, question classification) use third-party LLM APIs (OpenAI) where customer data is sent only for real-time inference — not for model training. OpenAI's API terms explicitly state that API inputs are not used for training. All AI processing is scoped to the individual workspace making the request.",
        "framework_tags": "GDPR,SOC2,ISO27001",
    },
    {
        "category": "tenant_isolation",
        "question": "How do you ensure data isolation between customers?",
        "answer": "Workspace-level tenant isolation is enforced at the application layer across all data operations. Every database query is scoped to the authenticated user's workspace. Storage paths include workspace identifiers to prevent cross-tenant file access. API endpoints validate workspace membership before returning any data. Vector search (pgvector) for semantic retrieval is filtered by workspace_id. Background job execution is workspace-scoped. These isolation rules are covered by automated integration tests.",
        "framework_tags": "SOC2,ISO27001,HIPAA",
    },
    {
        "category": "business_continuity",
        "question": "What is your uptime commitment?",
        "answer": "We target 99.9% uptime for the application. The infrastructure is hosted on DigitalOcean which provides 99.99% uptime SLA for compute and managed databases. Application health is monitored continuously with automated alerting. In the event of an outage, our incident response process is activated immediately. Planned maintenance windows are communicated in advance and scheduled during low-usage periods.",
        "framework_tags": "SOC2,ISO27001",
    },
    {
        "category": "third_party",
        "question": "What third-party services do you use?",
        "answer": "Key third-party services: (1) DigitalOcean — cloud infrastructure (compute, managed PostgreSQL, object storage). (2) OpenAI — AI inference for answer generation and question classification (API only, no training). (3) Stripe — payment processing. (4) Let's Encrypt — TLS certificates. (5) Sentry — error monitoring and tracking. All third-party providers are evaluated for their security practices and compliance certifications before integration.",
        "framework_tags": "SOC2,ISO27001,HIPAA",
    },
    {
        "category": "third_party",
        "question": "Do you have a subprocessor list?",
        "answer": "Yes. Our subprocessor list includes: DigitalOcean (infrastructure), OpenAI (AI inference), Stripe (payments), and email service providers for transactional notifications. We notify customers of any changes to our subprocessor list. A current version of the subprocessor list is available upon request and will be published on our Trust Center.",
        "framework_tags": "GDPR,SOC2",
    },
    {
        "category": "change_management",
        "question": "How do you manage code changes?",
        "answer": "All code changes follow a structured process: (1) Changes are developed in feature branches with descriptive commit messages. (2) Code review is required before merging. (3) Automated tests run on every change (unit, integration, and end-to-end). (4) Deployments are performed via containerized CI/CD pipelines. (5) Configuration changes are managed through environment variables with no secrets in source code. (6) Database schema changes use versioned migrations (Alembic) with rollback support.",
        "framework_tags": "SOC2,ISO27001,NIST",
    },
]


def seed_defaults(db: Session, workspace_id: int) -> int:
    """Seed default FAQ entries for a workspace. Skips if entries already exist."""
    existing = db.query(SecurityFAQ).filter(
        SecurityFAQ.workspace_id == workspace_id,
        SecurityFAQ.is_default == 1,
    ).count()
    if existing > 0:
        return 0

    created = 0
    for faq in DEFAULT_FAQ:
        db.add(SecurityFAQ(
            workspace_id=workspace_id,
            category=faq["category"],
            question=faq["question"],
            answer=faq["answer"],
            framework_tags=faq.get("framework_tags"),
            is_default=1,
        ))
        created += 1
    db.flush()
    return created


def list_faqs(
    db: Session,
    workspace_id: int,
    category: str | None = None,
    search: str | None = None,
    framework: str | None = None,
) -> list[dict]:
    """List FAQ entries with optional filters."""
    q = db.query(SecurityFAQ).filter(SecurityFAQ.workspace_id == workspace_id)
    if category:
        q = q.filter(SecurityFAQ.category == category)
    if framework:
        q = q.filter(SecurityFAQ.framework_tags.ilike(f"%{framework}%"))
    if search:
        q = q.filter(
            SecurityFAQ.question.ilike(f"%{search}%")
            | SecurityFAQ.answer.ilike(f"%{search}%")
        )
    q = q.order_by(SecurityFAQ.category, SecurityFAQ.id)
    return [_serialize(f) for f in q.all()]


def get_faq(db: Session, faq_id: int) -> dict | None:
    item = db.query(SecurityFAQ).filter(SecurityFAQ.id == faq_id).first()
    return _serialize(item) if item else None


def create_faq(
    db: Session,
    workspace_id: int,
    category: str,
    question: str,
    answer: str,
    framework_tags: str | None = None,
) -> dict:
    """Create a custom FAQ entry."""
    item = SecurityFAQ(
        workspace_id=workspace_id,
        category=category,
        question=question,
        answer=answer,
        framework_tags=framework_tags,
        is_default=0,
    )
    db.add(item)
    db.flush()
    return _serialize(item)


def update_faq(db: Session, faq_id: int, **updates) -> dict | None:
    item = db.query(SecurityFAQ).filter(SecurityFAQ.id == faq_id).first()
    if not item:
        return None
    for key in ("category", "question", "answer", "framework_tags"):
        if key in updates and updates[key] is not None:
            setattr(item, key, updates[key])
    db.flush()
    return _serialize(item)


def delete_faq(db: Session, faq_id: int) -> bool:
    item = db.query(SecurityFAQ).filter(SecurityFAQ.id == faq_id).first()
    if not item:
        return False
    db.delete(item)
    db.flush()
    return True


def get_categories(db: Session, workspace_id: int) -> list[str]:
    """Return distinct categories for a workspace."""
    rows = (
        db.query(SecurityFAQ.category)
        .filter(SecurityFAQ.workspace_id == workspace_id)
        .distinct()
        .order_by(SecurityFAQ.category)
        .all()
    )
    return [r[0] for r in rows]


def _serialize(item: SecurityFAQ) -> dict:
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "category": item.category,
        "question": item.question,
        "answer": item.answer,
        "framework_tags": item.framework_tags,
        "is_default": bool(item.is_default),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }
