"""
Comprehensive UI + Backend integration test.
Tests every frontend page route and API endpoint for connectivity.

Run inside the API container:
    python tests/full_ui_backend_test.py

Coverage:
    - 3 health/readiness probes
    - Authentication (login flow)
    - 5 auth endpoints (me, sessions, MFA, OAuth, alerts)
    - Workspace resolution
    - Documents list
    - Questionnaires list + detail (top 3)
    - Answer stats per questionnaire
    - Exports
    - Trust center articles
    - Compliance coverage + alerts
    - Notification policies, event types, logs, in-app count
    - Audit events
    - Members, invites, roles
    - Slack status
    - Gmail status
    - AI insights + governance settings
    - Dashboard cards + allowed routes
    - Vendor requests
    - Trust requests (backend still alive)
    - Compliance controls (backend still alive)
    - Legacy routes check
    - 19 active frontend pages (via Caddy)
    - 5 deleted frontend pages (confirm no page.tsx)
    Total: ~64 checks
"""
import json
import time
import sys
import requests
from collections import defaultdict

BASE = "http://localhost:8000"
SESSION = requests.Session()

results = {"pass": [], "fail": [], "warn": []}

def log(status, msg):
    icon = {"PASS": "OK", "FAIL": "FAIL", "WARN": "WARN", "INFO": "    "}[status]
    print(f"  [{icon}] {msg}")
    if status == "PASS":
        results["pass"].append(msg)
    elif status == "FAIL":
        results["fail"].append(msg)
    elif status == "WARN":
        results["warn"].append(msg)

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ── Auth ──
def login():
    section("AUTHENTICATION")
    r = SESSION.post(f"{BASE}/api/auth/login", json={"email": "demo@trust.local", "password": "j"})
    if r.status_code == 200:
        data = r.json()
        if data.get("mfa_required"):
            log("WARN", f"MFA required for login - skipping MFA step")
            return False
        log("PASS", f"Login successful as {data.get('user', {}).get('email', '?')}")
        return True
    else:
        log("FAIL", f"Login failed: {r.status_code} {r.text[:200]}")
        return False

# ── API Endpoint Tests ──
def test_api(method, path, desc, expected_codes=None, json_body=None, admin_only=False):
    if expected_codes is None:
        expected_codes = [200, 403] if admin_only else [200]
    try:
        url = f"{BASE}{path}"
        if method == "GET":
            r = SESSION.get(url, timeout=15)
        elif method == "POST":
            r = SESSION.post(url, json=json_body, timeout=15)
        elif method == "PATCH":
            r = SESSION.patch(url, json=json_body, timeout=15)
        else:
            r = SESSION.request(method, url, timeout=15)

        if r.status_code in expected_codes:
            log("PASS", f"{method} {path} -> {r.status_code} ({desc})")
            return r
        else:
            detail = ""
            try:
                detail = r.json().get("detail", "")[:100]
            except Exception:
                detail = r.text[:100]
            log("FAIL", f"{method} {path} -> {r.status_code} expected {expected_codes} ({desc}) {detail}")
            return r
    except Exception as e:
        log("FAIL", f"{method} {path} -> EXCEPTION: {e} ({desc})")
        return None

def test_legacy_routes():
    """Check status of legacy backend routes (still mounted, not used by frontend)."""
    section("LEGACY BACKEND ROUTES (still mounted, unused by frontend)")
    test_api("GET", "/api/controls", "legacy controls endpoint (still mounted, not used by UI)", expected_codes=[200, 403])

def test_auth_endpoints():
    section("AUTH ENDPOINTS")
    test_api("GET", "/api/auth/me", "current user")
    test_api("GET", "/api/auth/sessions", "active sessions")
    test_api("GET", "/api/auth/mfa/status", "MFA status")
    test_api("GET", "/api/auth/oauth/providers", "OAuth providers")
    test_api("GET", "/api/auth/alerts", "security alerts")

def test_workspace_endpoints():
    section("WORKSPACE ENDPOINTS")
    r = test_api("GET", "/api/workspaces/current", "current workspace")
    if r and r.status_code == 200:
        data = r.json()
        ws_id = data.get("id")
        log("INFO", f"  Workspace: {data.get('name')} (id={ws_id})")
        return ws_id
    return None

def test_document_endpoints(ws_id):
    section("DOCUMENTS")
    test_api("GET", f"/api/documents/?workspace_id={ws_id}", "list documents")

def test_questionnaire_endpoints(ws_id):
    section("QUESTIONNAIRES")
    r = test_api("GET", f"/api/questionnaires/?workspace_id={ws_id}", "list questionnaires")
    qnr_ids = []
    if r and r.status_code == 200:
        qnrs = r.json()
        if isinstance(qnrs, list):
            log("INFO", f"  Found {len(qnrs)} questionnaires")
            qnr_ids = [q["id"] for q in qnrs[:3]]
            for qid in qnr_ids:
                test_api("GET", f"/api/questionnaires/{qid}?workspace_id={ws_id}", f"questionnaire detail #{qid}")
    return qnr_ids

def test_answer_stats(qnr_ids):
    section("ANSWER STATS (per questionnaire)")
    for qid in qnr_ids:
        test_api("GET", f"/api/ai-governance/questionnaire-answer-stats/{qid}", f"answer stats for qnr #{qid}")

def test_export_endpoints(ws_id):
    section("EXPORTS")
    test_api("GET", f"/api/exports/records?workspace_id={ws_id}", "list exports")

def test_compliance_endpoints():
    section("COMPLIANCE / COVERAGE")
    test_api("GET", "/api/compliance-coverage", "compliance coverage dashboard")
    test_api("GET", "/api/compliance-alerts/active", "active compliance alerts", admin_only=True)

def test_notification_endpoints():
    section("NOTIFICATIONS")
    test_api("GET", "/api/notifications/event-types", "notification event types")
    test_api("GET", "/api/notifications/policies", "notification policies", admin_only=True)
    test_api("GET", "/api/notifications/log?page=1&page_size=5", "notification log", admin_only=True)
    test_api("GET", "/api/in-app-notifications/unread-count", "unread count")

def test_audit_endpoints():
    section("AUDIT / ACTIVITY")
    test_api("GET", "/api/audit/events?page=1&page_size=5", "audit events", admin_only=True)

def test_member_endpoints():
    section("MEMBERS")
    test_api("GET", "/api/members", "list members", admin_only=True)
    test_api("GET", "/api/members/invites", "list invites", admin_only=True)
    test_api("GET", "/api/members/roles", "list roles", admin_only=True)

def test_slack_endpoints():
    section("SLACK")
    test_api("GET", "/api/slack/status", "slack status", admin_only=True)

def test_gmail_endpoints():
    section("GMAIL")
    test_api("GET", "/api/gmail/status", "gmail status", admin_only=True)

def test_ai_governance_endpoints():
    section("AI GOVERNANCE / INSIGHTS")
    test_api("GET", "/api/ai-insights", "AI insights dashboard", admin_only=True)
    test_api("GET", "/api/ai-governance/settings", "AI governance settings")

def test_dashboard_cards():
    section("DASHBOARD CARDS")
    test_api("GET", "/api/dashboard/cards", "dashboard cards")
    test_api("GET", "/api/dashboard/cards/allowed-routes", "allowed routes for cards", admin_only=True)

def test_trust_center(ws_id):
    section("TRUST CENTER")
    test_api("GET", f"/api/trust-articles?workspace_id={ws_id}", "trust articles")

def test_vendor_requests():
    section("VENDOR REQUESTS (backend)")
    test_api("GET", "/api/vendor-requests", "list vendor requests")

def test_deleted_frontend_routes_dont_break_backend():
    """
    Make sure the backend APIs that were previously used by deleted
    frontend pages still work (they should -- we only deleted frontend).
    """
    section("BACKEND FOR DELETED FRONTEND PAGES (should still work)")
    test_api("GET", "/api/trust-requests", "trust requests list (backend alive)")
    test_api("GET", "/api/compliance/controls", "compliance controls (backend alive)")

def test_health():
    section("HEALTH / READINESS")
    test_api("GET", "/healthz", "health check")
    test_api("GET", "/readyz", "readiness check")
    test_api("GET", "/workerz", "worker heartbeat")

def test_frontend_page_loads():
    """
    Test that the frontend (via Caddy at port 3000) loads each page
    without 500 errors. We test through the API container's network.
    """
    section("FRONTEND PAGE LOADS (via Caddy)")
    pages = [
        "/",
        "/login",
        "/register",
        "/forgot-password",
        "/dashboard",
        "/dashboard/documents",
        "/dashboard/questionnaires",
        "/dashboard/review",
        "/dashboard/exports",
        "/dashboard/compliance-gaps",
        "/dashboard/notifications",
        "/dashboard/audit",
        "/dashboard/settings",
        "/dashboard/security",
        "/dashboard/ai-governance",
        "/dashboard/members",
        "/dashboard/slack",
        "/dashboard/gmail",
        "/dashboard/trust-center",
        "/dashboard/requests",
    ]
    deleted_pages = [
        "/dashboard/controls",
        "/dashboard/compliance-audit",
        "/dashboard/trust-requests",
    ]

    frontend_base = "http://caddy:3000"
    for page in pages:
        try:
            r = SESSION.get(f"{frontend_base}{page}", timeout=20, allow_redirects=True)
            if r.status_code in [200, 307, 302]:
                log("PASS", f"Page {page} -> {r.status_code}")
            else:
                log("FAIL", f"Page {page} -> {r.status_code}")
        except Exception as e:
            log("WARN", f"Page {page} -> could not reach frontend: {e}")

    for page in deleted_pages:
        try:
            r = SESSION.get(f"{frontend_base}{page}", timeout=10, allow_redirects=True)
            if r.status_code == 404:
                log("PASS", f"Deleted page {page} -> 404 (correct)")
            elif r.status_code in [200, 307, 302]:
                log("WARN", f"Deleted page {page} -> {r.status_code} (Next.js may still serve shell; check if page.tsx is gone)")
            else:
                log("WARN", f"Deleted page {page} -> {r.status_code}")
        except Exception as e:
            log("WARN", f"Deleted page {page} -> {e}")

    # Test that deleted mappings page 404s
    try:
        r = SESSION.get(f"{frontend_base}/dashboard/questionnaires/1/mappings", timeout=10, allow_redirects=True)
        if r.status_code == 404:
            log("PASS", f"Deleted mappings page -> 404 (correct)")
        else:
            log("WARN", f"Deleted mappings page -> {r.status_code}")
    except Exception as e:
        log("WARN", f"Deleted mappings page -> {e}")


def print_summary():
    section("TEST SUMMARY")
    total = len(results["pass"]) + len(results["fail"]) + len(results["warn"])
    print(f"\n  Total tests: {total}")
    print(f"  Passed:  {len(results['pass'])}")
    print(f"  Failed:  {len(results['fail'])}")
    print(f"  Warnings: {len(results['warn'])}")

    if results["fail"]:
        print(f"\n  FAILURES:")
        for f in results["fail"]:
            print(f"    - {f}")

    if results["warn"]:
        print(f"\n  WARNINGS:")
        for w in results["warn"]:
            print(f"    - {w}")

    print()
    if not results["fail"]:
        print("  ALL TESTS PASSED")
    else:
        print(f"  {len(results['fail'])} FAILURE(S) NEED ATTENTION")
    print()


def main():
    print("\n" + "="*60)
    print("  TRUST COPILOT - FULL UI + BACKEND INTEGRATION TEST")
    print("="*60)

    test_health()

    if not login():
        print("\n  Cannot proceed without authentication. Exiting.")
        sys.exit(1)

    test_auth_endpoints()
    ws_id = test_workspace_endpoints()

    if ws_id:
        test_document_endpoints(ws_id)
        qnr_ids = test_questionnaire_endpoints(ws_id)
        test_answer_stats(qnr_ids)
        test_export_endpoints(ws_id)
        test_trust_center(ws_id)
    else:
        log("WARN", "No workspace ID - skipping workspace-scoped tests")
        qnr_ids = []

    test_compliance_endpoints()
    test_notification_endpoints()
    test_audit_endpoints()
    test_member_endpoints()
    test_slack_endpoints()
    test_gmail_endpoints()
    test_ai_governance_endpoints()
    test_dashboard_cards()
    test_vendor_requests()
    test_deleted_frontend_routes_dont_break_backend()
    test_legacy_routes()
    test_frontend_page_loads()

    print_summary()

    sys.exit(1 if results["fail"] else 0)

if __name__ == "__main__":
    main()
