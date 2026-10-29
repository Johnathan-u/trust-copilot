# Encoding-classification follow-up evidence

Status: exact published code passes focused local checks and full PR CI; independent review has no blocker. Final readiness requires all four checks at the final documentation head, recorded in the PR/coordination thread. This is separate from the approved/merged #87 qualification.

Authorized by [Coordinator comment6504620821](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6504620821), claimed in comment6505738097. Branch: `codex/TC-19-BUG-001-encoding-classification`.

Production change: unsupported, nested or explicitly empty Content-Encoding now raises the existing invalid-encoding result before body consumption. The absent header remains identity. Actual oversized bodies retain response_too_large; invalid encodings stay nonretryable for HTTP 200/429/503. Stream closure and bounded memory remain covered. Truncated gzip now explicitly asserts invalid_encoding.

RED on unchanged base `80607881320e1fa2c6416c55730eb98a56449f26`: strengthened response-limit module returned exit 1, **16 failed, 23 passed**. Failures were the changed error classification. The truncated-gzip assertion already passed and strengthens coverage.

GREEN exact published-code run at `3d0b68e6e1c4de3d902da31e4c2f7889761fd928`: `PYTHONPATH=. python -m pytest tests/release/test_message_provider_response_limit.py tests/release/test_message_provider_wiring.py tests/release/test_safe_collection.py -q` returned exit 0, **109 passed, 0 skipped** (39+41+29). Linux/Python 3.12, exact hashed requirements-dev.lock, proxy variables cleared, synthetic HTTPX streams only. Ruff check/format and diff check pass.

Independent root review found no blocker and separately ran all 39 response-limit checks successfully. [PR CI run40936745662](https://github.com/Johnathan-u/trust-copilot/actions/runs/40936745662) completed successfully at `3d0b68e6e1c4de3d902da31e4c2f7889761fd928`: build123669175264 and web123669175714 both passed. The full backend suite recorded **3280 passed, 1 unrelated external blind-data skip**. The exact local run passed all 109 checks in 12.20 seconds; output is in `encoding-followup-local.txt`. Initial push attempt40936724456 failed before tests on isolated PostgreSQL readiness; its failed job alone was requested to rerun. No production workaround was added.

This artifact records the tested code SHA and completed PR run. The final documentation head must pass both push and PR workflows (four checks) before readiness; those results are recorded in the PR/coordination thread, avoiding a self-referential commit hash. No migration, new dependency, paid account or provider call. The historical #87 evidence remains unchanged.
