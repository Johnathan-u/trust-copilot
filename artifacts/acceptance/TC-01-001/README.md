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
