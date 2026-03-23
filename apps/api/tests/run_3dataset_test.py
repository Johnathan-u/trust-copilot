"""End-to-end 3-dataset validation for Trust Copilot pilot features.

Datasets:
  1. NovaTech SOC 2 (golden path -- expect high draft rate)
  2. MediCore HIPAA (gap detection -- expect high insufficient rate + gaps generated)
  3. Enterprise 150Q (stress test -- expect speed + throughput)

Usage:
  python -u tests/run_3dataset_test.py
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


# ---------------------------------------------------------------------------
# Evidence + Questionnaire payloads
# ---------------------------------------------------------------------------

NOVATECH_EVIDENCE_1 = """NovaTech Security & Infrastructure Policy

NovaTech operates a cloud-native platform hosted primarily in AWS, with secondary failover capability in Microsoft Azure. All production systems are deployed within Virtual Private Clouds (VPCs) with segmented subnets for application, database, and management layers. Network traffic is restricted using security groups and network ACLs. Public access is limited to load balancers and API gateways. Administrative access is restricted via bastion hosts and requires multi-factor authentication. All data in transit is encrypted using TLS 1.2 or higher. Internal service-to-service communication is encrypted using mTLS. Data at rest is encrypted using AES-256 encryption via AWS KMS-managed keys. Access to infrastructure is governed by role-based access control (RBAC) using AWS IAM. Least privilege principles are enforced, and all access is logged and monitored. Logs are centralized in a SIEM system and retained for a minimum of 365 days. Security events are monitored continuously, and alerts are generated for anomalous behavior. Backups are performed daily and stored in geographically separate regions. Backup integrity is tested quarterly."""

NOVATECH_EVIDENCE_2 = """NovaTech Incident Response Policy

NovaTech maintains a formal incident response program designed to detect, respond to, and recover from security incidents. Incidents are categorized by severity (Low, Medium, High, Critical). A dedicated incident response team is responsible for triaging and managing incidents. Detection mechanisms include automated monitoring tools, SIEM alerts, and manual reporting by employees. All incidents are logged in a centralized tracking system. Response procedures include containment, eradication, recovery, and post-incident analysis. Communication protocols ensure stakeholders are notified within defined SLAs. Post-incident reviews are conducted for all high and critical incidents. Lessons learned are documented and used to improve controls and processes. Incident response plans are tested annually through tabletop exercises."""

NOVATECH_QUESTIONS = [
    "Describe your system architecture and hosting environment.",
    "How do you segment your network?",
    "Do you encrypt data at rest? If so, how?",
    "Do you encrypt data in transit?",
    "How is access to infrastructure controlled?",
    "Do you enforce least privilege?",
    "Is multi-factor authentication required for administrative access?",
    "How are logs collected and monitored?",
    "What is your log retention policy?",
    "How do you detect security incidents?",
    "Do you have a formal incident response plan?",
    "How are incidents categorized?",
    "What steps are taken during incident response?",
    "Are post-incident reviews conducted?",
    "How often is your incident response plan tested?",
    "Describe your backup strategy.",
    "How often are backups performed?",
    "Are backups tested?",
    "How do you ensure availability during outages?",
    "What cloud providers do you use?",
    "How do you restrict public access to systems?",
    "Are internal communications encrypted?",
    "How do you monitor anomalous behavior?",
    "Are security alerts generated automatically?",
    "What is your disaster recovery strategy?",
]

MEDICORE_EVIDENCE = """MediCore Security Overview

MediCore provides healthcare data processing services hosted in a secure cloud environment. Access to systems is restricted using role-based access controls. All employees are required to complete annual security awareness training. Systems are monitored for unauthorized access. Data is backed up weekly and stored in secure storage. Logs are retained for 90 days. Incident response procedures exist and include escalation to management."""

MEDICORE_QUESTIONS = [
    "Do you encrypt PHI at rest?",
    "Do you encrypt PHI in transit?",
    "What encryption standards are used?",
    "How do you ensure HIPAA compliance?",
    "Do you conduct risk assessments?",
    "How often are risk assessments performed?",
    "How do you manage access to PHI?",
    "Is multi-factor authentication enforced?",
    "How are audit logs maintained?",
    "How long are audit logs retained?",
    "Do you monitor access to PHI?",
    "How do you detect unauthorized access?",
    "Do you have a breach notification process?",
    "How quickly are breaches reported?",
    "Are incident response plans documented?",
    "Are they tested regularly?",
    "How is employee access revoked?",
    "Are backups encrypted?",
    "How is data integrity ensured?",
    "Do you conduct vulnerability scans?",
]

ENTERPRISE_EVIDENCE_A = """Access Control Policy

Access is managed through centralized identity providers. Users are assigned roles based on job function. Access reviews are conducted quarterly."""

ENTERPRISE_EVIDENCE_B = """Encryption Policy

All sensitive data is encrypted using AES-256 at rest and TLS 1.2 in transit. Keys are managed using a centralized key management service."""

ENTERPRISE_EVIDENCE_C = """Logging & Monitoring

All systems generate logs which are aggregated into a centralized logging platform. Alerts are configured for suspicious activity."""

ENTERPRISE_BASE_QUESTIONS = [
    "How is access controlled?", "Are access reviews conducted?", "How often are access reviews performed?",
    "Is MFA required?", "How is user access revoked?", "Is data encrypted at rest?",
    "What encryption standard is used?", "Is data encrypted in transit?", "How are encryption keys managed?",
    "Are logs collected?", "Where are logs stored?", "How long are logs retained?",
    "Are logs monitored?", "Are alerts configured?", "What triggers alerts?",
    "Are incidents tracked?", "Is there an incident response plan?", "Are incidents categorized?",
    "Are backups performed?", "How often are backups performed?", "Are backups tested?",
    "Is there redundancy?", "How is uptime ensured?", "Are systems segmented?",
    "Are firewalls used?", "Is traffic restricted?", "Are admin actions logged?",
    "Are privileged accounts monitored?", "Is least privilege enforced?", "Are security policies documented?",
    "Are employees trained?", "How often is training conducted?", "Are vulnerability scans performed?",
    "How often?", "Are patches applied?", "How quickly?",
    "Is data integrity validated?", "Are systems audited?", "Are third parties assessed?",
    "Is compliance tracked?",
]

def make_150_questions():
    qs = list(ENTERPRISE_BASE_QUESTIONS)
    suffixes = [" Describe in detail.", " Provide specifics.", " What tools are used?"]
    i = 0
    while len(qs) < 150:
        base = ENTERPRISE_BASE_QUESTIONS[i % len(ENTERPRISE_BASE_QUESTIONS)]
        suffix = suffixes[i % len(suffixes)]
        qs.append(f"{base}{suffix}")
        i += 1
    return qs[:150]


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

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


def generate_answers(ws_id: int, qnr_id: int, doc_ids: list[int]) -> dict:
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
                "citations": a.get("citations"),
            })
        else:
            answers.append({
                "question_id": q["id"],
                "question_text": q.get("text", ""),
                "text": None,
                "status": "no_answer",
                "citations": None,
            })
    return answers


# ---------------------------------------------------------------------------
# Dataset runner
# ---------------------------------------------------------------------------

def run_dataset(name: str, evidence_docs: list[tuple[str, str]], questions: list[str]) -> dict:
    print(f"\n{'='*60}")
    print(f"  DATASET: {name}")
    print(f"  Questions: {len(questions)}, Evidence docs: {len(evidence_docs)}")
    print(f"{'='*60}")

    ws = create_workspace(f"Test - {name} - {int(time.time())}")
    ws_id = ws["id"]
    print(f"  Workspace created: id={ws_id}")

    doc_ids = []
    for fname, content in evidence_docs:
        d = upload_evidence(ws_id, fname, content)
        doc_id = d["id"]
        doc_ids.append(doc_id)
        print(f"  Evidence uploaded: {fname} -> doc_id={doc_id}")

    for doc_id in doc_ids:
        wait_doc_indexed(ws_id, doc_id)
        print(f"  Doc {doc_id} indexed")

    qnr = upload_questionnaire(ws_id, f"{name.replace(' ', '_')}_questionnaire.xlsx", questions)
    qnr_id = qnr["id"]
    print(f"  Questionnaire uploaded: id={qnr_id}")
    wait_qnr_parsed(ws_id, qnr_id)
    print(f"  Questionnaire parsed")

    t_start = time.monotonic()
    gen = generate_answers(ws_id, qnr_id, doc_ids)
    job_id = gen.get("job_id") or gen.get("id")
    print(f"  Generation started: job_id={job_id}")

    job_result = wait_answers_done(ws_id, job_id)
    t_gen = time.monotonic() - t_start
    print(f"  Generation completed in {t_gen:.1f}s (status={job_result.get('status')})")

    answers = get_answers(ws_id, qnr_id)
    drafted = [a for a in answers if a.get("status") == "draft"]
    insufficient = [a for a in answers if a.get("status") == "insufficient_evidence"]
    no_answer = [a for a in answers if a.get("status") == "no_answer"]
    print(f"  Answers: {len(answers)} total, {len(drafted)} drafted, {len(insufficient)} insufficient, {len(no_answer)} no_answer")

    throughput = len(questions) / t_gen if t_gen > 0 else 0
    result = {
        "name": name,
        "workspace_id": ws_id,
        "questionnaire_id": qnr_id,
        "total_questions": len(questions),
        "total_answers": len(answers),
        "drafted": len(drafted),
        "insufficient": len(insufficient),
        "no_answer": len(no_answer),
        "generation_time_s": round(t_gen, 1),
        "throughput_qps": round(throughput, 1),
        "job_status": job_result.get("status"),
    }

    print(f"\n  --- Q&A Summary ({name}) ---")
    for a in answers:
        q_text = a.get("question_text", f"Q#{a.get('question_id')}")
        a_text = (a.get("text") or "(no answer)")[:200]
        status = a.get("status", "?")
        print(f"  [{status:>22}] Q: {q_text[:80]}")
        print(f"                         A: {a_text}")
    print()
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  TRUST COPILOT - 3-DATASET VALIDATION")
    print("=" * 60)

    results = []

    r1 = run_dataset(
        "NovaTech SOC 2",
        [
            ("NovaTech_Security_Infrastructure_Policy.txt", NOVATECH_EVIDENCE_1),
            ("NovaTech_Incident_Response_Policy.txt", NOVATECH_EVIDENCE_2),
        ],
        NOVATECH_QUESTIONS,
    )
    results.append(r1)

    r2 = run_dataset(
        "MediCore HIPAA",
        [("MediCore_Security_Overview.txt", MEDICORE_EVIDENCE)],
        MEDICORE_QUESTIONS,
    )
    results.append(r2)

    r3 = run_dataset(
        "Enterprise 150Q",
        [
            ("Access_Control_Policy.txt", ENTERPRISE_EVIDENCE_A),
            ("Encryption_Policy.txt", ENTERPRISE_EVIDENCE_B),
            ("Logging_Monitoring.txt", ENTERPRISE_EVIDENCE_C),
        ],
        make_150_questions(),
    )
    results.append(r3)

    print("\n" + "=" * 60)
    print("  FINAL RESULTS")
    print("=" * 60)
    all_pass = True
    for r in results:
        status_icon = "PASS" if r["job_status"] == "completed" else "FAIL"
        if r["job_status"] != "completed":
            all_pass = False
        print(f"  [{status_icon}] {r['name']}: {r['drafted']} drafted, {r['insufficient']} insufficient, "
              f"{r['generation_time_s']}s ({r['throughput_qps']} q/s)")

    checks = []
    nt = results[0]
    checks.append(("NovaTech: >= 15 drafted", nt["drafted"] >= 15))
    if nt["drafted"] < 15:
        all_pass = False

    mc = results[1]
    checks.append(("MediCore: >= 8 insufficient", mc["insufficient"] >= 8))
    if mc["insufficient"] < 8:
        all_pass = False

    ent = results[2]
    checks.append(("Enterprise: >= 100 answers", ent["total_answers"] - ent["no_answer"] >= 100))
    if ent["total_answers"] - ent["no_answer"] < 100:
        all_pass = False
    checks.append(("Enterprise: >= 2 q/s throughput", ent["throughput_qps"] >= 2.0))

    print("\n  Validation checks:")
    for label, passed in checks:
        print(f"    {'PASS' if passed else 'FAIL'}: {label}")

    verdict = "ALL PASS" if all_pass else "SOME FAILURES"
    print(f"\n  VERDICT: {verdict}")
    print("=" * 60)

    with open("test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("  Results saved to test_results.json")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
