# TC-21-007c — Question parent provenance evidence

Scope: [issue #113](https://github.com/Johnathan-u/trust-copilot/issues/113).
Assignment: [#85 comment6511727336](https://github.com/Johnathan-u/trust-copilot/issues/85#issuecomment-6511727336).
Base: `2f9d65a06944e2cfae37e82cd53e27a82758ef6f`.

## Change

Every coverage recommendation now has `question_sources`, a list of
`{question_id, questionnaire_id}` pairs. The existing same-workspace,
nondeleted-questionnaire query returns the stored parent with each question ID.
Titled evidence-gap recommendations and insufficient-answer fallback suggestions
both use it. Pairs follow the sorted, deduplicated question IDs. Unavailable
targets emit no pair; sourceless recommendations remain visible with `[]`.
Counts, existing fields, review permission and read-only route behavior are
unchanged. No migration, dependency, new endpoint or provider call was added.

## Test-first evidence and local checks

Python: `/tmp/tc-backend-venv/bin/python` (3.12), run from `apps/api`.

| Command | Result |
| --- | --- |
| `python -m pytest tests/test_coverage_question_provenance.py tests/test_compliance_coverage_unit.py -q -k 'actual_parents or parent_associations'` before service changes | 2 failed, 39 deselected; both failed with `KeyError: question_sources` |
| `python -m pytest tests/test_coverage_question_provenance.py tests/test_compliance_coverage_unit.py -q` after service changes | 41 passed |
| `python -m pytest --collect-only -q tests/release/test_domain_coverage_recommendations.py tests/test_coverage_question_provenance.py tests/test_compliance_coverage_unit.py` | 44 collected |
| `python -m ruff check app/services/compliance_coverage.py tests/test_coverage_question_provenance.py tests/test_compliance_coverage_unit.py tests/release/test_domain_coverage_recommendations.py` | Passed |
| `python -m ruff format --check app/services/compliance_coverage.py tests/test_coverage_question_provenance.py tests/test_compliance_coverage_unit.py tests/release/test_domain_coverage_recommendations.py` | Passed |
| `git diff --check` | Passed |
| `TC_REQUIRE_DB=1 TC_TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/trustcopilot_test python -m pytest -rs` | Exit 3 during setup: PostgreSQL connection refused; no suite pass claimed |

The local SQLite projection test executes the real scoped SQL lookup against a
minimal question/questionnaire schema. It covers two distinct actual parents,
duplicate references, foreign and soft-deleted parents, nonexistent question IDs,
title association and empty provenance without changing recommendation counts.
It does not qualify PostgreSQL schemas, migrations or constraints. The existing
controlled-query unit harness verifies fallback propagation and preserved answer
counts; it is not database acceptance.

The three existing PostgreSQL provenance regressions now also assert parent pairs
for titled and fallback recommendations. They cover a foreign workspace's gap
with the same title, deleted/sourceless targets, two different question parents,
repeated gap references and unchanged GET row counts/source timestamps. These
tests were collected locally but require CI execution. No database constraint is
bypassed and no integration test was replaced with a mock.

## Remaining qualification

Independent review and fresh push/pull-request `build` and `web-release-e2e` on
the final published head remain required. The coordinator records the final
commit/tree and CI links in #85 and the PR. This evidence does not claim completion
of the separate TC-15-025 frontend drill-down or framework catalog rights gates.
