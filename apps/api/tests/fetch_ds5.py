"""Manual live-API dump against a LOCAL stack (TC-07-001: no embedded secrets).

Usage: TC_SESSION_SECRET=... python tests/fetch_ds5.py
"""

import requests

try:  # run as `python tests/<script>.py` or as `python -m tests.<script>`
    from _live_session import forge_session_cookie, live_api
except ImportError:  # pragma: no cover
    from tests._live_session import forge_session_cookie, live_api

API = live_api()


def cookie(ws_id):
    return forge_session_cookie(ws_id)


S = requests.Session()
S.cookies.set("tc_session", cookie(37))
r = S.get(f"{API}/api/questionnaires/189", params={"workspace_id": 37})
r.raise_for_status()
data = r.json()
print("5. NIST 800-53 / FederalEdge")
print(f"{len(data.get('questions',[]))} questions | all drafted")
print("=" * 60)
for i, q in enumerate(data.get("questions", []), 1):
    a = q.get("answer")
    st = a.get("status", "?") if a else "no_answer"
    txt = a.get("text", "") if a else ""
    print(f"Q{i}. {q.get('text','')}")
    print(f"[{'DRAFT' if st=='draft' else 'INSUFFICIENT' if st=='insufficient_evidence' else st}]")
    print(txt)
    print()
