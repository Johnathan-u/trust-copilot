"""Manual live-API check against a LOCAL stack (not a pytest test; TC-07-001).

Usage: TC_SESSION_SECRET=... python tests/test_alerts_api.py
"""

import requests

try:  # run as `python tests/<script>.py` or as `python -m tests.<script>`
    from _live_session import forge_session_cookie, live_api
except ImportError:  # pragma: no cover
    from tests._live_session import forge_session_cookie, live_api

__test__ = False  # never collected as a test module


def main() -> None:
    API = live_api()
    S = requests.Session()
    S.cookies.set("tc_session", forge_session_cookie(33))

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
            print(f"  {p['event_type']}: {'Active' if p['enabled'] else 'Disabled'} -> {p['recipient_type']}")

    print("\n=== Delivery Log ===")
    r = S.get(f"{API}/api/notifications/log?page=1&page_size=5")
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"  Total: {data.get('total', 0)}")
        for e in data.get("entries", []):
            print(f"  {e['event_type']} -> {e['recipient_email']} ({e['status']})")


if __name__ == "__main__":
    main()
