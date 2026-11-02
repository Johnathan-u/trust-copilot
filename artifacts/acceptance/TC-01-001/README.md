# TC-01-001: Freeze full-suite scope and objective (acceptance evidence)

- Branch: `tc/coord/TC-01-001`, based on `c20f949`
- Deliverable: [`docs/acceptance/scope-freeze.md`](../../../docs/acceptance/scope-freeze.md). The ticket proposes the name `scope-contract.md`; the coordinator brief names this file `scope-freeze.md`. The deliverable is the same.

| AC | How it is met | Evidence |
|---|---|---|
| TC-01-001-AC1: all 94 route modules, 33 pages, background dispatchers, and advertised providers have an owner and acceptance mapping | Generated from package `Traceability.json` (127 rows, 489 operations, all `REQUIRED FOR FULL RELEASE`) and cross-checked against `TrustCopilot_Feature_Scope.md`. Each surface has an owner epic (the epic of its first delivery ticket), all delivery tickets, and security ticket TC-06-005. The doc also lists 15 dispatcher rows found by reading `worker.py`, `main.py` lifespan, and in-process threads, and 24 providers from config, registries, and copy. | `check_scope_freeze.py` and `check_scope_freeze.out.txt` (PASS: 94 route files and 33 page files in the repo all frozen, with no extra rows) |
| TC-01-001-AC2: no feature silently disabled as completion; out-of-scope extensions explicitly listed | Freeze rule 2 and §7 (12 explicit exclusions) | `scope-freeze.md` §2, §7 |

Coordinator rulings R1–R4 are in §8. They are not yet applied to the package backlog JSON, which lives outside this repo.

## Assumptions

- "Owner epic" means the epic of the first delivery ticket listed in Traceability. Multi-epic surfaces list every ticket.
- The dispatcher and provider inventory comes from a static read at baseline. Runtime discovery may add rows through change control.
- Out-of-scope items are a coordinator ruling derived from PRODUCT_SPEC §Scope/§Architecture. The owner can move any of them into scope through `release-decisions.md`.
- Owner/seller signoff is still required for R3 (TC-01-007) and R4 (rights gating).

## Amendment 2026-11-02 (reconciled to master `574f2e2`)

The checker **failed on master before this amendment**, because the freeze had drifted after 2026-10-27:

- 10 page files added by in-scope tickets were missing.
- The frozen `/dashboard/vendor-requests/page.tsx` no longer exists. At baseline it was already a client-side redirect to `/dashboard/requests`; TC-15-024 replaced it with a server redirect (`route.ts`).

After the amendment, `check_scope_freeze.py` passes again: 94 route files and 43 page files in the repo are all frozen with an owner epic and delivery tickets, and all 140 parsed rows exist: 138 surfaces, including the row-22 `route.ts` redirect, now parsed, plus 2 dispatcher rows with repo paths (`check_scope_freeze.out.txt`).

| Change | Where |
|---|---|
| 34 static operations added in 15 existing modules (531 in total). Each is listed with the ticket that added it | `scope-freeze.md` §3 amendment table |
| 10 pages added (rows 35–44). Row 22 now records the vendor-requests server redirect, not a reduction | §4 |
| 4 dispatchers added: job-lease heartbeat, abandoned-job recovery and retries, storage reconcile and orphan sweep (E10), worker liveness heartbeat (TC-03-003) | §5 rows 16–19 |
| No new providers on master. Google Drive and Confluence approved for v1.1 | §6 note |
| §7 items moved into scope by owner decision OD-11, each with its ticket and release | §7 |
| Epics added after the freeze (E31–E37, 123 Jira tickets) mapped to a release, gates and owner decisions | §11 |
| Owner decision OD-11 and coordinator rulings for the amendment and PF-1 | `release-decisions.md` §3, §4 |

**Owner acceptance:** Johnathan Reinhart (Owner/seller), 2026-11-02. The owner confirmed on 2026-11-02 in the working session, answering an explicit sign-off question about PR #173 (answer: "Approve, drop the gates"): he signs off the amended freeze, approves E31–E37 into scope, and drops the planned approval checkpoints in TC-32-011 (after the Nov 30 go/kill decision) and TC-34-012 (Feb 15, 2027). Approved tickets may start on their Jira dates.

**Commands used for the reconciliation** (from the repo root):

- The mechanical check: `python3 artifacts/acceptance/TC-01-001/check_scope_freeze.py`.
- Per-module route decorators on `c20f949` and `574f2e2`, compared with `git show` and `grep`.
- `git log --diff-filter=A` on each new page, to find the commit that added it.
- Job kinds and thread classes or `threading.Thread` uses across `apps/api/app`, compared across both commits.
- The Jira epic and child lists for SCRUM-420, 421, 422, 464, 477, 492 and 505.
