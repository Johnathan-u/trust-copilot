# Dev / local compliance catalog (non-verbatim fixtures)

This folder documents the **development-only** multi-framework control summaries used for local questionnaire mapping benchmarks and UI demos.

- **SOC 2**: Uses common public **TSC criterion identifiers** (e.g. `CC6.1`) as keys. Descriptions are **short paraphrases** for keyword coverage, not official AICPA wording.
- **HIPAA**: Uses **public citation-style keys** (45 CFR Part 164) with **brief paraphrases** of themes, not full regulatory text.
- **NIST**: Uses **public NIST Cybersecurity Framework 2.0** subcategory identifiers (e.g. `GV.RM-01`) with short theme summaries.
- **HITRUST** and **ISO 27001**: The repo does **not** include licensed standard text. Entries use synthetic keys prefixed **`HITRUST-DEV-*`** and **`ISO-DEV-*`** with **representative theme summaries only**—suitable for dev mapping tests only, not compliance attestation.

Do not replace these with verbatim copyrighted control libraries without proper licensing.

The seed writes **dev/test framework rows only**. It does not attach controls to the advertised production catalog slot (`catalog_kind=advertised_blocked`). Those rows stay blocked until content rights are decided in TC-01-007. `POST /api/compliance/frameworks/enable` refuses every advertised framework and refuses synthetic `HITRUST-DEV-*` / `ISO-DEV-*` keys and dev versions (`CSF-dev`, `dev-themes`) as a production catalog. There is no environment flag that turns a dev seed into a licensed catalog.

See `docs/release/tickets/TC-21-001.md` for the enablement contract, migration, and rollback.

## Seeding

From `apps/api`:

```bash
python -m scripts.seed_dev_compliance_catalog
python -m scripts.seed_dev_compliance_catalog --workspace-id 1
```

This is also invoked automatically at the end of `python -m scripts.seed_demo_workspace` (even if MinIO/questionnaire seed fails).

**Duplicate `SOC2` vs `SOC 2`:** If both framework rows exist, merge them safely with:

```bash
cd apps/api
python -m scripts.merge_dev_duplicate_soc2_framework --dry-run
TRUST_COPILOT_MERGE_SOC2=1 python -m scripts.merge_dev_duplicate_soc2_framework --apply
# or: python -m scripts.merge_dev_duplicate_soc2_framework --apply --i-know-what-im-doing
```

This relinks `WorkspaceControl` rows to the canonical **`SOC 2`** framework, remaps dependent FKs, and removes the duplicate framework row (dev/local only; not a production migration).
