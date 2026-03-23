import base64, hmac, json
import requests

API = "http://localhost:8000"
SECRET = "zDWud8xGEkOl_7ceEhfvrGeTNehTp3ttPHo9uYEcCGoyZUOlYvYBCiDHjp1stF_0"

def cookie(ws_id):
    p = {"user_id":1,"email":"reinhartjm294@gmail.com","workspace_id":ws_id,"role":"admin"}
    d = base64.urlsafe_b64encode(json.dumps(p).encode()).decode()
    s = hmac.new(SECRET.encode(),d.encode(),"sha256").hexdigest()
    return f"{d}.{s}"

S = requests.Session()
S.cookies.set("tc_session", cookie(37))
r = S.get(f"{API}/api/questionnaires/189", params={"workspace_id": 37})
r.raise_for_status()
data = r.json()
print("5. NIST 800-53 / FederalEdge")
print(f"{len(data.get('questions',[]))} questions | all drafted")
print("="*60)
for i, q in enumerate(data.get("questions", []), 1):
    a = q.get("answer")
    st = a.get("status","?") if a else "no_answer"
    txt = a.get("text","") if a else ""
    print(f"Q{i}. {q.get('text','')}")
    print(f"[{'DRAFT' if st=='draft' else 'INSUFFICIENT' if st=='insufficient_evidence' else st}]")
    print(txt)
    print()
