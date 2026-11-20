# TC-17-001a evidence

Local pytest only. This directory does not record CI run ids. It does not accept TC-17-001 or TC-17-001a, and it does not count the child toward DONE.

Command, from `apps/api`:

```sh
python -m pytest tests/release/test_domain_trust_articles.py -q --tb=line -k "public_read_hides or public_list_keeps or seed_publishes"
```

- `failing-before.txt`: those four tests against the unfixed public read and the unfixed QA seed. 4 failed, 19 deselected. An anonymous get of a published row with no version returned 200 and the live title and content. The same get of a dangling `published_version_id` returned the live columns. A `published_only` list included the versionless neighbour. The QA seed left `published_version_id` null.
- `passing-after.txt`: the same four tests after the fix. 4 passed, 19 deselected. No skip.
- `pytest.txt`: `python -m pytest tests/release/test_domain_trust_articles.py -q --tb=line` on the fixed code. 23 passed, no skip.

Related suites on the same tree, from `apps/api`. No skip.

| Suite | Result |
|---|---|
| `tests/test_trust_articles_api.py` | 11 passed |
| `tests/test_trust_center_publish.py` | 6 passed |
| `tests/release/test_trust_article_slug_workspace.py` | 2 passed |
| `tests/test_multi_tenant.py` | 20 passed |
| `tests/test_wave3_p23_p29_api.py::test_p29_editor_cannot_delete_trust_article` | 1 passed |
| `tests/test_controls_api.py` | 6 passed |
| `tests/release/test_principal_contract.py` | 90 passed |
| `tests/release/test_session_validation.py` | 51 passed |
| `tests/release/test_remember_policy.py` | 88 passed |

Environment: Python 3.12.3, pytest 9.1.1, SQLAlchemy 2.0.55, PostgreSQL 16.15, pgvector 0.6.0, database `trustcopilot_test` on 127.0.0.1:5432. `ruff check` on the touched Python files exited 0.

No migration.
