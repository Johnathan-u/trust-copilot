# Encoding-classification follow-up evidence

Status: implementation and independent review complete; exact published-code and full CI verification pending. This is separate from the approved/merged #87 qualification.

Authorized by [Coordinator comment6504620821](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6504620821), claimed in comment6505738097. Branch: `codex/TC-19-BUG-001-encoding-classification`.

Production change: unsupported, nested or explicitly empty Content-Encoding now raises the existing invalid-encoding result before body consumption. The absent header remains identity. Actual oversized bodies retain response_too_large; invalid encodings stay nonretryable for HTTP 200/429/503. Stream closure and bounded memory remain covered. Truncated gzip now explicitly asserts invalid_encoding.

RED on unchanged base `80607881320e1fa2c6416c55730eb98a56449f26`: strengthened response-limit module returned exit 1, **16 failed, 23 passed**. Failures were the changed error classification. The truncated-gzip assertion already passed and strengthens coverage.

GREEN working-tree run: `PYTHONPATH=. python -m pytest tests/release/test_message_provider_response_limit.py tests/release/test_message_provider_wiring.py tests/release/test_safe_collection.py -q` returned exit 0, **109 passed, 0 skipped** (39+41+29). Linux/Python 3.12, exact hashed requirements-dev.lock, proxy variables cleared, synthetic HTTPX streams only. Ruff check/format and diff check pass.

Independent root review found no blocker and separately ran all 39 response-limit checks successfully. Exact published-code SHA and four CI checks will be recorded after publication; draft status remains until they are green. No migration, new dependency, paid account or provider call. The historical #87 evidence remains unchanged.
