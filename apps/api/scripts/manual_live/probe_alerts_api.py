"""Manual probe against a LOCAL running API (see README.md). Not a pytest module."""

import json  # noqa: F401
import os

import requests

from _live_guard import api_base, forge_session_cookie

API = api_base()
cookie = forge_session_cookie(int(os.environ.get("TC_WORKSPACE_ID", "1")))

S = requests.Session()
S.cookies.set("tc_session", cookie)

print("=== Active Alerts ===")
r = S.get(f"{API}/api/compliance-alerts/active")
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    alerts = data.get("alerts", [])
    if not alerts:
        print("  No active alerts (healthy)")
    for a in alerts:
        print(f"  [{a['severity'].upper()}] {a['title']}: {a['description']}")

print("\n=== Event Types ===")
r = S.get(f"{API}/api/notifications/event-types")
print(f"Status: {r.status_code}")
if r.status_code == 200:
    for et in r.json().get("event_types", []):
        print(f"  {et}")

print("\n=== Policies ===")
r = S.get(f"{API}/api/notifications/policies")
print(f"Status: {r.status_code}")
if r.status_code == 200:
    for p in r.json().get("policies", []):
        print(
            f"  {p['event_type']}: {'Active' if p['enabled'] else 'Disabled'} -> {p['recipient_type']}"
        )

print("\n=== Delivery Log ===")
r = S.get(f"{API}/api/notifications/log?page=1&page_size=5")
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json()
    print(f"  Total: {data.get('total', 0)}")
    for e in data.get("entries", []):
        print(f"  {e['event_type']} -> {e['recipient_email']} ({e['status']})")
