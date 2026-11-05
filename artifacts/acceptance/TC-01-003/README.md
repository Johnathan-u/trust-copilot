# TC-01-003 evidence: licence resolution

Ticket: TC-01-003 (Jira SCRUM-38). Record: `docs/acceptance/license-resolution.md`. Owner rulings:
OD-2 (2026-10-27, PyMuPDF replaced) and OD-12 (2026-11-05, MinIO removed from production) in
`docs/acceptance/release-decisions.md` §3.

| File | What it shows |
|---|---|
| `scan_licences.py` | Static scan of the shipped stack: production Compose services and images, web lock licence counts, non-permissive runtime web entries, API runtime pins. Run from the repo root. |
| `scan_before_master.txt` | The scan at master `bc1c5c9`: `minio/minio:latest` (AGPL-3.0) and its `minio_data` volume are in `docker-compose.prod.yml`. |
| `scan_branch.txt` | The same scan on this branch: no MinIO service or volume; everything else unchanged. |

The PDF part (TC-01-003-AC2) is evidenced by `artifacts/acceptance/TC-01-003a/` and
`artifacts/acceptance/TC-01-003b/` (locator corpus, PyMuPDF baseline parity).

Continuous checks, in the backend CI job (`pytest -rs` in `apps/api`):

- `tests/release/test_license_resolution.py`: no MinIO in the production stack; every shipped
  image listed in the record with its licence; every API runtime pin's installed licence metadata
  and every web runtime lock entry permissive or a documented exception; no AGPL, GPL, SSPL or
  BUSL in any web lock entry; the exceptions are still present and documented.
- `tests/release/test_storage_region.py`: `S3_REGION` reaches the boto3 client (default
  `us-east-1`), for external S3 services outside that region.
- `tests/release/test_secret_inventory.py::test_prod_compose_requires_credentials_from_env`: the
  production stack requires `S3_ENDPOINT` from the environment and carries no MinIO credentials.

Limits: owner review only, no outside counsel; exact dependency and asset inventory with NOTICE
file is TC-01-004; container image and secret checks in CI are TC-02-008.
