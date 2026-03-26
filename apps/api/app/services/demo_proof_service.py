"""Demo proof package generator — sample questionnaire, coverage report, gap list."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.questionnaire import Question, Questionnaire
from app.models.answer import Answer
from app.models.evidence_gap import EvidenceGap

logger = logging.getLogger(__name__)

SAMPLE_QUESTIONNAIRE = {
    "title": "Sample SOC 2 Security Questionnaire",
    "framework": "SOC 2 Type II",
    "sections": [
        {
            "name": "Access Control",
            "questions": [
                {
                    "text": "How do you manage user access to production systems?",
                    "answer": "Access to production systems is managed through role-based access control (RBAC) with three tiers: admin, editor, and reviewer. Each role has explicitly defined permissions enforced at the API layer. All access changes are logged in the system audit trail. MFA is available and can be enforced at the workspace level.",
                    "confidence": 92,
                    "evidence": "RBAC implementation in auth_deps.py; UserMfa model; AuditEvent logging",
                },
                {
                    "text": "Do you enforce multi-factor authentication?",
                    "answer": "Yes. We support TOTP-based multi-factor authentication compatible with standard authenticator apps. MFA can be enforced at the workspace level by administrators through the mfa_required workspace setting. Recovery codes are generated during MFA setup. MFA login tokens expire after 5 minutes.",
                    "confidence": 95,
                    "evidence": "UserMfa model with TOTP; MfaLoginToken with expiry; Workspace.mfa_required flag",
                },
                {
                    "text": "How do you handle user offboarding?",
                    "answer": "When a user is removed from a workspace, their workspace membership is deleted and all active sessions are invalidated. Suspended users receive a 403 response on any API request. Audit logs record all membership changes including removals.",
                    "confidence": 88,
                    "evidence": "WorkspaceMember suspension; session invalidation in auth_deps.py",
                },
            ],
        },
        {
            "name": "Data Protection",
            "questions": [
                {
                    "text": "Is customer data encrypted at rest?",
                    "answer": "Yes. All data at rest is encrypted using AES-256 encryption. Database volumes use full-disk encryption provided by DigitalOcean managed databases. Object storage (S3-compatible) uses server-side encryption with managed keys.",
                    "confidence": 94,
                    "evidence": "DigitalOcean managed database encryption; S3 server-side encryption configuration",
                },
                {
                    "text": "Is data encrypted in transit?",
                    "answer": "Yes. All data in transit uses TLS 1.2 or higher. The application is served behind Caddy which provides automatic HTTPS with Let's Encrypt certificates. All API endpoints reject non-HTTPS connections in production.",
                    "confidence": 96,
                    "evidence": "Caddy TLS configuration; HTTPS enforcement in deployment",
                },
                {
                    "text": "How do you ensure data isolation between tenants?",
                    "answer": "Workspace-level tenant isolation is enforced at the application layer. Every database query is scoped to the authenticated user's workspace_id. Storage paths include workspace identifiers. Vector search is filtered by workspace_id. Background jobs are workspace-scoped. Isolation is validated by automated integration tests.",
                    "confidence": 97,
                    "evidence": "Workspace scoping in all API routes; test_tenant_isolation.py; auth_deps.py workspace filtering",
                },
            ],
        },
        {
            "name": "Logging & Monitoring",
            "questions": [
                {
                    "text": "Do you maintain audit logs of system activity?",
                    "answer": "Yes. All significant actions are recorded in a comprehensive audit log including: authentication events, workspace changes, document operations, questionnaire processing, answer generation, export operations, and admin actions. Logs include timestamps, user identity, action type, and affected resources. Audit events are accessible to workspace administrators via the API.",
                    "confidence": 95,
                    "evidence": "AuditEvent model; audit routes; persist_audit calls throughout codebase",
                },
                {
                    "text": "How do you monitor for security incidents?",
                    "answer": "We use Sentry for real-time error monitoring and alerting. Application metrics are exposed via a Prometheus-compatible /metrics endpoint tracking request counts, latency, and error rates. Suspicious authentication patterns (brute force, credential stuffing) are detected by rate limiting and logged as security events.",
                    "confidence": 85,
                    "evidence": "Sentry integration in main.py; metrics endpoint; rate_limit.py threat detection",
                },
            ],
        },
        {
            "name": "Incident Response",
            "questions": [
                {
                    "text": "Do you have an incident response plan?",
                    "answer": "Yes. Our incident response process includes detection through application monitoring, classification by severity, containment and investigation, resolution and recovery, and post-incident documentation. For security incidents affecting customer data, we notify affected customers within 72 hours consistent with GDPR requirements.",
                    "confidence": 80,
                    "evidence": "Monitoring infrastructure; notification service for alerts",
                },
                {
                    "text": "How do you handle vulnerability management?",
                    "answer": "We employ automated dependency scanning, regular security reviews, and infrastructure-level patching. Critical vulnerabilities are prioritized for immediate remediation. We maintain a responsible disclosure policy for external researchers.",
                    "confidence": 78,
                    "evidence": "Dependency management; CI pipeline; security review process",
                },
            ],
        },
        {
            "name": "Business Continuity",
            "questions": [
                {
                    "text": "What is your backup and recovery strategy?",
                    "answer": "Database backups are automated daily by the managed database service with point-in-time recovery available for 7 days. Backups are encrypted and stored in a separate geographic location. Object storage uses built-in redundancy with automatic replication. Backup restoration procedures are documented.",
                    "confidence": 90,
                    "evidence": "DigitalOcean managed database backups; S3 replication",
                },
            ],
        },
    ],
}


def generate_demo_package(db: Session, workspace_id: int) -> dict:
    """Generate a complete demo proof package for sales and onboarding."""
    questionnaire = _build_sample_questionnaire()
    coverage = _build_coverage_report(questionnaire)
    gaps = _build_gap_list(questionnaire)
    walkthrough = _build_walkthrough()
    live_stats = _get_live_stats(db, workspace_id)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace_id": workspace_id,
        "sample_questionnaire": questionnaire,
        "coverage_report": coverage,
        "gap_list": gaps,
        "walkthrough": walkthrough,
        "live_stats": live_stats,
    }


def _build_sample_questionnaire() -> dict:
    questions = []
    for section in SAMPLE_QUESTIONNAIRE["sections"]:
        for q in section["questions"]:
            questions.append({
                "section": section["name"],
                "question": q["text"],
                "answer": q["answer"],
                "confidence": q["confidence"],
                "evidence_sources": q["evidence"],
            })
    return {
        "title": SAMPLE_QUESTIONNAIRE["title"],
        "framework": SAMPLE_QUESTIONNAIRE["framework"],
        "total_questions": len(questions),
        "questions": questions,
    }


def _build_coverage_report(questionnaire: dict) -> dict:
    questions = questionnaire["questions"]
    total = len(questions)
    answered = sum(1 for q in questions if q["answer"])
    high_conf = sum(1 for q in questions if q["confidence"] >= 90)
    med_conf = sum(1 for q in questions if 70 <= q["confidence"] < 90)
    low_conf = sum(1 for q in questions if q["confidence"] < 70)
    avg_conf = sum(q["confidence"] for q in questions) / total if total else 0

    sections = {}
    for q in questions:
        sec = q["section"]
        if sec not in sections:
            sections[sec] = {"total": 0, "avg_confidence": 0, "confidences": []}
        sections[sec]["total"] += 1
        sections[sec]["confidences"].append(q["confidence"])

    section_summary = []
    for name, data in sections.items():
        avg = sum(data["confidences"]) / len(data["confidences"]) if data["confidences"] else 0
        section_summary.append({
            "section": name,
            "questions": data["total"],
            "avg_confidence": round(avg, 1),
        })

    return {
        "total_questions": total,
        "answered": answered,
        "coverage_pct": round(answered / total * 100, 1) if total else 0,
        "avg_confidence": round(avg_conf, 1),
        "high_confidence": high_conf,
        "medium_confidence": med_conf,
        "low_confidence": low_conf,
        "by_section": section_summary,
    }


def _build_gap_list(questionnaire: dict) -> dict:
    gaps = []
    for q in questionnaire["questions"]:
        if q["confidence"] < 85:
            gaps.append({
                "section": q["section"],
                "question": q["question"],
                "confidence": q["confidence"],
                "recommendation": _gap_recommendation(q["section"], q["confidence"]),
            })
    return {
        "total_gaps": len(gaps),
        "gaps": gaps,
    }


def _gap_recommendation(section: str, confidence: int) -> str:
    if confidence < 70:
        return f"Upload supporting documentation for {section}. This area needs additional evidence to meet buyer expectations."
    return f"Review and strengthen evidence for {section}. Consider uploading recent audit reports or policy documents."


def _build_walkthrough() -> dict:
    return {
        "steps": [
            {
                "step": 1,
                "title": "Upload Evidence Documents",
                "description": "Upload your compliance documents (SOC 2 reports, policies, certifications) to the Documents module. Trust Copilot automatically indexes and classifies them by framework and control area.",
            },
            {
                "step": 2,
                "title": "Upload the Questionnaire",
                "description": "Upload the security questionnaire you received (XLSX, DOCX, or PDF). Trust Copilot extracts individual questions, detects the framework, and classifies each question by subject area.",
            },
            {
                "step": 3,
                "title": "Generate AI Answers with Citations",
                "description": "Trust Copilot's RAG pipeline retrieves relevant evidence from your uploaded documents and generates draft answers with citations. Each answer includes a confidence score based on evidence strength.",
            },
            {
                "step": 4,
                "title": "Review and Approve",
                "description": "Review generated answers in the Review module. Approve high-confidence answers, edit medium-confidence ones, and manually address low-confidence areas. All reviewed answers feed the reusable answer library.",
            },
            {
                "step": 5,
                "title": "Export and Send",
                "description": "Export the completed questionnaire in XLSX or DOCX format with answers, citations, and evidence references. Send it back to the requesting party and close the deal.",
            },
        ],
    }


def _get_live_stats(db: Session, workspace_id: int) -> dict:
    """Pull real workspace stats to demonstrate the product with actual data."""
    try:
        q_count = db.query(Questionnaire).filter(Questionnaire.workspace_id == workspace_id).count()
        question_count = db.query(Question).join(Questionnaire).filter(Questionnaire.workspace_id == workspace_id).count()
        answer_count = db.query(Answer).join(Question).join(Questionnaire).filter(Questionnaire.workspace_id == workspace_id).count()
        gap_count = db.query(EvidenceGap).filter(EvidenceGap.workspace_id == workspace_id).count()
    except Exception:
        q_count = question_count = answer_count = gap_count = 0

    return {
        "questionnaires_processed": q_count,
        "questions_answered": question_count,
        "ai_answers_generated": answer_count,
        "evidence_gaps_identified": gap_count,
    }
