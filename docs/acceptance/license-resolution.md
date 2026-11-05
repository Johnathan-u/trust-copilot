# Licence resolution (TC-01-003)

Status: **resolved 2026-11-05**, owner-accepted. This file is the manual evidence that TC-01-003
names. Every dependency or bundled service whose licence is not plainly permissive has one
chosen path here: replaced, removed from the shipped product, or complied with. The release test
`apps/api/tests/release/test_license_resolution.py` keeps it true on every CI run.

Scope is what ships to a customer or buyer: the API and worker image (`apps/api`), the web image
(`apps/web`) and the production Compose stack (`docker-compose.prod.yml`). Development and test
tools that never ship are listed in §6 for completeness.

## 1. Owner rulings

| Ruling | Date | Decision | Record |
|---|---|---|---|
| OD-2 | 2026-10-27 | Replace PyMuPDF (AGPL-3.0 or Artifex commercial) with a permissive library. Done in TC-01-003a (#11, `f30c174`) with pypdf (BSD-3-Clause), plus TC-01-003b (#22, `e86812b`) for table cells. | `release-decisions.md` §3 |
| OD-12 | 2026-11-05 | Remove MinIO (AGPL-3.0) from the production stack. Production uses an external S3-compatible service; MinIO stays in the dev Compose file only. LGPL, MPL and CC-BY components below ship unmodified with their notices. | `release-decisions.md` §3 |

Both are decided by the owner/seller, Johnathan Reinhart, the Legal decision owner in
`release-decisions.md` §1. No outside counsel has reviewed this file (see §8).

## 2. Resolution of every non-permissive item

| Item | Where | Licence | Path chosen | Evidence |
|---|---|---|---|---|
| PyMuPDF | API runtime (was) | AGPL-3.0 or commercial | **Replaced** by pypdf 6.21.3 (BSD-3-Clause) behind `app/services/pdf_text.py`. No PDF library other than pypdf is imported. | TC-01-003a, TC-01-003b; `tests/test_pdf_text_locator_corpus.py` scans every manifest and lock for the old package |
| MinIO server (`minio/minio:latest`) | production Compose (was) | AGPL-3.0 | **Removed from production.** `docker-compose.prod.yml` has no object-store service; `S3_ENDPOINT` must point at an external S3-compatible service. MinIO remains only in `docker-compose.yml` (local dev and E2E), which is not shipped. The upstream community edition is also no longer maintained. | this PR; `test_license_resolution.py::test_prod_compose_bundles_no_minio` |
| psycopg2-binary 2.9.13 | API runtime | LGPL-3.0-or-later with OpenSSL exception | **Comply.** Used unmodified as a separately installed library; its licence travels with the wheel. No change to its source. | `test_license_resolution.py::test_python_runtime_licences` |
| certifi 2026.10.23 | API runtime | MPL-2.0 | **Comply.** File-level copyleft; used unmodified, licence included in the wheel. | same |
| sharp / libvips binaries (`@img/sharp-libvips-*` 1.3.4, `@img/sharp-*` 0.35.5) | web runtime (optional dependency of Next.js image optimisation) | LGPL-3.0-or-later (libvips), Apache-2.0 (sharp) | **Comply.** Prebuilt, unmodified, dynamically loaded shared library; replaceable by the user; licence files ship in the package. | `test_license_resolution.py::test_web_runtime_licences` |
| caniuse-lite 1.0.30001819 | web runtime (browserslist data) | CC-BY-4.0 | **Comply.** Attribution kept in the package; data is unmodified. | same |

Nothing else in the runtime dependency set is copyleft or source-available.

## 3. Production images

| Image | Licence | Notes |
|---|---|---|
| `caddy:2` | Apache-2.0 | Reverse proxy and TLS. |
| `pgvector/pgvector:pg16` | PostgreSQL Licence (PostgreSQL and pgvector) | Database. |
| `python:3.11-slim` | PSF-2.0 (CPython) | Base of the API and worker image. |
| `node:24.22.1-trixie-slim` | MIT (Node.js) | Base of the web image, pinned by digest in `apps/web/Dockerfile`. |

The Debian base layers in these images contain operating-system packages under their own
licences (including GPL tools such as bash and coreutils). They are shipped unmodified as
separate programs, which is ordinary aggregation and needs no change to TrustCopilot's licence.
The exact per-package list belongs to TC-01-004.

## 4. API runtime dependencies (`apps/api/requirements.lock`, 63 packages)

All packages are MIT, BSD-2/3-Clause, Apache-2.0, ISC, PSF-2.0, MIT-0 or dual-licensed among
these, except psycopg2-binary (LGPL) and certifi (MPL-2.0) in §2. `httpx2` 2.16.0, `httpcore2`
2.16.0 and `httpx2-jsfetch` 1.0 declare BSD-3-Clause. CI reads the installed metadata of every
runtime package on each run and fails on any copyleft or source-available licence that is not an
exception in §2.

## 5. Web runtime dependencies (`apps/web/package-lock.json`, 181 non-dev entries)

129 MIT, 19 Apache-2.0, 14 ISC, 2 BSD-3-Clause, 1 0BSD, 1 MIT AND ISC AND BSD-3-Clause, and the
sharp/libvips and caniuse-lite entries in §2. Direct dependencies: next, react, react-dom,
react-markdown, recharts. CI checks every non-dev entry of the lock file.

## 6. Development and test tools (not shipped)

275 dev-only npm entries: MIT, Apache-2.0, ISC, BSD-2/3-Clause, BlueOak-1.0.0, and 14 MPL-2.0
(axe-core and @axe-core/playwright for accessibility tests, lightningcss for the CSS build).
MPL-2.0 dev tools are used unmodified and are not distributed. The extra Python dev pins in
`requirements-dev.lock` (pytest, ruff, pluggy, iniconfig, packaging, pygments, colorama) are MIT,
Apache-2.0 or BSD. MinIO runs only in `docker-compose.yml` for local development and E2E tests.
No AGPL, GPL (other than LGPL), SSPL or BUSL package exists in either lock file, dev or runtime.
CI checks every npm entry and every API runtime pin for this; the extra Python dev pins are not
machine-checked.

## 7. PDF engine (E37)

The owned PDF engine (`Johnathan-u/pdf-engine`, E37) will later replace pypdf (TC-37-019). Its
repository has its own licence gate (`cargo deny`, permissive licences only) and clean-room rules,
so it adds no restrictive licence when it lands.

## 8. Acceptance and limits

- **TC-01-003-AC1** (a chosen path for every incompatible dependency): §2, owner rulings in §1.
  The path was chosen by the owner/seller as Legal decision owner. "Legally reviewed" here means
  owner review; no outside counsel was engaged. A buyer may still ask for counsel sign-off.
- **TC-01-003-AC2** (PDF replacement passes the locator corpus and does not silently change
  supported formats): TC-01-003a and TC-01-003b. The synthetic locator corpus passes with pypdf,
  parity with the recorded PyMuPDF baseline is tested, and every behaviour difference and error
  is documented in `docs/release/tickets/TC-01-003a.md` and `TC-01-003b.md`. Neither ticket
  changed the upload allow-lists (`file_service.ALLOWED_RAW_EXTENSIONS`,
  `gmail_ingest_service.SUPPORTED_ATTACHMENT_TYPES`); PDFs still need a text layer (no OCR before
  or after).
- Not covered here: the exact dependency and asset inventory and NOTICE file (TC-01-004); CI
  checks for secrets and container images (TC-02-008); chain of title (TC-01-002, OD-1). The
  `depends_on` TC-01-002 is ordering only; this file does not rely on it.
- Production operators must create the `S3_BUCKET_RAW` and `S3_BUCKET_EXPORTS` buckets in their
  S3 service and set `S3_REGION` when it is not `us-east-1`.
