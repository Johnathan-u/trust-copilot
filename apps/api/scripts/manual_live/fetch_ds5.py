"""Manual fetch against a LOCAL running API (see README.md). Not a pytest module."""
import json

import requests

from _live_guard import api_base, forge_session_cookie

API = api_base()


def cookie(ws_id):
    return forge_session_cookie(ws_id)

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
