import base64, hmac, json
import requests

SECRET = "zDWud8xGEkOl_7ceEhfvrGeTNehTp3ttPHo9uYEcCGoyZUOlYvYBCiDHjp1stF_0"
p = {"user_id": 1, "email": "reinhartjm294@gmail.com", "workspace_id": 33, "role": "admin"}
d = base64.urlsafe_b64encode(json.dumps(p).encode()).decode()
s = hmac.new(SECRET.encode(), d.encode(), "sha256").hexdigest()
cookie = f"{d}.{s}"

S = requests.Session()
S.cookies.set("tc_session", cookie)

print("=== Active Alerts ===")
r = S.get("http://localhost:8000/api/compliance-alerts/active")
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    alerts = data.get("alerts", [])
    if not alerts:
        print("  No active alerts (healthy)")
    for a in alerts:
        print(f"  [{a['severity'].upper()}] {a['title']}: {a['description']}")

print("\n=== Event Types ===")
r = S.get("http://localhost:8000/api/notifications/event-types")
print(f"Status: {r.status_code}")
if r.status_code == 200:
    for et in r.json().get("event_types", []):
        print(f"  {et}")

print("\n=== Policies ===")
r = S.get("http://localhost:8000/api/notifications/policies")
print(f"Status: {r.status_code}")
if r.status_code == 200:
    for p in r.json().get("policies", []):
        print(f"  {p['event_type']}: {'Active' if p['enabled'] else 'Disabled'} -> {p['recipient_type']}")

print("\n=== Delivery Log ===")
r = S.get("http://localhost:8000/api/notifications/log?page=1&page_size=5")
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    print(f"  Total: {data.get('total', 0)}")
    for e in data.get("entries", []):
        print(f"  {e['event_type']} -> {e['recipient_email']} ({e['status']})")
