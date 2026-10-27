# TC-01-005: Replace unsupported product and traction claims (acceptance evidence)

- Branch: `tc/coord/TC-01-005`, based on `c20f949` (master)
- Register: [`docs/acceptance/claims-register.md`](../../../docs/acceptance/claims-register.md)
- Reviewer: Trust Copilot Coordinator (merge authority, per release-decisions)

## Acceptance criteria

| AC | Criterion | How it is met | Evidence |
|---|---|---|---|
| TC-01-005-AC1 | Each public capability claim links to a passing acceptance result or is withheld pending delivery | Every claim in README, `/`, `/pricing`, `/checkout`, root metadata, and user-facing API copy has a register row. 0 rows are Supported because no acceptance results exist at baseline. Absolute, expired, or unverifiable claims were removed or reworded (20 rows). Descriptive feature copy that remains is marked Withheld with a named delivery ticket (27 rows). | `claims-register.md`; `check_public_claims.after.txt` (PASS) vs `check_public_claims.baseline.txt` (77 findings at `c20f949`) |
| TC-01-005-AC2 | Seed data, synthetic testimonials, revenue placeholders and heuristic scores are never represented as real traction | No testimonials, logos, or traction figures exist. Mock CRM deals are renamed "(example data)" and responses carry `mock`/`data_basis`. The demo-proof package, ROI calculator, proof-widget hours-saved, and default security FAQ templates are labeled synthetic, illustrative, heuristic, or template. Security-page certifications are `not_attested`. | `service_label_check.py` and `service_label_check.out.txt` (PASS); register rows A1–A11 and D8–D12 |

## How to reproduce

```bash
# from repo root — fails on c20f949, passes on this branch
python3 scripts/check_public_claims.py

# from apps/api — service-level checks, no DB or network
TRUST_COPILOT_TESTING=1 DATABASE_URL=postgresql://x:x@127.0.0.1:1/none SESSION_SECRET=x \
  python ../../artifacts/acceptance/TC-01-005/service_label_check.py
```

## Test notes

- The full pytest suite was **not run** in this environment. `tests/conftest.py` creates and migrates the shared `trustcopilot_test` database on `pytest_configure`, and other bots use the shared Postgres on this machine, so running it could disturb their schema. CI or the reviewer should run `cd apps/api && pytest tests/test_roi_calculator.py tests/test_demo_proof.py tests/test_security_page.py tests/test_security_faq.py tests/test_crm_connectors.py tests/test_proof_widgets.py -m "not integration"`.
- I checked those tests' assertions by hand. All API changes are additive fields or string changes. Assertions on `title`, certification names, the `AES-256` substring, keys, and counts are preserved. `crm_source` values are unchanged, so `get_sync_status` counts are unaffected.
- The web changes are string and JSX-text only. No `node_modules` on this box, so `next build`/`tsc` was not run. The one expression change, `checkout/page.tsx` step-2 plan summary, uses the existing module constants `monthlyPrice` and `annualPrice`.

## Assumptions

1. Since nothing has passing acceptance evidence yet, "withheld pending delivery" means the copy stays as a plain, non-absolute description and the register marks it not release-qualified. Removing every feature mention from the landing page was judged out of proportion. The coordinator can tighten this.
2. The "Free until April 5, 2026" promotion expired. The backend (`billing.py`) already stops the trial after that date, so the expired promo copy was **removed** to match actual billing behavior. The existing list price ($25/$250) is shown with no new terms. Pricing itself remains an **owner decision** (release-decisions.md).
3. Security FAQ defaults already seeded in existing workspaces are not rewritten. Only new seeds get the template prefix, so no data migration is needed.
4. The ROI default `subscription_monthly=399` (versus the $25 list price) is left unchanged pending the owner's pricing decision and is flagged in the register (A6).
