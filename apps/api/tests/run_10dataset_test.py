"""End-to-end 10-dataset framework classification + answer validation.

Datasets 1-8:  Framework-specific (SOC2, HIPAA, ISO27001, NIST CSF, 800-53, 800-171, SIG, CAIQ)
Datasets 9-10: Negative controls (generic vendor, generic healthcare without HIPAA)

Usage:
  python -u tests/run_10dataset_test.py
"""

import base64
import hmac
import io
import json
import os
import sys
import time

import requests

API = os.environ.get("TC_API", "http://localhost:8000")
POLL_INTERVAL = 3
POLL_TIMEOUT = 300
SESSION_SECRET = os.environ.get(
    "TC_SESSION_SECRET",
    "zDWud8xGEkOl_7ceEhfvrGeTNehTp3ttPHo9uYEcCGoyZUOlYvYBCiDHjp1stF_0",
)


def _make_session_cookie(workspace_id: int = 1) -> str:
    payload = {"user_id": 1, "email": "reinhartjm294@gmail.com", "workspace_id": workspace_id, "role": "admin"}
    data = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), data.encode("utf-8"), "sha256").hexdigest()
    return f"{data}.{sig}"


S = requests.Session()
S.cookies.set("tc_session", _make_session_cookie())


def _set_ws(ws_id: int) -> None:
    S.cookies.set("tc_session", _make_session_cookie(ws_id))


# ═══════════════════════════════════════════════════════════════════════════
# DATASET 1 — SOC 2 / Redwood Analytics
# ═══════════════════════════════════════════════════════════════════════════

D1_EV_A = """Redwood SOC 2 System Description Summary

Redwood Analytics is a service organization that provides a multi-tenant analytics platform hosted primarily in AWS, with disaster recovery failover capability in Microsoft Azure. The system description supports Redwood's SOC 2 Type II examination against the Trust Services Criteria for Security and Availability.

Management has designed and implemented controls to support service commitments and system requirements. Production environments are segmented using virtual private cloud architecture, separate subnets for application, database, and management traffic, and restricted ingress through load balancers and API gateways.

Logical access is managed through centralized identity and access management, role-based access control, and multi-factor authentication for administrative access. Access provisioning is approved by management, and privileged access is logged and monitored.

Logs from production systems are centralized in the company SIEM. Monitoring activities include alert generation for anomalous behavior, review of critical events, and retention of security logs for at least 365 days.

Backups are performed daily and replicated to a geographically separate region. Backup restoration tests are performed quarterly. Complementary user entity controls include appropriate customer-side user provisioning and secure credential handling."""

D1_EV_B = """Redwood Change and Incident Management Standard

Redwood maintains formal change management and incident response procedures. Changes to production systems are tracked through a ticketing workflow, reviewed by authorized personnel, tested prior to release, and approved before deployment. Emergency changes require retrospective review.

The incident response program defines severity levels of Low, Medium, High, and Critical. Detection mechanisms include SIEM alerts, employee reporting, and infrastructure monitoring. Incident handling includes triage, containment, eradication, recovery, stakeholder communication, and post-incident review. Annual tabletop exercises are used to test the incident response plan."""

D1_QUESTIONS = [
    "Are you a SOC 2 audited service organization?",
    "What Trust Services Criteria are in scope?",
    "How do you segment your production environment?",
    "Is MFA required for administrative access?",
    "How do you manage privileged access?",
    "What is your log retention period?",
    "How do you detect and respond to incidents?",
    "How often are backups performed and tested?",
    "Describe your disaster recovery strategy.",
    "Describe your formal change management process.",
]

# ═══════════════════════════════════════════════════════════════════════════
# DATASET 2 — HIPAA / Riverbend Health
# ═══════════════════════════════════════════════════════════════════════════

D2_EV_A = """Riverbend HIPAA Security Rule Safeguards Overview

Riverbend Health Services processes electronic protected health information (ePHI) in support of care coordination workflows. Riverbend operates as a business associate for covered entity customers and maintains Business Associate Agreements where required.

Administrative safeguards include workforce training, risk analysis activities, information access management, and incident response procedures. Technical safeguards include role-based access controls, unique user identification, audit logging, person or entity authentication, and encryption of ePHI in transit using TLS 1.2 or higher.

Audit logs are reviewed by security personnel and retained for 180 days. Access to systems containing ePHI is restricted to authorized workforce members based on job responsibilities.

Riverbend has documented breach escalation procedures and coordinates breach-related communications with covered entity customers in accordance with contractual and legal obligations."""

D2_EV_B = """Riverbend Device, Media, and Backup Standard

Riverbend maintains daily backups of critical systems and stores backup copies in secure cloud storage. Backup restoration is tested semi-annually. Workstations are managed according to approved configuration baselines, and removable media containing sensitive data must be encrypted and tracked.

Termination procedures require revocation of access through the identity management process, return of company devices, and confirmation that credentials associated with production systems have been disabled."""

D2_QUESTIONS = [
    "Do you process PHI or ePHI?",
    "Are you a covered entity or business associate?",
    "How do you protect ePHI in transit?",
    "How do you protect ePHI at rest?",
    "How do you manage workforce access to ePHI?",
    "How long are audit logs retained?",
    "Do you have breach notification procedures?",
    "How are terminated users removed from systems?",
    "Are backups performed and restoration tested?",
    "Do you maintain Business Associate Agreements where required?",
]

# ═══════════════════════════════════════════════════════════════════════════
# DATASET 3 — ISO 27001 / Northway Systems
# ═══════════════════════════════════════════════════════════════════════════

D3_EV_A = """Northway ISMS Scope and Statement of Applicability Summary

Northway Systems has established, implemented, and maintains an Information Security Management System (ISMS) aligned to ISO/IEC 27001:2022. The scope of the ISMS includes the design, development, operation, and support of Northway's SaaS platform and supporting corporate functions.

Northway maintains a Statement of Applicability that documents which Annex A controls are applicable, the implementation status of each control, and the justification for exclusions. Information security objectives are reviewed at planned intervals, and risk treatment decisions are documented through the risk treatment plan.

Documented information relevant to the ISMS is maintained according to the document control process."""

D3_EV_B = """Northway Internal Audit and Management Review Summary

Northway performs internal ISMS audits on a planned basis to evaluate conformance and effectiveness. Audit findings are recorded, assigned owners, and tracked through corrective action to closure.

Management reviews the ISMS at least annually. Inputs include audit results, risk treatment status, security incidents, changes affecting the ISMS, and opportunities for continual improvement. Nonconformities are handled through corrective action procedures."""

D3_QUESTIONS = [
    "Do you maintain an ISMS?",
    "What is the scope of the ISMS?",
    "Do you maintain a Statement of Applicability?",
    "How do you determine applicable controls?",
    "Are information security objectives reviewed?",
    "Are internal audits performed?",
    "How are audit findings tracked?",
    "Is management review performed?",
    "How are nonconformities and corrective actions handled?",
    "How do you document risk treatment decisions?",
]

# ═══════════════════════════════════════════════════════════════════════════
# DATASET 4 — NIST CSF 2.0 / Atlas Manufacturing
# ═══════════════════════════════════════════════════════════════════════════

D4_EV_A = """Atlas Cybersecurity Framework Profile Summary

Atlas Manufacturing uses the NIST Cybersecurity Framework 2.0 to organize its cybersecurity program. Atlas maintains a current profile and a target profile aligned to business priorities and risk tolerance. The program is structured around the Govern, Identify, Protect, Detect, Respond, and Recover functions.

Gaps between the current and target profiles are tracked through a remediation roadmap, with ownership assigned to responsible teams. Cybersecurity outcomes are reviewed during periodic risk governance meetings."""

D4_EV_B = """Atlas CSF Implementation Tiers and Improvement Plan

Atlas uses implementation tiers to describe the maturity and integration of cybersecurity risk management practices. Tiering is used to inform planning and prioritization rather than as a certification mechanism.

Planned improvements include strengthening asset inventory processes, expanding detection engineering, and improving business continuity coordination across manufacturing sites."""

D4_QUESTIONS = [
    "Do you use the NIST Cybersecurity Framework?",
    "Do you maintain a current profile and target profile?",
    "How do you track gaps between profiles?",
    "Which CSF functions organize your program?",
    "Do you use implementation tiers?",
    "How do you use tiers in decision-making?",
    "How do you govern cybersecurity outcomes?",
    "How do you prioritize improvements?",
    "How do you address asset inventory gaps?",
    "How does the framework support recovery planning?",
]

# ═══════════════════════════════════════════════════════════════════════════
# DATASET 5 — NIST SP 800-53 Rev. 5 / FederalEdge
# ═══════════════════════════════════════════════════════════════════════════

D5_EV_A = """FederalEdge 800-53 Control Implementation Summary

FederalEdge maps its security program to NIST SP 800-53 Rev. 5. Control implementations include AC-2 for account management, IA-2 for identification and authentication, AU-6 for audit review, analysis, and reporting, CM-2 for baseline configuration, SC-7 for boundary protection, and IR-4 for incident handling.

Control owners are assigned to each implemented control. Control evidence is reviewed periodically and tracked within the governance system."""

D5_EV_B = """FederalEdge Baseline and Assessment Notes

FederalEdge aligns relevant systems to moderate baseline expectations and maintains assessment records showing implementation status, planned remediation, and responsible owners. Audit and accountability, system and communications protection, and incident response controls are reviewed during internal assessment cycles."""

D5_QUESTIONS = [
    "Do you map controls to NIST SP 800-53 Rev. 5?",
    "How do you implement AC-2 account management?",
    "How do you implement IA-2 authentication?",
    "How do you perform AU-6 audit review and analysis?",
    "How do you maintain CM-2 baseline configurations?",
    "How is SC-7 boundary protection implemented?",
    "How do you perform IR-4 incident handling?",
    "Are control owners assigned?",
    "Do you maintain assessment records?",
    "What baseline level is used for relevant systems?",
]

# ═══════════════════════════════════════════════════════════════════════════
# DATASET 6 — NIST SP 800-171 Rev. 3 / CUIWorks
# ═══════════════════════════════════════════════════════════════════════════

D6_EV_A = """CUIWorks Protecting CUI Program Summary

CUIWorks handles Controlled Unclassified Information (CUI) within nonfederal systems and organizations supporting federal contractors. The security program is aligned to NIST SP 800-171 Rev. 3.

Relevant security requirements include 3.1 access control, 3.3 audit and accountability, 3.5 identification and authentication, 3.6 incident response, 3.11 risk assessment, and 3.13 system and communications protection. Requirement owners are assigned and tracked through periodic compliance reviews."""

D6_EV_B = """CUIWorks Authentication and Communications Security Note

CUIWorks requires unique user identification, role-based access controls, multi-factor authentication for privileged access, and encryption of CUI in transit. Security requirement reviews include validation of access restrictions, log review processes, and communications protection controls."""

D6_QUESTIONS = [
    "Do you protect CUI in nonfederal systems?",
    "Is your program aligned to NIST SP 800-171 Rev. 3?",
    "How do you address 3.1 access control requirements?",
    "How do you address 3.3 audit and accountability requirements?",
    "How do you address 3.5 identification and authentication requirements?",
    "How do you address 3.6 incident response requirements?",
    "How do you address 3.11 risk assessment requirements?",
    "How do you address 3.13 communications protection requirements?",
    "Is MFA required for privileged access?",
    "Is CUI encrypted in transit?",
]

# ═══════════════════════════════════════════════════════════════════════════
# DATASET 7 — SIG / HarborPay
# ═══════════════════════════════════════════════════════════════════════════

D7_EV_A = """HarborPay Third-Party Risk and Security Overview

HarborPay provides payment workflow software to enterprise customers. The company maintains formal security policies covering access control, incident response, data protection, workforce training, and vendor management. Third-party service providers are evaluated during onboarding and reviewed according to risk.

Incident response procedures include escalation, investigation, customer communication, and post-incident analysis. Employees complete annual security awareness training."""

D7_EV_B = """HarborPay Business Continuity and Privacy Summary

HarborPay maintains backup and restoration procedures for critical systems, annual tabletop exercises for response planning, and privacy commitments related to customer data handling. Material subprocessors are tracked and subject to contractual review."""

D7_QUESTIONS = [
    "Provide a company profile and description of services.",
    "Describe your regulatory compliance and external assurance activities.",
    "Describe your third-party risk management process.",
    "Do you use subcontractors or fourth parties?",
    "How do you manage customer data privacy obligations?",
    "Describe your incident management and escalation process.",
    "Describe your business continuity and resilience program.",
    "What workforce security training is required?",
    "How do you review vendor contracts and subprocessors?",
    "How do you assess operational resilience risks?",
]

# ═══════════════════════════════════════════════════════════════════════════
# DATASET 8 — CAIQ / SkyLedger Cloud
# ═══════════════════════════════════════════════════════════════════════════

D8_EV_A = """SkyLedger Cloud Security Overview

SkyLedger is a cloud service provider offering multi-tenant SaaS workloads. Customer environments are logically separated, and access to administrative interfaces requires centralized authentication and role-based access controls. Data is encrypted at rest and in transit, and security logs are aggregated into a centralized monitoring platform.

The platform follows a shared responsibility model describing provider-managed controls and customer-managed configurations."""

D8_EV_B = """SkyLedger CSA STAR Self-Assessment Summary

SkyLedger maintains a cloud assurance self-assessment aligned to the Cloud Controls Matrix. The assessment covers governance, identity and access management, cryptography and key management, logging and monitoring, threat and vulnerability management, data security and privacy, and infrastructure and virtualization security.

Cloud service models and security responsibilities are documented for customers."""

D8_QUESTIONS = [
    "Are you a cloud service provider?",
    "Describe your shared responsibility model.",
    "How do you address identity and access management controls?",
    "How do you address cryptography, encryption, and key management?",
    "How do you address logging and monitoring controls?",
    "How do you address threat and vulnerability management?",
    "How do you address data security and privacy controls?",
    "How do you address infrastructure and virtualization security?",
    "Do you maintain a Cloud Controls Matrix self-assessment?",
    "Is your self-assessment aligned to CSA STAR or CAIQ practices?",
]

# ═══════════════════════════════════════════════════════════════════════════
# DATASET 9 — Negative Control: Generic Vendor
# ═══════════════════════════════════════════════════════════════════════════

D9_EV_A = """BrightOps Security Overview

BrightOps maintains policies for access control, logging, encryption, backups, and incident response. The company uses cloud infrastructure and monitors its environment for security events."""

D9_QUESTIONS = [
    "Describe your security program.",
    "Do you encrypt data?",
    "Do you require MFA?",
    "How do you monitor your environment?",
    "Do you have an incident response plan?",
    "Are backups performed?",
    "How do you manage vendors?",
    "How do you manage access control?",
]

# ═══════════════════════════════════════════════════════════════════════════
# DATASET 10 — Negative Control: Generic Healthcare (no HIPAA markers)
# ═══════════════════════════════════════════════════════════════════════════

D10_EV_A = """CareBridge Security Note

CareBridge supports healthcare organizations and maintains role-based access controls, staff training, logging, and incident escalation procedures. Sensitive information is handled according to internal procedures and contractual requirements."""

D10_QUESTIONS = [
    "Describe your healthcare security controls.",
    "How do you control access to sensitive information?",
    "How do you train employees?",
    "How do you monitor systems?",
    "How do you escalate incidents?",
    "How do you handle customer data?",
]


# ═══════════════════════════════════════════════════════════════════════════
# API helpers
# ═══════════════════════════════════════════════════════════════════════════

def create_workspace(name: str) -> dict:
    r = S.post(f"{API}/api/workspaces", json={"name": name})
    r.raise_for_status()
    data = r.json()
    _set_ws(data["id"])
    return data


def upload_evidence(ws_id: int, filename: str, content: str) -> dict:
    _set_ws(ws_id)
    files = {"file": (filename, io.BytesIO(content.encode()), "text/plain")}
    r = S.post(f"{API}/api/documents/upload", data={"workspace_id": str(ws_id)}, files=files)
    r.raise_for_status()
    return r.json()


def wait_doc_indexed(ws_id: int, doc_id: int, timeout: int = 120):
    _set_ws(ws_id)
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = S.get(f"{API}/api/documents", params={"workspace_id": ws_id})
        r.raise_for_status()
        for d in r.json():
            if d["id"] == doc_id and d.get("status") == "indexed":
                return d
        time.sleep(2)
    raise TimeoutError(f"Doc {doc_id} not indexed within {timeout}s")


def get_doc_metadata(ws_id: int, doc_id: int) -> dict:
    _set_ws(ws_id)
    r = S.get(f"{API}/api/documents", params={"workspace_id": ws_id})
    r.raise_for_status()
    for d in r.json():
        if d["id"] == doc_id:
            return d
    return {}


def upload_questionnaire(ws_id: int, filename: str, questions: list[str]) -> dict:
    _set_ws(ws_id)
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Questions"
    ws.append(["Question"])
    for q in questions:
        ws.append([q])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    files = {"file": (filename, buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = S.post(f"{API}/api/questionnaires/upload", data={"workspace_id": str(ws_id)}, files=files)
    r.raise_for_status()
    return r.json()


def wait_qnr_parsed(ws_id: int, qnr_id: int, timeout: int = 120):
    _set_ws(ws_id)
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = S.get(f"{API}/api/questionnaires/{qnr_id}", params={"workspace_id": ws_id})
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "parsed":
            return data
        time.sleep(2)
    raise TimeoutError(f"QNR {qnr_id} not parsed within {timeout}s")


def generate_answers(ws_id: int, qnr_id: int) -> dict:
    _set_ws(ws_id)
    r = S.post(f"{API}/api/exports/generate/{qnr_id}", params={"workspace_id": ws_id})
    r.raise_for_status()
    return r.json()


def wait_answers_done(ws_id: int, job_id: int, timeout: int = POLL_TIMEOUT) -> dict:
    _set_ws(ws_id)
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = S.get(f"{API}/api/jobs/{job_id}", params={"workspace_id": ws_id})
        r.raise_for_status()
        data = r.json()
        if data.get("status") in ("completed", "failed"):
            return data
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Job {job_id} not done within {timeout}s")


def get_answers(ws_id: int, qnr_id: int) -> list[dict]:
    _set_ws(ws_id)
    r = S.get(f"{API}/api/questionnaires/{qnr_id}", params={"workspace_id": ws_id})
    r.raise_for_status()
    data = r.json()
    answers = []
    for q in data.get("questions", []):
        a = q.get("answer")
        if a:
            answers.append({
                "question_id": q["id"],
                "question_text": q.get("text", ""),
                "text": a.get("text"),
                "status": a.get("status"),
            })
        else:
            answers.append({
                "question_id": q["id"],
                "question_text": q.get("text", ""),
                "text": None,
                "status": "no_answer",
            })
    return answers


# ═══════════════════════════════════════════════════════════════════════════
# Dataset runner
# ═══════════════════════════════════════════════════════════════════════════

def run_dataset(name: str, evidence_docs: list[tuple[str, str]], questions: list[str]) -> dict:
    print(f"\n{'='*70}")
    print(f"  DATASET: {name}")
    print(f"  Questions: {len(questions)}, Evidence docs: {len(evidence_docs)}")
    print(f"{'='*70}")

    ws = create_workspace(f"Test - {name} - {int(time.time())}")
    ws_id = ws["id"]
    print(f"  Workspace: id={ws_id}")

    doc_ids = []
    doc_frameworks: dict[int, list[str]] = {}
    for fname, content in evidence_docs:
        d = upload_evidence(ws_id, fname, content)
        doc_id = d["id"]
        doc_ids.append(doc_id)
        print(f"  Evidence: {fname} -> doc_id={doc_id}")

    for doc_id in doc_ids:
        wait_doc_indexed(ws_id, doc_id)
        meta = get_doc_metadata(ws_id, doc_id)
        fw = meta.get("frameworks", [])
        doc_frameworks[doc_id] = fw
        print(f"  Doc {doc_id} indexed, frameworks={fw}")

    qnr = upload_questionnaire(ws_id, f"{name.replace(' ', '_')}_qnr.xlsx", questions)
    qnr_id = qnr["id"]
    print(f"  Questionnaire: id={qnr_id}")
    wait_qnr_parsed(ws_id, qnr_id)
    print(f"  Parsed")

    t_start = time.monotonic()
    gen = generate_answers(ws_id, qnr_id)
    job_id = gen.get("job_id") or gen.get("id")
    print(f"  Generation started: job_id={job_id}")

    job_result = wait_answers_done(ws_id, job_id)
    t_gen = time.monotonic() - t_start
    print(f"  Generation: {t_gen:.1f}s (status={job_result.get('status')})")

    answers = get_answers(ws_id, qnr_id)
    drafted = [a for a in answers if a.get("status") == "draft"]
    insufficient = [a for a in answers if a.get("status") == "insufficient_evidence"]
    no_answer = [a for a in answers if a.get("status") == "no_answer"]
    print(f"  Results: {len(answers)} total, {len(drafted)} drafted, {len(insufficient)} insufficient, {len(no_answer)} no_answer")

    print(f"\n  --- Answers ---")
    for a in answers:
        q = a.get("question_text", "?")[:70]
        a_text = (a.get("text") or "(no answer)")[:140]
        st = a.get("status", "?")
        print(f"  [{st:>22}] {q}")
        print(f"  {'':>24} {a_text}")
    print()

    return {
        "name": name,
        "workspace_id": ws_id,
        "questionnaire_id": qnr_id,
        "total_questions": len(questions),
        "total_answers": len(answers),
        "drafted": len(drafted),
        "insufficient": len(insufficient),
        "no_answer": len(no_answer),
        "generation_time_s": round(t_gen, 1),
        "job_status": job_result.get("status"),
        "doc_frameworks": {str(k): v for k, v in doc_frameworks.items()},
    }


# ═══════════════════════════════════════════════════════════════════════════
# Validation checks
# ═══════════════════════════════════════════════════════════════════════════

ALL_DATASETS = [
    {
        "label": "1. SOC 2 / Redwood",
        "evidence": [
            ("Redwood_SOC2_System_Description.txt", D1_EV_A),
            ("Redwood_Change_Incident_Management.txt", D1_EV_B),
        ],
        "questions": D1_QUESTIONS,
        "expect_min_drafted": 8,
        "expect_max_insufficient": 2,
    },
    {
        "label": "2. HIPAA / Riverbend",
        "evidence": [
            ("Riverbend_HIPAA_Safeguards.txt", D2_EV_A),
            ("Riverbend_Device_Media_Backup.txt", D2_EV_B),
        ],
        "questions": D2_QUESTIONS,
        "expect_min_drafted": 7,
        "expect_max_insufficient": 3,
    },
    {
        "label": "3. ISO 27001 / Northway",
        "evidence": [
            ("Northway_ISMS_Scope_SoA.txt", D3_EV_A),
            ("Northway_Internal_Audit_MgmtReview.txt", D3_EV_B),
        ],
        "questions": D3_QUESTIONS,
        "expect_min_drafted": 9,
        "expect_max_insufficient": 1,
    },
    {
        "label": "4. NIST CSF 2.0 / Atlas",
        "evidence": [
            ("Atlas_CSF_Profile.txt", D4_EV_A),
            ("Atlas_CSF_Tiers_Improvement.txt", D4_EV_B),
        ],
        "questions": D4_QUESTIONS,
        "expect_min_drafted": 8,
        "expect_max_insufficient": 2,
    },
    {
        "label": "5. NIST 800-53 / FederalEdge",
        "evidence": [
            ("FederalEdge_80053_Controls.txt", D5_EV_A),
            ("FederalEdge_Baseline_Assessment.txt", D5_EV_B),
        ],
        "questions": D5_QUESTIONS,
        "expect_min_drafted": 9,
        "expect_max_insufficient": 1,
    },
    {
        "label": "6. NIST 800-171 / CUIWorks",
        "evidence": [
            ("CUIWorks_CUI_Program.txt", D6_EV_A),
            ("CUIWorks_Auth_CommSec.txt", D6_EV_B),
        ],
        "questions": D6_QUESTIONS,
        "expect_min_drafted": 8,
        "expect_max_insufficient": 2,
    },
    {
        "label": "7. SIG / HarborPay",
        "evidence": [
            ("HarborPay_ThirdPartyRisk.txt", D7_EV_A),
            ("HarborPay_BCDR_Privacy.txt", D7_EV_B),
        ],
        "questions": D7_QUESTIONS,
        "expect_min_drafted": 6,
        "expect_max_insufficient": 4,
    },
    {
        "label": "8. CAIQ / SkyLedger",
        "evidence": [
            ("SkyLedger_Cloud_Security.txt", D8_EV_A),
            ("SkyLedger_CSA_STAR_Assessment.txt", D8_EV_B),
        ],
        "questions": D8_QUESTIONS,
        "expect_min_drafted": 8,
        "expect_max_insufficient": 2,
    },
    {
        "label": "9. Negative: Generic Vendor",
        "evidence": [("BrightOps_Security_Overview.txt", D9_EV_A)],
        "questions": D9_QUESTIONS,
        "expect_min_drafted": 5,
        "expect_max_insufficient": 3,
    },
    {
        "label": "10. Negative: Healthcare (no HIPAA)",
        "evidence": [("CareBridge_Security_Note.txt", D10_EV_A)],
        "questions": D10_QUESTIONS,
        "expect_min_drafted": 3,
        "expect_max_insufficient": 3,
    },
]


def main():
    print("=" * 70)
    print("  TRUST COPILOT — 10-DATASET FRAMEWORK CLASSIFICATION VALIDATION")
    print("=" * 70)

    results = []
    for ds in ALL_DATASETS:
        r = run_dataset(ds["label"], ds["evidence"], ds["questions"])
        r["expect_min_drafted"] = ds["expect_min_drafted"]
        r["expect_max_insufficient"] = ds["expect_max_insufficient"]
        results.append(r)

    print("\n" + "=" * 70)
    print("  FINAL RESULTS")
    print("=" * 70)

    checks: list[tuple[str, bool]] = []
    all_pass = True

    for r in results:
        status = "PASS" if r["job_status"] == "completed" else "FAIL"
        if r["job_status"] != "completed":
            all_pass = False
        print(f"  [{status}] {r['name']}: {r['drafted']} drafted, {r['insufficient']} insufficient, {r['generation_time_s']}s")

        fw_summary = "; ".join(f"doc {did}: {fws}" for did, fws in r.get("doc_frameworks", {}).items())
        if fw_summary:
            print(f"        Frameworks: {fw_summary}")

        label = r["name"]
        min_d = r["expect_min_drafted"]
        max_i = r["expect_max_insufficient"]

        drafted_ok = r["drafted"] >= min_d
        checks.append((f"{label}: >= {min_d} drafted (got {r['drafted']})", drafted_ok))
        if not drafted_ok:
            all_pass = False

        completed_ok = r["job_status"] == "completed"
        checks.append((f"{label}: job completed", completed_ok))
        if not completed_ok:
            all_pass = False

    print(f"\n  Validation checks ({len(checks)}):")
    for label, passed in checks:
        print(f"    {'PASS' if passed else 'FAIL'}: {label}")

    verdict = "ALL PASS" if all_pass else "SOME FAILURES"
    print(f"\n  VERDICT: {verdict}")
    print("=" * 70)

    with open("test_results_10ds.json", "w") as f:
        json.dump(results, f, indent=2)
    print("  Results saved to test_results_10ds.json")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
