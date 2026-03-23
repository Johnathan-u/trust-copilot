import base64, hmac, json
import requests

SECRET = "zDWud8xGEkOl_7ceEhfvrGeTNehTp3ttPHo9uYEcCGoyZUOlYvYBCiDHjp1stF_0"
p = {"user_id": 1, "email": "reinhartjm294@gmail.com", "workspace_id": 33, "role": "admin"}
d = base64.urlsafe_b64encode(json.dumps(p).encode()).decode()
s = hmac.new(SECRET.encode(), d.encode(), "sha256").hexdigest()
cookie = f"{d}.{s}"

S = requests.Session()
S.cookies.set("tc_session", cookie)
r = S.get("http://localhost:8000/api/compliance-coverage")
print(f"Status: {r.status_code}")

if r.status_code != 200:
    print(r.text[:500])
else:
    data = r.json()
    kpi = data.get("kpi", {})
    print(f"\n=== KPI Cards ===")
    print(f"  Total Questions: {kpi.get('total_questions')}")
    print(f"  Total Drafted:   {kpi.get('total_drafted')}")
    print(f"  Insufficient:    {kpi.get('total_insufficient')}")
    print(f"  Coverage:        {kpi.get('coverage_pct')}%")
    print(f"  High Confidence: {kpi.get('high_confidence_pct')}%")
    print(f"  Insufficient:    {kpi.get('insufficient_pct')}%")
    print(f"  Blind Spots:     {kpi.get('blind_spot_count')}")

    print(f"\n=== Framework Coverage ({len(data.get('framework_coverage', []))}) ===")
    for fc in data.get("framework_coverage", []):
        print(f"  {fc['framework']}: {fc['coverage_pct']}% ({fc['drafted']}/{fc['total']} drafted, {fc['insufficient']} insufficient)")

    print(f"\n=== Blind Spots ({len(data.get('blind_spots', []))}) ===")
    for bs in data.get("blind_spots", []):
        print(f"  {bs['subject']}: {bs['insufficient_count']} insufficient / {bs['total']} total")

    print(f"\n=== Weak Areas ({len(data.get('weak_areas', []))}) ===")
    for wa in data.get("weak_areas", []):
        print(f"  {wa['subject']}: avg confidence {wa['avg_confidence']}% ({wa['count']} answers)")

    print(f"\n=== Evidence Strength ({len(data.get('evidence_strength', []))}) ===")
    for es in data.get("evidence_strength", []):
        print(f"  {es['subject']}: avg {es['avg_evidence_count']} citations ({es['total_answers']} answers)")

    print(f"\n=== Recommended Evidence ({len(data.get('recommended_evidence', []))}) ===")
    for re_item in data.get("recommended_evidence", []):
        print(f"  {re_item['title']} -> improves {re_item['improves_questions']} questions")

    print(f"\n=== Trends ({len(data.get('trends', []))}) ===")
    for t in data.get("trends", [])[-5:]:
        print(f"  {t['date']}: coverage={t['coverage_pct']}% insuff={t['insufficient_pct']}%")

    print(f"\n=== Drill-Down ({len(data.get('drill_down', []))}) ===")
    for dd in data.get("drill_down", [])[:10]:
        print(f"  {dd['subject']} / {dd['framework']}: {dd['answered']}/{dd['questions_seen']} answered, {dd['insufficient']} insuff")
