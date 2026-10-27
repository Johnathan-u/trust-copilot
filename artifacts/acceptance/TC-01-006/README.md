# TC-01-006: Define release decisions and change control (acceptance evidence)

- Branch: `tc/coord/TC-01-006`, based on `c20f949`
- Deliverable: [`docs/acceptance/release-decisions.md`](../../../docs/acceptance/release-decisions.md). The ticket proposes the name `decision-control.md`; the coordinator brief names this file `release-decisions.md`. The deliverable is the same.

| AC | How it is met |
|---|---|
| TC-01-006-AC1: product, domain, security, legal, and buyer decision owners named by role | §1 table. Owner/seller (Johnathan) owns legal, rights, spend, accounts, and sale terms. The Trust Copilot Coordinator owns scope, merges, and technical rulings. Security and domain are split explicitly. |
| TC-01-006-AC2: new scope gets a linked ticket, estimate, and dependency before any completion claim | §2 rule 1 (four concrete preconditions), rules 2–4 (no silent reduction, evidence before Done, approval split) |

Verification is a manual evidence review, as the ticket specifies. The facts cited in the §3 log were checked against baseline source:
`apps/api/pyproject.toml:27` (pymupdf), `apps/api/app/api/routes/billing.py:16,83` (FREE_TRIAL_END 2026-04-05), `apps/api/app/services/roi_calculator_service.py:9` (399.0), `apps/api/app/services/security_page_service.py` (security@trustcopilot.io).

## Assumptions

- The person behind "Owner/seller" is Johnathan, per the coordinator brief.
- OD-10 (retention) was added because PRODUCT_SPEC requires owner and counsel approval. It was not in the brief's list.
- All Owner decisions are PENDING. This PR records them and does not decide them.
