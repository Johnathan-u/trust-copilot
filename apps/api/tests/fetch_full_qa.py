import base64, hmac, json
import requests

API = "http://localhost:8000"
SECRET = "zDWud8xGEkOl_7ceEhfvrGeTNehTp3ttPHo9uYEcCGoyZUOlYvYBCiDHjp1stF_0"

def cookie(ws_id):
    p = {"user_id":1,"email":"reinhartjm294@gmail.com","workspace_id":ws_id,"role":"admin"}
    d = base64.urlsafe_b64encode(json.dumps(p).encode()).decode()
    s = hmac.new(SECRET.encode(),d.encode(),"sha256").hexdigest()
    return f"{d}.{s}"

datasets = [
    ("1. SOC 2 / Redwood", 33, 185),
    ("2. HIPAA / Riverbend", 34, 186),
    ("3. ISO 27001 / Northway", 35, 187),
    ("4. NIST CSF 2.0 / Atlas", 36, 188),
    ("5. NIST 800-53 / FederalEdge", 37, 189),
    ("6. NIST 800-171 / CUIWorks", 38, 190),
    ("7. SIG / HarborPay", 39, 191),
    ("8. CAIQ / SkyLedger", 40, 192),
    ("9. Negative: Generic Vendor", 41, 193),
    ("10. Negative: Healthcare (no HIPAA)", 42, 194),
]

S = requests.Session()
for label, ws_id, qnr_id in datasets:
    S.cookies.set("tc_session", cookie(ws_id))
    r = S.get(f"{API}/api/questionnaires/{qnr_id}", params={"workspace_id": ws_id})
    r.raise_for_status()
    data = r.json()
    qs = data.get("questions", [])
    drafted = sum(1 for q in qs if q.get("answer",{}) and q["answer"].get("status") == "draft")
    insuff = sum(1 for q in qs if q.get("answer",{}) and q["answer"].get("status") == "insufficient_evidence")
    no_ans = len(qs) - drafted - insuff
    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"  {len(qs)} questions | {drafted} drafted | {insuff} insufficient | {no_ans} no_answer")
    print(f"{'='*80}")
    for i, q in enumerate(qs, 1):
        a = q.get("answer")
        st = a.get("status","no_answer") if a else "no_answer"
        txt = a.get("text","") if a else ""
        qtext = q.get("text","")
        tag = "DRAFT" if st == "draft" else "INSUFFICIENT" if st == "insufficient_evidence" else "NO ANSWER"
        print(f"\n  Q{i}. {qtext}")
        print(f"  [{tag}]")
        print(f"  {txt}")
    print()
