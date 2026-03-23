"""
Deep audit: check actual data shapes from API and DB to determine
what the pipeline actually produces.
"""
import json, sys, requests

BASE = "http://localhost:8000"
S = requests.Session()

def login():
    r = S.post(f"{BASE}/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    return r.json()

def section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

login()

# 1. Check raw question/answer data shape
section("RAW QUESTION/ANSWER DATA SHAPE")
ws = S.get(f"{BASE}/api/workspaces/current").json()
ws_id = ws["id"]

qnrs = S.get(f"{BASE}/api/questionnaires/?workspace_id={ws_id}").json()
# Pick a questionnaire with answers
for q in qnrs:
    qid = q["id"]
    detail = S.get(f"{BASE}/api/questionnaires/{qid}?workspace_id={ws_id}").json()
    questions = detail.get("questions", [])
    # Find a question with an answer
    for question in questions:
        has_answer = False
        for key in ["answer", "ai_answer", "generated_answer", "draft_answer"]:
            if question.get(key):
                has_answer = True
                break
        if has_answer or question.get("status") == "draft":
            print(f"\nQuestionnaire #{qid}, Question sample:")
            print(f"  Question keys: {list(question.keys())}")
            # Print full question (truncate long values)
            for k, v in question.items():
                val_str = str(v)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                print(f"    {k}: {val_str}")
            break
    else:
        continue
    break

# 2. Check answer stats shape in detail
section("ANSWER STATS DEEP INSPECTION")
for qid in [qnrs[0]["id"]]:
    r = S.get(f"{BASE}/api/ai-governance/questionnaire-answer-stats/{qid}")
    if r.status_code == 200:
        data = r.json()
        print(f"  Full stats response for QNR #{qid}:")
        print(json.dumps(data, indent=2, default=str)[:2000])

# 3. Check compliance coverage shape in detail
section("COMPLIANCE COVERAGE DEEP INSPECTION")
r = S.get(f"{BASE}/api/compliance-coverage")
if r.status_code == 200:
    data = r.json()
    print("  Top-level keys:", list(data.keys()))
    print()
    for key in data.keys():
        val = data[key]
        if isinstance(val, list):
            print(f"  {key}: {len(val)} items")
            if val:
                print(f"    First item: {json.dumps(val[0], default=str)[:300]}")
        elif isinstance(val, dict):
            print(f"  {key}: {json.dumps(val, default=str)[:300]}")
        else:
            print(f"  {key}: {val}")
        print()

# 4. Check AI governance settings shape
section("AI GOVERNANCE SETTINGS SHAPE")
r = S.get(f"{BASE}/api/ai-governance/settings")
if r.status_code == 200:
    data = r.json()
    print(json.dumps(data, indent=2, default=str)[:1500])

# 5. Check notification event types shape
section("NOTIFICATION EVENT TYPES SHAPE")
r = S.get(f"{BASE}/api/notifications/event-types")
if r.status_code == 200:
    data = r.json()
    print(json.dumps(data, indent=2, default=str)[:1500])

# 6. Check dashboard cards shape
section("DASHBOARD CARDS SHAPE")
r = S.get(f"{BASE}/api/dashboard/cards")
if r.status_code == 200:
    data = r.json()
    print(json.dumps(data, indent=2, default=str)[:2000])

# 7. Check exports shape
section("EXPORTS SHAPE")
r = S.get(f"{BASE}/api/exports/records?workspace_id={ws_id}")
if r.status_code == 200:
    data = r.json()
    if isinstance(data, list) and data:
        print(f"  {len(data)} exports")
        print(f"  First export keys: {list(data[0].keys())}")
        print(f"  First export: {json.dumps(data[0], indent=2, default=str)[:500]}")
