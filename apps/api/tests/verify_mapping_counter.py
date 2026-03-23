"""Focused verification: questionnaire mapping counter and full lifecycle.

Run inside Docker:
    docker compose exec api python tests/verify_mapping_counter.py

Tests:
  1. Generate mappings for a questionnaire with questions
  2. Verify mapped_count == rows with preferred_control_id set (not len(mappings))
  3. Approve, reject, edit, regenerate — verify status persistence
  4. Verify mapped_count still matches control-linked rows after workflow
"""
import sys
import uuid
from pathlib import Path

# `python tests/verify_mapping_counter.py` puts tests/ on sys.path[0], which can shadow
# the real `app` package and yield wrong route code (e.g. stale mapped_count). Prefer
# `python -m tests.verify_mapping_counter` from /app, or ensure project root is first.
_api_root = Path(__file__).resolve().parents[1]
_tests_dir = Path(__file__).resolve().parent
if sys.path and Path(sys.path[0]).resolve() == _tests_dir:
    sys.path.insert(0, str(_api_root))

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models.questionnaire import Questionnaire, Question
from app.models.ai_mapping import QuestionMappingPreference

c = TestClient(app, base_url="http://localhost")
H = {"Origin": "http://localhost", "Referer": "http://localhost/"}
PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    status = "PASS" if condition else "FAIL"
    if not condition:
        FAIL += 1
    else:
        PASS += 1
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return condition


# --- Setup ---
r = c.post("/api/auth/login", json={"email": "demo@trust.local", "password": "j"}, headers=H)
assert r.status_code == 200, f"Login failed: {r.text}"

r = c.get("/api/auth/me", headers=H)
ws_id = r.json()["workspace_id"]
print(f"Logged in: workspace_id={ws_id}")

db = SessionLocal()
uid = uuid.uuid4().hex[:8]
qnr = Questionnaire(
    workspace_id=ws_id, filename=f"verify-{uid}.xlsx",
    status="parsed", display_id=f"QNR-V-{uid}",
)
db.add(qnr)
db.commit()
db.refresh(qnr)
for txt in [
    "How do you manage access control for your systems?",
    "What encryption standards do you use for data at rest?",
    "Describe your incident response process.",
]:
    db.add(Question(questionnaire_id=qnr.id, text=txt, section="S1", answer_type="text"))
db.commit()
QNR = qnr.id
db.close()
print(f"Created test QNR id={QNR} with 3 questions\n")

try:
    # --- Test 1: Generate mappings ---
    print("1. Generate mappings")
    r = c.post(f"/api/questionnaires/{QNR}/generate-mappings?workspace_id={ws_id}", headers=H)
    check("generate returns 200", r.status_code == 200, f"got {r.status_code}")
    gen = r.json()
    check("created 3 mappings", gen["created"] == 3, f"created={gen['created']}")
    check("total_questions is 3", gen["total_questions"] == 3)

    # --- Test 2: List mappings and inspect mapped_count ---
    print("\n2. Mapped counter analysis")
    r = c.get(f"/api/questionnaires/{QNR}/mappings?workspace_id={ws_id}", headers=H)
    check("list returns 200", r.status_code == 200)
    data = r.json()
    check("total_questions equals 3", data["total_questions"] == 3)

    mappings = data["mappings"]
    with_control = [m for m in mappings if m["preferred_control_id"] is not None]
    without_control = [m for m in mappings if m["preferred_control_id"] is None]
    print(f"    Rows with a control: {len(with_control)}")
    print(f"    Rows with Control=None: {len(without_control)}")
    check(
        "mapped_count equals rows with preferred_control_id",
        data["mapped_count"] == len(with_control),
        f"mapped_count={data['mapped_count']}, with_control={len(with_control)}",
    )
    print()

    # --- Test 3: Approve ---
    print("3. Approve first mapping")
    m0 = mappings[0]
    r = c.patch(
        f"/api/questionnaires/{QNR}/mappings/{m0['id']}?workspace_id={ws_id}",
        json={"status": "approved"}, headers={**H, "Content-Type": "application/json"},
    )
    check("approve returns 200", r.status_code == 200)
    check("status is approved", r.json()["status"] == "approved")
    check("approved flag is True", r.json()["approved"] is True)

    # --- Test 4: Reject ---
    print("\n4. Reject second mapping")
    m1 = mappings[1]
    r = c.patch(
        f"/api/questionnaires/{QNR}/mappings/{m1['id']}?workspace_id={ws_id}",
        json={"status": "rejected"}, headers={**H, "Content-Type": "application/json"},
    )
    check("reject returns 200", r.status_code == 200)
    check("status is rejected", r.json()["status"] == "rejected")
    check("approved flag is False", r.json()["approved"] is False)

    # --- Test 5: Manual edit ---
    print("\n5. Manual edit third mapping")
    m2 = mappings[2]
    r = c.patch(
        f"/api/questionnaires/{QNR}/mappings/{m2['id']}?workspace_id={ws_id}",
        json={"status": "manual", "preferred_control_id": 0},
        headers={**H, "Content-Type": "application/json"},
    )
    check("manual edit returns 200", r.status_code == 200)
    check("status is manual", r.json()["status"] == "manual")
    check("approved flag is True", r.json()["approved"] is True)

    # --- Test 6: Regenerate single ---
    print("\n6. Regenerate second mapping (was rejected)")
    r = c.post(
        f"/api/questionnaires/{QNR}/mappings/{m1['id']}/regenerate?workspace_id={ws_id}",
        headers=H,
    )
    check("regenerate returns 200", r.status_code == 200)
    check("status reset to suggested", r.json()["status"] == "suggested")
    check("source is ai", r.json()["source"] == "ai")

    # --- Test 7: Bulk regenerate protects approved/manual ---
    print("\n7. Bulk regenerate — protected statuses")
    r = c.post(f"/api/questionnaires/{QNR}/generate-mappings?workspace_id={ws_id}", headers=H)
    regen = r.json()
    check("bulk regen returns 200", r.status_code == 200)
    check("skipped 2 (approved + manual)", regen["skipped"] == 2, f"skipped={regen['skipped']}")
    check("updated 1 (the suggested one)", regen["updated"] == 1, f"updated={regen['updated']}")

    # --- Test 8: Persistence after reload ---
    print("\n8. Persistence — reload mappings")
    r = c.get(f"/api/questionnaires/{QNR}/mappings?workspace_id={ws_id}", headers=H)
    check("reload returns 200", r.status_code == 200)
    reloaded = {m["id"]: m["status"] for m in r.json()["mappings"]}
    check("first stays approved", reloaded[m0["id"]] == "approved")
    check("second is suggested (was regenerated)", reloaded[m1["id"]] == "suggested")
    check("third stays manual", reloaded[m2["id"]] == "manual")

    # --- Test 9: mapped_count matches control-linked rows after workflow ---
    print("\n9. Mapped counter vs control-linked rows")
    final = r.json()
    expected = sum(1 for m in final["mappings"] if m["preferred_control_id"] is not None)
    check(
        "mapped_count matches rows with preferred_control_id",
        final["mapped_count"] == expected,
        f"mapped_count={final['mapped_count']}, expected={expected}",
    )

    # --- Test 10: Invalid status ---
    print("\n10. Validation")
    r = c.patch(
        f"/api/questionnaires/{QNR}/mappings/{m0['id']}?workspace_id={ws_id}",
        json={"status": "bogus"}, headers={**H, "Content-Type": "application/json"},
    )
    check("invalid status returns 400", r.status_code == 400)

    r = c.patch(
        f"/api/questionnaires/{QNR}/mappings/99999?workspace_id={ws_id}",
        json={"status": "approved"}, headers={**H, "Content-Type": "application/json"},
    )
    check("not-found mapping returns 404", r.status_code == 404)

finally:
    # --- Cleanup (fresh session; setup session was closed before HTTP) ---
    _dbc = SessionLocal()
    try:
        _dbc.query(QuestionMappingPreference).filter(
            QuestionMappingPreference.questionnaire_id == QNR
        ).delete()
        _dbc.query(Question).filter(Question.questionnaire_id == QNR).delete()
        _dbc.query(Questionnaire).filter(Questionnaire.id == QNR).delete()
        _dbc.commit()
    finally:
        _dbc.close()
    print("\nCleanup done.")

print(f"\n{'='*50}")
print(f"RESULTS: {PASS} passed, {FAIL} failed")
if FAIL > 0:
    print("SOME CHECKS FAILED")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
