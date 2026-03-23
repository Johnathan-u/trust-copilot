# Auth & Access — Single Source of Truth

**The diagrams in this folder are the canonical vision for Trust Copilot authentication and authorization.** All other docs and the backlog are aligned to this vision.

- **auth.md** — Tiered model, security controls (AUTH-04–09, SESS-01, SEC-02), implementation order. *Elaborates policy and backend/frontend work; defers flow to these diagrams.*
- **auth-workflow.md** — Narrative and Mermaid sequences for login, reset, invite, workspace switch, request lifecycle. *Must match the flows shown in the diagrams below.*
- **baclog.md** — Sprints 11–13 (Auth & Access). *Every diagram node/decision has a corresponding ticket or is covered by an existing ticket.*

---

## Diagram index

| File | Scope | What it defines |
|------|--------|------------------|
| **mermaid-diagram (1).png** | App-level auth flow | Open app → AuthProvider checks `GET /api/auth/me` → Authenticated? → (Yes) Load user + workspace + permissions → Protected app, with Workspace switch and Logout; (No) Login/Register/Invite/Reset → Login submit → MFA required? → MFA screen or direct → Load user + workspace + permissions. |
| **mermaid-diagram.png** | Detailed auth + Public vs Inside App | App loads → AuthProvider boots → `GET /api/auth/me` → Authenticated? → (Yes) Load auth context (user, workspace, role, permissions) → Protected app routes → **Route allowed?** → 403 Forbidden or **Inside App** (dashboard, workspace switcher, security page, logout). (No) **Public Auth**: Register, Forgot password, Reset password, Login, Accept invite. Post–login/invite: Login response / Valid token? → **Requires MFA?** → MFA challenge or set password/accept invite → Refresh auth context → `GET /api/auth/me` → Redirect to dashboard/intended route. |

---

## Enterprise-grade checklist (from diagrams)

- [x] AuthProvider + `GET /api/auth/me` as single source of auth state
- [x] Authenticated? branch → Load user + workspace + permissions before protected app
- [x] **Route allowed?** → 403 Forbidden when role/route not allowed
- [x] Public auth: Register, Login, Forgot password, Reset password, Accept invite
- [x] MFA required? → MFA challenge (TOTP / recovery) before session
- [x] Workspace switcher → POST switch-workspace → Refresh auth context → Reload app data
- [x] Security page: View sessions/devices, Sign out other sessions, Enable/manage MFA
- [x] Logout → POST logout → Clear auth context → Back to public auth
- [x] Generic error messages (no enumeration); explicit error paths (invalid login, expired invite, MFA error)

When adding or changing auth behaviour, update the diagrams first, then sync auth.md, auth-workflow.md, and backlog to match.

---

## Diagram → Backlog mapping (Sprints 11–13)

| Diagram element | Backlog ticket(s) |
|-----------------|--------------------|
| AuthProvider boots / GET /api/auth/me | AUTH-203, WEB-201 |
| Load user + workspace + permissions / auth context | AUTH-203, WEB-201, WEB-202 |
| Protected app routes / Route allowed? / 403 | AUTH-205, WEB-204, guards in auth.md |
| Login submit, Login response, Invalid → generic error | AUTH-201, AUTH-210, WEB-207 (reset) |
| MFA required? → MFA screen / TOTP or recovery | AUTH-211, AUTH-212, WEB-208, WEB-209 |
| Register, verify email, Login page | AUTH-207, WEB-205 |
| Forgot password, Reset password, success → Login | AUTH-209, WEB-207 |
| Accept invite, Valid token?, Set password / confirm | AUTH-208, WEB-206 |
| Workspace switcher, POST switch-workspace, Refresh context | AUTH-204, WEB-203 |
| Security page: sessions/devices, Sign out others, MFA | AUTH-213, AUTH-214, WEB-210, WEB-211, WEB-208 |
| Logout, POST logout, Clear auth context | Existing logout; SESS-201 for revocation |
