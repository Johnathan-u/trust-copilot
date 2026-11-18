# TC-07-004: hostile Origin is final, and forwarded headers need a trusted proxy

A present `Origin` that is not allowed, including the literal `null`, is rejected before Referer or `X-Forwarded-*`. `X-Forwarded-Host` and `X-Forwarded-Proto` count only when the direct peer is in `TRUSTED_PROXY_IPS` (IPs or CIDRs). Unset trusts nothing. Production Caddy replaces those two headers with the host and scheme it received.

This note does not accept TC-07-004. No migration. The batch-7 files `pytest.txt` and `environment.txt` in this directory are the earlier origin-test run. They are not this change.

## Red command

Working directory `apps/api`. Interpreter `/tmp/tc-venv/bin/python`. Product code was `e8ed98aa` (batch 7). The new test file was present. The origin check and the Caddy file were not.

```text
python -m pytest tests/release/test_csrf_proxy.py -q --tb=short
```

- Python 3.12.3, pytest 9.1.1
- No database

| Command | Exit | Total |
|---|---|---|
| the red command above | 1 | 5 failed, 4 passed, 0.27s |

The four security failures are `assert True is False`: a hostile `Origin` was accepted because the Referer or `X-Forwarded-Host` matched, `Origin: null` fell through to that Referer, and forwarded headers were accepted from a peer that is not a configured proxy. `test_forwarded_headers_from_trusted_proxy_are_honoured` passed on that code because every caller was treated as the proxy. The Caddy assertion failed because `Caddyfile.production` did not replace the forwarded headers. The allowed-Origin and same-origin tests passed. Log: `failing-before.txt`.

## Green command

Same interpreter and tests, after the check, the proxy setting, and the Caddy change.

```text
python -m pytest tests/release/test_csrf_proxy.py -q --tb=short
python -m pytest tests/test_csrf_origins.py -q --tb=short
```

## Environment

- Python 3.12.3, pytest 9.1.1
- No database. PostgreSQL was not used.

## Totals

| Command | Exit | Total |
|---|---|---|
| `python -m pytest tests/release/test_csrf_proxy.py -q --tb=short` | 0 | 9 passed, 0.25s |
| `python -m pytest tests/test_csrf_origins.py -q --tb=short` | 0 | 8 passed, 0.22s |

Pytest did not report a skipped test. Log: `passing-after.txt`.

`tests/test_csrf_origins.py::test_csrf_safe_x_forwarded_host_matches_trusted` now passes a trusted peer (`10.0.0.8`). Before this change it supplied `X-Forwarded-Host` with no peer, which is the insecure fallback. The other seven origin tests are unchanged.

`TestClientIpTrust` (4) and `test_contract_doc_is_generated_from_code` also passed in the same environment (22 passed together with the two files above). Those commands are not the named release command.
