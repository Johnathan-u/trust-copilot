# TC-17-001b evidence

Local pytest only. This directory does not record CI run ids.

- `failing-before.txt`: the four new tests against unfixed `_viewable_version`. Two failed. A non-admin acknowledge of a published policy with no version returned 200 and stored a version. The current-version acknowledge and the administrator publish passed.
- `passing-after.txt`: the same four tests after the fix. 4 passed.
- `pytest.txt`: `python -m pytest tests/release/test_domain_trust_articles.py -q` on the fixed code. 18 passed, no skip.

The trust-center dashboard already shows an error for this refusal. No dashboard change.
