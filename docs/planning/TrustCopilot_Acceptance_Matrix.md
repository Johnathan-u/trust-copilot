# TrustCopilot complete ticket acceptance matrix

All rows are future required acceptance, not current test results. Each linked ticket contains its full acceptance criteria and definition of done. Record actual outcomes at the final release SHA; no required unexplained skips.

| Ticket | Acceptance IDs | Verification | Evidence directory |
| --- | --- | --- | --- |
| [TC-01-001](tickets/TC-01-001.md) | TC-01-001-AC1, TC-01-001-AC2 | Manual evidence review: docs/acceptance/scope-contract.md | artifacts/acceptance/TC-01-001/ |
| [TC-01-002](tickets/TC-01-002.md) | TC-01-002-AC1, TC-01-002-AC2 | Manual evidence review: docs/acceptance/ip-provenance.md | artifacts/acceptance/TC-01-002/ |
| [TC-01-003](tickets/TC-01-003.md) | TC-01-003-AC1, TC-01-003-AC2 | Manual evidence review: docs/acceptance/license-resolution.md | artifacts/acceptance/TC-01-003/ |
| [TC-01-004](tickets/TC-01-004.md) | TC-01-004-AC1, TC-01-004-AC2 | Manual evidence review: docs/acceptance/license-sbom.md | artifacts/acceptance/TC-01-004/ |
| [TC-01-005](tickets/TC-01-005.md) | TC-01-005-AC1, TC-01-005-AC2 | Manual evidence review: docs/acceptance/claims-register.md | artifacts/acceptance/TC-01-005/ |
| [TC-01-006](tickets/TC-01-006.md) | TC-01-006-AC1, TC-01-006-AC2 | Manual evidence review: docs/acceptance/decision-control.md | artifacts/acceptance/TC-01-006/ |
| [TC-02-001](tickets/TC-02-001.md) | TC-02-001-AC1, TC-02-001-AC2 | python -m pytest tests/release/test_safe_collection.py -q | artifacts/acceptance/TC-02-001/ |
| [TC-02-002](tickets/TC-02-002.md) | TC-02-002-AC1, TC-02-002-AC2 | python -m pytest tests/release/test_python_lock.py -q | artifacts/acceptance/TC-02-002/ |
| [TC-02-003](tickets/TC-02-003.md) | TC-02-003-AC1, TC-02-003-AC2 | python -m pytest tests/release/test_web_lock.py -q | artifacts/acceptance/TC-02-003/ |
| [TC-02-004](tickets/TC-02-004.md) | TC-02-004-AC1, TC-02-004-AC2 | python -m pytest tests/release/test_test_overlay.py -q | artifacts/acceptance/TC-02-004/ |
| [TC-02-005](tickets/TC-02-005.md) | TC-02-005-AC1, TC-02-005-AC2 | python -m pytest tests/release/test_api_quality.py -q | artifacts/acceptance/TC-02-005/ |
| [TC-02-006](tickets/TC-02-006.md) | TC-02-006-AC1, TC-02-006-AC2 | python -m pytest tests/release/test_web_quality.py -q | artifacts/acceptance/TC-02-006/ |
| [TC-02-007](tickets/TC-02-007.md) | TC-02-007-AC1, TC-02-007-AC2 | python -m pytest tests/release/test_ci_integration.py -q | artifacts/acceptance/TC-02-007/ |
| [TC-02-008](tickets/TC-02-008.md) | TC-02-008-AC1, TC-02-008-AC2 | python -m pytest tests/release/test_ci_supply_chain.py -q | artifacts/acceptance/TC-02-008/ |
| [TC-02-009](tickets/TC-02-009.md) | TC-02-009-AC1, TC-02-009-AC2 | python -m pytest tests/release/test_ci_evidence.py -q | artifacts/acceptance/TC-02-009/ |
| [TC-03-001](tickets/TC-03-001.md) | TC-03-001-AC1, TC-03-001-AC2 | python -m pytest tests/release/test_config_contract.py -q | artifacts/acceptance/TC-03-001/ |
| [TC-03-002](tickets/TC-03-002.md) | TC-03-002-AC1, TC-03-002-AC2 | python -m pytest tests/release/test_compose_stack.py -q | artifacts/acceptance/TC-03-002/ |
| [TC-03-003](tickets/TC-03-003.md) | TC-03-003-AC1, TC-03-003-AC2 | python -m pytest tests/release/test_health_probes.py -q | artifacts/acceptance/TC-03-003/ |
| [TC-03-004](tickets/TC-03-004.md) | TC-03-004-AC1, TC-03-004-AC2 | python -m pytest tests/release/test_migration_baseline.py -q | artifacts/acceptance/TC-03-004/ |
| [TC-03-005](tickets/TC-03-005.md) | TC-03-005-AC1, TC-03-005-AC2 | python -m pytest tests/release/test_migration_lock.py -q | artifacts/acceptance/TC-03-005/ |
| [TC-03-006](tickets/TC-03-006.md) | TC-03-006-AC1, TC-03-006-AC2 | python -m pytest tests/release/test_release_images.py -q | artifacts/acceptance/TC-03-006/ |
| [TC-03-007](tickets/TC-03-007.md) | TC-03-007-AC1, TC-03-007-AC2 | python -m pytest tests/release/test_upgrade_rollback.py -q | artifacts/acceptance/TC-03-007/ |
| [TC-04-001](tickets/TC-04-001.md) | TC-04-001-AC1, TC-04-001-AC2 | python -m pytest tests/release/test_registration.py -q | artifacts/acceptance/TC-04-001/ |
| [TC-04-002](tickets/TC-04-002.md) | TC-04-002-AC1, TC-04-002-AC2 | python -m pytest tests/release/test_identity_tokens.py -q | artifacts/acceptance/TC-04-002/ |
| [TC-04-003](tickets/TC-04-003.md) | TC-04-003-AC1, TC-04-003-AC2 | python -m pytest tests/release/test_password_reset.py -q | artifacts/acceptance/TC-04-003/ |
| [TC-04-004](tickets/TC-04-004.md) | TC-04-004-AC1, TC-04-004-AC2 | python -m pytest tests/release/test_session_validation.py -q | artifacts/acceptance/TC-04-004/ |
| [TC-04-005](tickets/TC-04-005.md) | TC-04-005-AC1, TC-04-005-AC2 | python -m pytest tests/release/test_session_revocation.py -q | artifacts/acceptance/TC-04-005/ |
| [TC-04-006](tickets/TC-04-006.md) | TC-04-006-AC1, TC-04-006-AC2 | python -m pytest tests/release/test_remember_policy.py -q | artifacts/acceptance/TC-04-006/ |
| [TC-04-007](tickets/TC-04-007.md) | TC-04-007-AC1, TC-04-007-AC2 | python -m pytest tests/release/test_auth_rate_limits.py -q | artifacts/acceptance/TC-04-007/ |
| [TC-05-001](tickets/TC-05-001.md) | TC-05-001-AC1, TC-05-001-AC2 | python -m pytest tests/release/test_mfa_enroll.py -q | artifacts/acceptance/TC-05-001/ |
| [TC-05-002](tickets/TC-05-002.md) | TC-05-002-AC1, TC-05-002-AC2 | python -m pytest tests/release/test_mfa_recovery.py -q | artifacts/acceptance/TC-05-002/ |
| [TC-05-003](tickets/TC-05-003.md) | TC-05-003-AC1, TC-05-003-AC2 | python -m pytest tests/release/test_role_matrix.py -q | artifacts/acceptance/TC-05-003/ |
| [TC-05-004](tickets/TC-05-004.md) | TC-05-004-AC1, TC-05-004-AC2 | python -m pytest tests/release/test_oauth_binding.py -q | artifacts/acceptance/TC-05-004/ |
| [TC-05-005](tickets/TC-05-005.md) | TC-05-005-AC1, TC-05-005-AC2 | python -m pytest tests/release/test_oauth_google.py -q | artifacts/acceptance/TC-05-005/ |
| [TC-05-006](tickets/TC-05-006.md) | TC-05-006-AC1, TC-05-006-AC2 | python -m pytest tests/release/test_oauth_github.py -q | artifacts/acceptance/TC-05-006/ |
| [TC-05-007](tickets/TC-05-007.md) | TC-05-007-AC1, TC-05-007-AC2 | python -m pytest tests/release/test_oauth_microsoft.py -q | artifacts/acceptance/TC-05-007/ |
| [TC-05-008](tickets/TC-05-008.md) | TC-05-008-AC1, TC-05-008-AC2 | python -m pytest tests/release/test_oauth_oidc_idme.py -q | artifacts/acceptance/TC-05-008/ |
| [TC-05-009](tickets/TC-05-009.md) | TC-05-009-AC1, TC-05-009-AC2 | python -m pytest tests/release/test_sso_policy.py -q | artifacts/acceptance/TC-05-009/ |
| [TC-06-001](tickets/TC-06-001.md) | TC-06-001-AC1, TC-06-001-AC2 | python -m pytest tests/release/test_principal_contract.py -q | artifacts/acceptance/TC-06-001/ |
| [TC-06-002](tickets/TC-06-002.md) | TC-06-002-AC1, TC-06-002-AC2 | python -m pytest tests/release/test_authorization_core.py -q | artifacts/acceptance/TC-06-002/ |
| [TC-06-003](tickets/TC-06-003.md) | TC-06-003-AC1, TC-06-003-AC2 | python -m pytest tests/release/test_authorization_expanded.py -q | artifacts/acceptance/TC-06-003/ |
| [TC-06-004](tickets/TC-06-004.md) | TC-06-004-AC1, TC-06-004-AC2 | python -m pytest tests/release/test_authorization_public.py -q | artifacts/acceptance/TC-06-004/ |
| [TC-06-005](tickets/TC-06-005.md) | TC-06-005-AC1, TC-06-005-AC2 | python -m pytest tests/release/test_authorization_matrix.py -q | artifacts/acceptance/TC-06-005/ |
| [TC-06-006](tickets/TC-06-006.md) | TC-06-006-AC1, TC-06-006-AC2 | python -m pytest tests/release/test_authorization_storage_cache.py -q | artifacts/acceptance/TC-06-006/ |
| [TC-07-001](tickets/TC-07-001.md) | TC-07-001-AC1, TC-07-001-AC2 | python -m pytest tests/release/test_secret_inventory.py -q | artifacts/acceptance/TC-07-001/ |
| [TC-07-002](tickets/TC-07-002.md) | TC-07-002-AC1, TC-07-002-AC2 | python -m pytest tests/release/test_key_rotation.py -q | artifacts/acceptance/TC-07-002/ |
| [TC-07-003](tickets/TC-07-003.md) | TC-07-003-AC1, TC-07-003-AC2 | python -m pytest tests/release/test_login_redirect.py -q | artifacts/acceptance/TC-07-003/ |
| [TC-07-004](tickets/TC-07-004.md) | TC-07-004-AC1, TC-07-004-AC2 | python -m pytest tests/release/test_csrf_proxy.py -q | artifacts/acceptance/TC-07-004/ |
| [TC-07-005](tickets/TC-07-005.md) | TC-07-005-AC1, TC-07-005-AC2 | python -m pytest tests/release/test_csp_xss.py -q | artifacts/acceptance/TC-07-005/ |
| [TC-07-006](tickets/TC-07-006.md) | TC-07-006-AC1, TC-07-006-AC2 | python -m pytest tests/release/test_upload_stream.py -q | artifacts/acceptance/TC-07-006/ |
| [TC-07-007](tickets/TC-07-007.md) | TC-07-007-AC1, TC-07-007-AC2 | python -m pytest tests/release/test_parser_sandbox.py -q | artifacts/acceptance/TC-07-007/ |
| [TC-07-008](tickets/TC-07-008.md) | TC-07-008-AC1, TC-07-008-AC2 | python -m pytest tests/release/test_download_safety.py -q | artifacts/acceptance/TC-07-008/ |
| [TC-07-009](tickets/TC-07-009.md) | TC-07-009-AC1, TC-07-009-AC2 | python -m pytest tests/release/test_ssrf_egress.py -q | artifacts/acceptance/TC-07-009/ |
| [TC-07-010](tickets/TC-07-010.md) | TC-07-010-AC1, TC-07-010-AC2 | python -m pytest tests/release/test_injection_boundaries.py -q | artifacts/acceptance/TC-07-010/ |
| [TC-07-011](tickets/TC-07-011.md) | TC-07-011-AC1, TC-07-011-AC2 | python -m pytest tests/release/test_log_redaction.py -q | artifacts/acceptance/TC-07-011/ |
| [TC-07-012](tickets/TC-07-012.md) | TC-07-012-AC1, TC-07-012-AC2 | python -m pytest tests/release/test_threat_model.py -q | artifacts/acceptance/TC-07-012/ |
| [TC-07-013](tickets/TC-07-013.md) | TC-07-013-AC1, TC-07-013-AC2 | python -m pytest tests/release/test_security_review.py -q | artifacts/acceptance/TC-07-013/ |
| [TC-07-014](tickets/TC-07-014.md) | TC-07-014-AC1, TC-07-014-AC2 | python -m pytest tests/release/test_security_maintenance.py -q | artifacts/acceptance/TC-07-014/ |
| [TC-08-001](tickets/TC-08-001.md) | TC-08-001-AC1, TC-08-001-AC2 | python -m pytest tests/release/test_evidence_provenance.py -q | artifacts/acceptance/TC-08-001/ |
| [TC-08-002](tickets/TC-08-002.md) | TC-08-002-AC1, TC-08-002-AC2 | python -m pytest tests/release/test_evidence_format_errors.py -q | artifacts/acceptance/TC-08-002/ |
| [TC-08-003](tickets/TC-08-003.md) | TC-08-003-AC1, TC-08-003-AC2 | python -m pytest tests/release/test_index_atomicity.py -q | artifacts/acceptance/TC-08-003/ |
| [TC-08-004](tickets/TC-08-004.md) | TC-08-004-AC1, TC-08-004-AC2 | python -m pytest tests/release/test_retrieval_isolation.py -q | artifacts/acceptance/TC-08-004/ |
| [TC-08-005](tickets/TC-08-005.md) | TC-08-005-AC1, TC-08-005-AC2 | python -m pytest tests/release/test_session_concurrency.py -q | artifacts/acceptance/TC-08-005/ |
| [TC-08-006](tickets/TC-08-006.md) | TC-08-006-AC1, TC-08-006-AC2 | python -m pytest tests/release/test_archive_revalidation.py -q | artifacts/acceptance/TC-08-006/ |
| [TC-08-007](tickets/TC-08-007.md) | TC-08-007-AC1, TC-08-007-AC2 | python -m pytest tests/release/test_hard_deletion.py -q | artifacts/acceptance/TC-08-007/ |
| [TC-08-008](tickets/TC-08-008.md) | TC-08-008-AC1, TC-08-008-AC2 | python -m pytest tests/release/test_workspace_privacy.py -q | artifacts/acceptance/TC-08-008/ |
| [TC-08-009](tickets/TC-08-009.md) | TC-08-009-AC1, TC-08-009-AC2 | python -m pytest tests/release/test_data_flow_policy.py -q | artifacts/acceptance/TC-08-009/ |
| [TC-09-001](tickets/TC-09-001.md) | TC-09-001-AC1, TC-09-001-AC2 | python -m pytest tests/release/test_question_detection.py -q | artifacts/acceptance/TC-09-001/ |
| [TC-09-002](tickets/TC-09-002.md) | TC-09-002-AC1, TC-09-002-AC2 | python -m pytest tests/release/test_cell_mapping.py -q | artifacts/acceptance/TC-09-002/ |
| [TC-09-003](tickets/TC-09-003.md) | TC-09-003-AC1, TC-09-003-AC2 | python -m pytest tests/release/test_mapping_preview.py -q | artifacts/acceptance/TC-09-003/ |
| [TC-09-004](tickets/TC-09-004.md) | TC-09-004-AC1, TC-09-004-AC2 | python -m pytest tests/release/test_workbook_preflight.py -q | artifacts/acceptance/TC-09-004/ |
| [TC-09-005](tickets/TC-09-005.md) | TC-09-005-AC1, TC-09-005-AC2 | python -m pytest tests/release/test_questionnaire_docx_pdf.py -q | artifacts/acceptance/TC-09-005/ |
| [TC-09-006](tickets/TC-09-006.md) | TC-09-006-AC1, TC-09-006-AC2 | python -m pytest tests/release/test_questionnaire_replay.py -q | artifacts/acceptance/TC-09-006/ |
| [TC-10-001](tickets/TC-10-001.md) | TC-10-001-AC1, TC-10-001-AC2 | python -m pytest tests/release/test_job_leases.py -q | artifacts/acceptance/TC-10-001/ |
| [TC-10-002](tickets/TC-10-002.md) | TC-10-002-AC1, TC-10-002-AC2 | python -m pytest tests/release/test_job_retries.py -q | artifacts/acceptance/TC-10-002/ |
| [TC-10-003](tickets/TC-10-003.md) | TC-10-003-AC1, TC-10-003-AC2 | python -m pytest tests/release/test_job_idempotency.py -q | artifacts/acceptance/TC-10-003/ |
| [TC-10-004](tickets/TC-10-004.md) | TC-10-004-AC1, TC-10-004-AC2 | python -m pytest tests/release/test_job_cancellation.py -q | artifacts/acceptance/TC-10-004/ |
| [TC-10-005](tickets/TC-10-005.md) | TC-10-005-AC1, TC-10-005-AC2 | python -m pytest tests/release/test_enqueue_consistency.py -q | artifacts/acceptance/TC-10-005/ |
| [TC-10-006](tickets/TC-10-006.md) | TC-10-006-AC1, TC-10-006-AC2 | python -m pytest tests/release/test_storage_checksums.py -q | artifacts/acceptance/TC-10-006/ |
| [TC-10-007](tickets/TC-10-007.md) | TC-10-007-AC1, TC-10-007-AC2 | python -m pytest tests/release/test_restart_persistence.py -q | artifacts/acceptance/TC-10-007/ |
| [TC-11-001](tickets/TC-11-001.md) | TC-11-001-AC1, TC-11-001-AC2 | python -m pytest tests/release/test_provider_adapter.py -q | artifacts/acceptance/TC-11-001/ |
| [TC-11-002](tickets/TC-11-002.md) | TC-11-002-AC1, TC-11-002-AC2 | python -m pytest tests/release/test_provider_budget.py -q | artifacts/acceptance/TC-11-002/ |
| [TC-11-003](tickets/TC-11-003.md) | TC-11-003-AC1, TC-11-003-AC2 | python -m pytest tests/release/test_structured_citations.py -q | artifacts/acceptance/TC-11-003/ |
| [TC-11-004](tickets/TC-11-004.md) | TC-11-004-AC1, TC-11-004-AC2 | python -m pytest tests/release/test_source_viewer.py -q | artifacts/acceptance/TC-11-004/ |
| [TC-11-005](tickets/TC-11-005.md) | TC-11-005-AC1, TC-11-005-AC2 | python -m pytest tests/release/test_grounding_policy.py -q | artifacts/acceptance/TC-11-005/ |
| [TC-11-006](tickets/TC-11-006.md) | TC-11-006-AC1, TC-11-006-AC2 | python -m pytest tests/release/test_confidence_semantics.py -q | artifacts/acceptance/TC-11-006/ |
| [TC-11-007](tickets/TC-11-007.md) | TC-11-007-AC1, TC-11-007-AC2 | python -m pytest tests/release/test_eval_corpus.py -q | artifacts/acceptance/TC-11-007/ |
| [TC-11-008](tickets/TC-11-008.md) | TC-11-008-AC1, TC-11-008-AC2 | python -m pytest tests/release/test_eval_real_model.py -q | artifacts/acceptance/TC-11-008/ |
| [TC-11-009](tickets/TC-11-009.md) | TC-11-009-AC1, TC-11-009-AC2 | python -m pytest tests/release/test_model_version_change.py -q | artifacts/acceptance/TC-11-009/ |
| [TC-12-001](tickets/TC-12-001.md) | TC-12-001-AC1, TC-12-001-AC2 | python -m pytest tests/release/test_answer_routing.py -q | artifacts/acceptance/TC-12-001/ |
| [TC-12-002](tickets/TC-12-002.md) | TC-12-002-AC1, TC-12-002-AC2 | python -m pytest tests/release/test_answer_revisions.py -q | artifacts/acceptance/TC-12-002/ |
| [TC-12-003](tickets/TC-12-003.md) | TC-12-003-AC1, TC-12-003-AC2 | python -m pytest tests/release/test_answer_approval.py -q | artifacts/acceptance/TC-12-003/ |
| [TC-12-004](tickets/TC-12-004.md) | TC-12-004-AC1, TC-12-004-AC2 | python -m pytest tests/release/test_approval_regeneration.py -q | artifacts/acceptance/TC-12-004/ |
| [TC-13-001](tickets/TC-13-001.md) | TC-13-001-AC1, TC-13-001-AC2 | python -m pytest tests/release/test_export_targets.py -q | artifacts/acceptance/TC-13-001/ |
| [TC-13-002](tickets/TC-13-002.md) | TC-13-002-AC1, TC-13-002-AC2 | python -m pytest tests/release/test_export_fidelity.py -q | artifacts/acceptance/TC-13-002/ |
| [TC-13-003](tickets/TC-13-003.md) | TC-13-003-AC1, TC-13-003-AC2 | python -m pytest tests/release/test_export_literal_text.py -q | artifacts/acceptance/TC-13-003/ |
| [TC-13-004](tickets/TC-13-004.md) | TC-13-004-AC1, TC-13-004-AC2 | python -m pytest tests/release/test_export_approval_policy.py -q | artifacts/acceptance/TC-13-004/ |
| [TC-13-005](tickets/TC-13-005.md) | TC-13-005-AC1, TC-13-005-AC2 | python -m pytest tests/release/test_export_failure.py -q | artifacts/acceptance/TC-13-005/ |
| [TC-13-006](tickets/TC-13-006.md) | TC-13-006-AC1, TC-13-006-AC2 | python -m pytest tests/release/test_export_pack.py -q | artifacts/acceptance/TC-13-006/ |
| [TC-14-001](tickets/TC-14-001.md) | TC-14-001-AC1, TC-14-001-AC2 | npx playwright test e2e/release/design-tokens.spec.ts | artifacts/acceptance/TC-14-001/ |
| [TC-14-002](tickets/TC-14-002.md) | TC-14-002-AC1, TC-14-002-AC2 | npx playwright test e2e/release/button-input.spec.ts | artifacts/acceptance/TC-14-002/ |
| [TC-14-003](tickets/TC-14-003.md) | TC-14-003-AC1, TC-14-003-AC2 | npx playwright test e2e/release/dialog-toast.spec.ts | artifacts/acceptance/TC-14-003/ |
| [TC-14-004](tickets/TC-14-004.md) | TC-14-004-AC1, TC-14-004-AC2 | npx playwright test e2e/release/tables-filters.spec.ts | artifacts/acceptance/TC-14-004/ |
| [TC-14-005](tickets/TC-14-005.md) | TC-14-005-AC1, TC-14-005-AC2 | npx playwright test e2e/release/state-components.spec.ts | artifacts/acceptance/TC-14-005/ |
| [TC-14-006](tickets/TC-14-006.md) | TC-14-006-AC1, TC-14-006-AC2 | npx playwright test e2e/release/responsive-shell.spec.ts | artifacts/acceptance/TC-14-006/ |
| [TC-14-007](tickets/TC-14-007.md) | TC-14-007-AC1, TC-14-007-AC2 | npx playwright test e2e/release/navigation-patterns.spec.ts | artifacts/acceptance/TC-14-007/ |
| [TC-14-008](tickets/TC-14-008.md) | TC-14-008-AC1, TC-14-008-AC2 | npx playwright test e2e/release/microcopy-states.spec.ts | artifacts/acceptance/TC-14-008/ |
| [TC-14-009](tickets/TC-14-009.md) | TC-14-009-AC1, TC-14-009-AC2 | npx playwright test e2e/release/a11y-controls.spec.ts | artifacts/acceptance/TC-14-009/ |
| [TC-14-010](tickets/TC-14-010.md) | TC-14-010-AC1, TC-14-010-AC2 | npx playwright test e2e/release/responsive-visual.spec.ts | artifacts/acceptance/TC-14-010/ |
| [TC-14-011](tickets/TC-14-011.md) | TC-14-011-AC1, TC-14-011-AC2 | npx playwright test e2e/release/motion-feedback.spec.ts | artifacts/acceptance/TC-14-011/ |
| [TC-14-012](tickets/TC-14-012.md) | TC-14-012-AC1, TC-14-012-AC2 | npx playwright test e2e/release/frontend-performance.spec.ts | artifacts/acceptance/TC-14-012/ |
| [TC-14-013](tickets/TC-14-013.md) | TC-14-013-AC1, TC-14-013-AC2 | npx playwright test e2e/release/browser-compat.spec.ts | artifacts/acceptance/TC-14-013/ |
| [TC-16-001](tickets/TC-16-001.md) | TC-16-001-AC1, TC-16-001-AC2 | python -m pytest tests/release/test_member_lifecycle.py -q | artifacts/acceptance/TC-16-001/ |
| [TC-16-002](tickets/TC-16-002.md) | TC-16-002-AC1, TC-16-002-AC2 | python -m pytest tests/release/test_workspace_switch.py -q | artifacts/acceptance/TC-16-002/ |
| [TC-16-003](tickets/TC-16-003.md) | TC-16-003-AC1, TC-16-003-AC2 | python -m pytest tests/release/test_audit_events.py -q | artifacts/acceptance/TC-16-003/ |
| [TC-16-004](tickets/TC-16-004.md) | TC-16-004-AC1, TC-16-004-AC2 | python -m pytest tests/release/test_api_keys.py -q | artifacts/acceptance/TC-16-004/ |
| [TC-16-005](tickets/TC-16-005.md) | TC-16-005-AC1, TC-16-005-AC2 | python -m pytest tests/release/test_api_contracts.py -q | artifacts/acceptance/TC-16-005/ |
| [TC-16-006](tickets/TC-16-006.md) | TC-16-006-AC1, TC-16-006-AC2 | python -m pytest tests/release/test_feature_flags.py -q | artifacts/acceptance/TC-16-006/ |
| [TC-19-001](tickets/TC-19-001.md) | TC-19-001-AC1, TC-19-001-AC2 | python -m pytest tests/release/test_message_provider_wiring.py -q | artifacts/acceptance/TC-19-001/ |
| [TC-19-002](tickets/TC-19-002.md) | TC-19-002-AC1, TC-19-002-AC2 | python -m pytest tests/release/test_slack_consent.py -q | artifacts/acceptance/TC-19-002/ |
| [TC-19-003](tickets/TC-19-003.md) | TC-19-003-AC1, TC-19-003-AC2 | python -m pytest tests/release/test_slack_ingestion.py -q | artifacts/acceptance/TC-19-003/ |
| [TC-19-004](tickets/TC-19-004.md) | TC-19-004-AC1, TC-19-004-AC2 | python -m pytest tests/release/test_slack_delivery.py -q | artifacts/acceptance/TC-19-004/ |
| [TC-19-005](tickets/TC-19-005.md) | TC-19-005-AC1, TC-19-005-AC2 | python -m pytest tests/release/test_gmail_consent.py -q | artifacts/acceptance/TC-19-005/ |
| [TC-19-006](tickets/TC-19-006.md) | TC-19-006-AC1, TC-19-006-AC2 | python -m pytest tests/release/test_gmail_ingestion.py -q | artifacts/acceptance/TC-19-006/ |
| [TC-19-007](tickets/TC-19-007.md) | TC-19-007-AC1, TC-19-007-AC2 | python -m pytest tests/release/test_gmail_delivery.py -q | artifacts/acceptance/TC-19-007/ |
| [TC-19-008](tickets/TC-19-008.md) | TC-19-008-AC1, TC-19-008-AC2 | python -m pytest tests/release/test_notification_delivery.py -q | artifacts/acceptance/TC-19-008/ |
| [TC-20-001](tickets/TC-20-001.md) | TC-20-001-AC1, TC-20-001-AC2 | python -m pytest tests/release/test_connector_adapter.py -q | artifacts/acceptance/TC-20-001/ |
| [TC-20-002](tickets/TC-20-002.md) | TC-20-002-AC1, TC-20-002-AC2 | python -m pytest tests/release/test_connector_credentials.py -q | artifacts/acceptance/TC-20-002/ |
| [TC-20-003](tickets/TC-20-003.md) | TC-20-003-AC1, TC-20-003-AC2 | python -m pytest tests/release/test_connector_scheduler.py -q | artifacts/acceptance/TC-20-003/ |
| [TC-20-004](tickets/TC-20-004.md) | TC-20-004-AC1, TC-20-004-AC2 | python -m pytest tests/release/test_connector_disconnect.py -q | artifacts/acceptance/TC-20-004/ |
| [TC-20-005](tickets/TC-20-005.md) | TC-20-005-AC1, TC-20-005-AC2 | python -m pytest tests/release/test_hris_contract.py -q | artifacts/acceptance/TC-20-005/ |
| [TC-20-006](tickets/TC-20-006.md) | TC-20-006-AC1, TC-20-006-AC2 | python -m pytest tests/release/test_hris_implementation.py -q | artifacts/acceptance/TC-20-006/ |
| [TC-20-007](tickets/TC-20-007.md) | TC-20-007-AC1, TC-20-007-AC2 | python -m pytest tests/release/test_hris_qualification.py -q | artifacts/acceptance/TC-20-007/ |
| [TC-24-001](tickets/TC-24-001.md) | TC-24-001-AC1, TC-24-001-AC2 | python -m pytest tests/release/test_billing_provider.py -q | artifacts/acceptance/TC-24-001/ |
| [TC-24-002](tickets/TC-24-002.md) | TC-24-002-AC1, TC-24-002-AC2 | python -m pytest tests/release/test_billing_lifecycle.py -q | artifacts/acceptance/TC-24-002/ |
| [TC-24-003](tickets/TC-24-003.md) | TC-24-003-AC1, TC-24-003-AC2 | python -m pytest tests/release/test_credit_ledger.py -q | artifacts/acceptance/TC-24-003/ |
| [TC-24-004](tickets/TC-24-004.md) | TC-24-004-AC1, TC-24-004-AC2 | python -m pytest tests/release/test_quota_enforcement.py -q | artifacts/acceptance/TC-24-004/ |
| [TC-24-005](tickets/TC-24-005.md) | TC-24-005-AC1, TC-24-005-AC2 | python -m pytest tests/release/test_billing_reconciliation.py -q | artifacts/acceptance/TC-24-005/ |
| [TC-26-001](tickets/TC-26-001.md) | TC-26-001-AC1, TC-26-001-AC2 | npx playwright test e2e/release/analytics-plan.spec.ts | artifacts/acceptance/TC-26-001/ |
| [TC-26-002](tickets/TC-26-002.md) | TC-26-002-AC1, TC-26-002-AC2 | npx playwright test e2e/release/analytics-property.spec.ts | artifacts/acceptance/TC-26-002/ |
| [TC-26-003](tickets/TC-26-003.md) | TC-26-003-AC1, TC-26-003-AC2 | npx playwright test e2e/release/analytics-consent.spec.ts | artifacts/acceptance/TC-26-003/ |
| [TC-26-004](tickets/TC-26-004.md) | TC-26-004-AC1, TC-26-004-AC2 | npx playwright test e2e/release/analytics-pageviews.spec.ts | artifacts/acceptance/TC-26-004/ |
| [TC-26-005](tickets/TC-26-005.md) | TC-26-005-AC1, TC-26-005-AC2 | npx playwright test e2e/release/analytics-events.spec.ts | artifacts/acceptance/TC-26-005/ |
| [TC-26-006](tickets/TC-26-006.md) | TC-26-006-AC1, TC-26-006-AC2 | npx playwright test e2e/release/analytics-private-boundary.spec.ts | artifacts/acceptance/TC-26-006/ |
| [TC-26-007](tickets/TC-26-007.md) | TC-26-007-AC1, TC-26-007-AC2 | npx playwright test e2e/release/analytics-filtering.spec.ts | artifacts/acceptance/TC-26-007/ |
| [TC-26-008](tickets/TC-26-008.md) | TC-26-008-AC1, TC-26-008-AC2, TC-26-008-AC3 | npx playwright test e2e/release/analytics-validation.spec.ts | artifacts/acceptance/TC-26-008/ |
| [TC-26-009](tickets/TC-26-009.md) | TC-26-009-AC1, TC-26-009-AC2 | npx playwright test e2e/release/analytics-report.spec.ts | artifacts/acceptance/TC-26-009/ |
| [TC-26-010](tickets/TC-26-010.md) | TC-26-010-AC1, TC-26-010-AC2 | npx playwright test e2e/release/analytics-embedded.spec.ts | artifacts/acceptance/TC-26-010/ |
| [TC-26-011](tickets/TC-26-011.md) | TC-26-011-AC1, TC-26-011-AC2 | npx playwright test e2e/release/analytics-search-console.spec.ts | artifacts/acceptance/TC-26-011/ |
| [TC-26-012](tickets/TC-26-012.md) | TC-26-012-AC1, TC-26-012-AC2 | npx playwright test e2e/release/analytics-transfer.spec.ts | artifacts/acceptance/TC-26-012/ |
| [TC-26-013](tickets/TC-26-013.md) | TC-26-013-AC1, TC-26-013-AC2 | npx playwright test e2e/release/analytics-notices.spec.ts | artifacts/acceptance/TC-26-013/ |
| [TC-26-014](tickets/TC-26-014.md) | TC-26-014-AC1, TC-26-014-AC2 | npx playwright test e2e/release/analytics-funnel.spec.ts | artifacts/acceptance/TC-26-014/ |
| [TC-26-015](tickets/TC-26-015.md) | TC-26-015-AC1, TC-26-015-AC2 | npx playwright test e2e/release/analytics-funnel-report.spec.ts | artifacts/acceptance/TC-26-015/ |
| [TC-27-001](tickets/TC-27-001.md) | TC-27-001-AC1, TC-27-001-AC2 | python -m pytest tests/release/test_backup_failure.py -q | artifacts/acceptance/TC-27-001/ |
| [TC-27-002](tickets/TC-27-002.md) | TC-27-002-AC1, TC-27-002-AC2 | python -m pytest tests/release/test_backup_complete.py -q | artifacts/acceptance/TC-27-002/ |
| [TC-27-003](tickets/TC-27-003.md) | TC-27-003-AC1, TC-27-003-AC2 | python -m pytest tests/release/test_restore_drill.py -q | artifacts/acceptance/TC-27-003/ |
| [TC-27-004](tickets/TC-27-004.md) | TC-27-004-AC1, TC-27-004-AC2 | python -m pytest tests/release/test_monitoring_alerts.py -q | artifacts/acceptance/TC-27-004/ |
| [TC-27-005](tickets/TC-27-005.md) | TC-27-005-AC1, TC-27-005-AC2 | python -m pytest tests/release/test_incident_runbooks.py -q | artifacts/acceptance/TC-27-005/ |
| [TC-27-006](tickets/TC-27-006.md) | TC-27-006-AC1, TC-27-006-AC2 | python -m pytest tests/release/test_capacity_load.py -q | artifacts/acceptance/TC-27-006/ |
| [TC-27-007](tickets/TC-27-007.md) | TC-27-007-AC1, TC-27-007-AC2 | python -m pytest tests/release/test_cost_model.py -q | artifacts/acceptance/TC-27-007/ |
| [TC-27-008](tickets/TC-27-008.md) | TC-27-008-AC1, TC-27-008-AC2 | python -m pytest tests/release/test_tls_dns_email.py -q | artifacts/acceptance/TC-27-008/ |
| [TC-27-009](tickets/TC-27-009.md) | TC-27-009-AC1, TC-27-009-AC2 | python -m pytest tests/release/test_ops_least_privilege.py -q | artifacts/acceptance/TC-27-009/ |
| [TC-28-001](tickets/TC-28-001.md) | TC-28-001-AC1, TC-28-001-AC2 | python -m pytest tests/release/test_regression_index.py -q | artifacts/acceptance/TC-28-001/ |
| [TC-28-002](tickets/TC-28-002.md) | TC-28-002-AC1, TC-28-002-AC2 | python -m pytest tests/release/test_full_stack_journey.py -q | artifacts/acceptance/TC-28-002/ |
| [TC-28-003](tickets/TC-28-003.md) | TC-28-003-AC1, TC-28-003-AC2 | python -m pytest tests/release/test_full_suite_journeys.py -q | artifacts/acceptance/TC-28-003/ |
| [TC-28-004](tickets/TC-28-004.md) | TC-28-004-AC1, TC-28-004-AC2 | python -m pytest tests/release/test_cross_browser_release.py -q | artifacts/acceptance/TC-28-004/ |
| [TC-28-005](tickets/TC-28-005.md) | TC-28-005-AC1, TC-28-005-AC2 | python -m pytest tests/release/test_failure_chaos.py -q | artifacts/acceptance/TC-28-005/ |
| [TC-28-006](tickets/TC-28-006.md) | TC-28-006-AC1, TC-28-006-AC2 | python -m pytest tests/release/test_release_gate.py -q | artifacts/acceptance/TC-28-006/ |
| [TC-29-001](tickets/TC-29-001.md) | TC-29-001-AC1, TC-29-001-AC2 | Manual evidence review: docs/acceptance/install-docs.md | artifacts/acceptance/TC-29-001/ |
| [TC-29-002](tickets/TC-29-002.md) | TC-29-002-AC1, TC-29-002-AC2 | Manual evidence review: docs/acceptance/architecture-docs.md | artifacts/acceptance/TC-29-002/ |
| [TC-29-003](tickets/TC-29-003.md) | TC-29-003-AC1, TC-29-003-AC2 | Manual evidence review: docs/acceptance/user-docs.md | artifacts/acceptance/TC-29-003/ |
| [TC-29-004](tickets/TC-29-004.md) | TC-29-004-AC1, TC-29-004-AC2 | Manual evidence review: docs/acceptance/operations-docs.md | artifacts/acceptance/TC-29-004/ |
| [TC-29-005](tickets/TC-29-005.md) | TC-29-005-AC1, TC-29-005-AC2 | Manual evidence review: docs/acceptance/demo-package.md | artifacts/acceptance/TC-29-005/ |
| [TC-29-006](tickets/TC-29-006.md) | TC-29-006-AC1, TC-29-006-AC2 | Manual evidence review: docs/acceptance/data-room.md | artifacts/acceptance/TC-29-006/ |
| [TC-30-001](tickets/TC-30-001.md) | TC-30-001-AC1, TC-30-001-AC2, TC-30-001-AC3 | Manual evidence review: docs/acceptance/buyer-accounts.md | artifacts/acceptance/TC-30-001/ |
| [TC-30-002](tickets/TC-30-002.md) | TC-30-002-AC1, TC-30-002-AC2 | Manual evidence review: docs/acceptance/buyer-install.md | artifacts/acceptance/TC-30-002/ |
| [TC-30-003](tickets/TC-30-003.md) | TC-30-003-AC1, TC-30-003-AC2 | Manual evidence review: docs/acceptance/buyer-recovery.md | artifacts/acceptance/TC-30-003/ |
| [TC-30-004](tickets/TC-30-004.md) | TC-30-004-AC1, TC-30-004-AC2 | Manual evidence review: docs/acceptance/asset-conveyance.md | artifacts/acceptance/TC-30-004/ |
| [TC-30-005](tickets/TC-30-005.md) | TC-30-005-AC1, TC-30-005-AC2 | Manual evidence review: docs/acceptance/support-cap.md | artifacts/acceptance/TC-30-005/ |
| [TC-30-006](tickets/TC-30-006.md) | TC-30-006-AC1, TC-30-006-AC2, TC-30-006-AC3 | Manual evidence review: docs/acceptance/buyer-signoff.md | artifacts/acceptance/TC-30-006/ |
| [TC-15-001](tickets/TC-15-001.md) | TC-15-001-AC1, TC-15-001-AC2, TC-15-001-AC3, TC-15-001-AC4, TC-15-001-AC5, TC-15-001-AC6, TC-15-001-AC7 | npx playwright test e2e/release/ui-01.spec.ts | artifacts/acceptance/TC-15-001/ |
| [TC-15-002](tickets/TC-15-002.md) | TC-15-002-AC1, TC-15-002-AC2, TC-15-002-AC3, TC-15-002-AC4, TC-15-002-AC5, TC-15-002-AC6 | npx playwright test e2e/release/ui-02.spec.ts | artifacts/acceptance/TC-15-002/ |
| [TC-15-003](tickets/TC-15-003.md) | TC-15-003-AC1, TC-15-003-AC2, TC-15-003-AC3, TC-15-003-AC4, TC-15-003-AC5, TC-15-003-AC6, TC-15-003-AC7, TC-15-003-AC8, TC-15-003-AC9, TC-15-003-AC10 | npx playwright test e2e/release/ui-03.spec.ts | artifacts/acceptance/TC-15-003/ |
| [TC-15-004](tickets/TC-15-004.md) | TC-15-004-AC1, TC-15-004-AC2, TC-15-004-AC3, TC-15-004-AC4, TC-15-004-AC5, TC-15-004-AC6, TC-15-004-AC7, TC-15-004-AC8 | npx playwright test e2e/release/ui-04.spec.ts | artifacts/acceptance/TC-15-004/ |
| [TC-15-005](tickets/TC-15-005.md) | TC-15-005-AC1, TC-15-005-AC2, TC-15-005-AC3, TC-15-005-AC4, TC-15-005-AC5, TC-15-005-AC6 | npx playwright test e2e/release/ui-05.spec.ts | artifacts/acceptance/TC-15-005/ |
| [TC-15-006](tickets/TC-15-006.md) | TC-15-006-AC1, TC-15-006-AC2, TC-15-006-AC3, TC-15-006-AC4, TC-15-006-AC5, TC-15-006-AC6 | npx playwright test e2e/release/ui-06.spec.ts | artifacts/acceptance/TC-15-006/ |
| [TC-15-007](tickets/TC-15-007.md) | TC-15-007-AC1, TC-15-007-AC2, TC-15-007-AC3, TC-15-007-AC4, TC-15-007-AC5, TC-15-007-AC6, TC-15-007-AC7 | npx playwright test e2e/release/ui-07.spec.ts | artifacts/acceptance/TC-15-007/ |
| [TC-15-008](tickets/TC-15-008.md) | TC-15-008-AC1, TC-15-008-AC2, TC-15-008-AC3, TC-15-008-AC4, TC-15-008-AC5, TC-15-008-AC6, TC-15-008-AC7 | npx playwright test e2e/release/ui-08.spec.ts | artifacts/acceptance/TC-15-008/ |
| [TC-15-009](tickets/TC-15-009.md) | TC-15-009-AC1, TC-15-009-AC2, TC-15-009-AC3, TC-15-009-AC4, TC-15-009-AC5, TC-15-009-AC6, TC-15-009-AC7, TC-15-009-AC8 | npx playwright test e2e/release/ui-09.spec.ts | artifacts/acceptance/TC-15-009/ |
| [TC-15-010](tickets/TC-15-010.md) | TC-15-010-AC1, TC-15-010-AC2, TC-15-010-AC3, TC-15-010-AC4, TC-15-010-AC5, TC-15-010-AC6 | npx playwright test e2e/release/ui-10.spec.ts | artifacts/acceptance/TC-15-010/ |
| [TC-15-011](tickets/TC-15-011.md) | TC-15-011-AC1, TC-15-011-AC2, TC-15-011-AC3, TC-15-011-AC4, TC-15-011-AC5 | npx playwright test e2e/release/ui-11.spec.ts | artifacts/acceptance/TC-15-011/ |
| [TC-15-012](tickets/TC-15-012.md) | TC-15-012-AC1, TC-15-012-AC2, TC-15-012-AC3, TC-15-012-AC4, TC-15-012-AC5, TC-15-012-AC6, TC-15-012-AC7, TC-15-012-AC8, TC-15-012-AC9, TC-15-012-AC10, TC-15-012-AC11 | npx playwright test e2e/release/ui-12.spec.ts | artifacts/acceptance/TC-15-012/ |
| [TC-15-013](tickets/TC-15-013.md) | TC-15-013-AC1, TC-15-013-AC2, TC-15-013-AC3, TC-15-013-AC4, TC-15-013-AC5 | npx playwright test e2e/release/ui-13-1.spec.ts | artifacts/acceptance/TC-15-013/ |
| [TC-15-014](tickets/TC-15-014.md) | TC-15-014-AC1, TC-15-014-AC2, TC-15-014-AC3, TC-15-014-AC4, TC-15-014-AC5 | npx playwright test e2e/release/ui-13-2.spec.ts | artifacts/acceptance/TC-15-014/ |
| [TC-15-015](tickets/TC-15-015.md) | TC-15-015-AC1, TC-15-015-AC2, TC-15-015-AC3, TC-15-015-AC4, TC-15-015-AC5, TC-15-015-AC6, TC-15-015-AC7, TC-15-015-AC8 | npx playwright test e2e/release/ui-14.spec.ts | artifacts/acceptance/TC-15-015/ |
| [TC-15-016](tickets/TC-15-016.md) | TC-15-016-AC1, TC-15-016-AC2, TC-15-016-AC3, TC-15-016-AC4, TC-15-016-AC5, TC-15-016-AC6, TC-15-016-AC7, TC-15-016-AC8, TC-15-016-AC9, TC-15-016-AC10, TC-15-016-AC11 | npx playwright test e2e/release/ui-15.spec.ts | artifacts/acceptance/TC-15-016/ |
| [TC-15-017](tickets/TC-15-017.md) | TC-15-017-AC1, TC-15-017-AC2, TC-15-017-AC3, TC-15-017-AC4, TC-15-017-AC5, TC-15-017-AC6, TC-15-017-AC7, TC-15-017-AC8, TC-15-017-AC9 | npx playwright test e2e/release/ui-16.spec.ts | artifacts/acceptance/TC-15-017/ |
| [TC-15-018](tickets/TC-15-018.md) | TC-15-018-AC1, TC-15-018-AC2, TC-15-018-AC3, TC-15-018-AC4, TC-15-018-AC5, TC-15-018-AC6, TC-15-018-AC7, TC-15-018-AC8, TC-15-018-AC9, TC-15-018-AC10 | npx playwright test e2e/release/ui-17.spec.ts | artifacts/acceptance/TC-15-018/ |
| [TC-15-019](tickets/TC-15-019.md) | TC-15-019-AC1, TC-15-019-AC2, TC-15-019-AC3, TC-15-019-AC4, TC-15-019-AC5 | npx playwright test e2e/release/ui-18.spec.ts | artifacts/acceptance/TC-15-019/ |
| [TC-15-020](tickets/TC-15-020.md) | TC-15-020-AC1, TC-15-020-AC2, TC-15-020-AC3, TC-15-020-AC4, TC-15-020-AC5, TC-15-020-AC6, TC-15-020-AC7, TC-15-020-AC8 | npx playwright test e2e/release/ui-19-1.spec.ts | artifacts/acceptance/TC-15-020/ |
| [TC-15-021](tickets/TC-15-021.md) | TC-15-021-AC1, TC-15-021-AC2, TC-15-021-AC3, TC-15-021-AC4, TC-15-021-AC5, TC-15-021-AC6, TC-15-021-AC7 | npx playwright test e2e/release/ui-19-2.spec.ts | artifacts/acceptance/TC-15-021/ |
| [TC-15-022](tickets/TC-15-022.md) | TC-15-022-AC1, TC-15-022-AC2, TC-15-022-AC3, TC-15-022-AC4, TC-15-022-AC5, TC-15-022-AC6, TC-15-022-AC7, TC-15-022-AC8, TC-15-022-AC9 | npx playwright test e2e/release/ui-20.spec.ts | artifacts/acceptance/TC-15-022/ |
| [TC-15-023](tickets/TC-15-023.md) | TC-15-023-AC1, TC-15-023-AC2, TC-15-023-AC3, TC-15-023-AC4, TC-15-023-AC5, TC-15-023-AC6, TC-15-023-AC7, TC-15-023-AC8, TC-15-023-AC9 | npx playwright test e2e/release/ui-21.spec.ts | artifacts/acceptance/TC-15-023/ |
| [TC-15-024](tickets/TC-15-024.md) | TC-15-024-AC1, TC-15-024-AC2, TC-15-024-AC3, TC-15-024-AC4 | npx playwright test e2e/release/ui-22.spec.ts | artifacts/acceptance/TC-15-024/ |
| [TC-15-025](tickets/TC-15-025.md) | TC-15-025-AC1, TC-15-025-AC2, TC-15-025-AC3, TC-15-025-AC4, TC-15-025-AC5, TC-15-025-AC6, TC-15-025-AC7, TC-15-025-AC8, TC-15-025-AC9 | npx playwright test e2e/release/ui-23.spec.ts | artifacts/acceptance/TC-15-025/ |
| [TC-15-026](tickets/TC-15-026.md) | TC-15-026-AC1, TC-15-026-AC2, TC-15-026-AC3, TC-15-026-AC4, TC-15-026-AC5, TC-15-026-AC6, TC-15-026-AC7, TC-15-026-AC8 | npx playwright test e2e/release/ui-24.spec.ts | artifacts/acceptance/TC-15-026/ |
| [TC-15-027](tickets/TC-15-027.md) | TC-15-027-AC1, TC-15-027-AC2, TC-15-027-AC3, TC-15-027-AC4, TC-15-027-AC5, TC-15-027-AC6, TC-15-027-AC7, TC-15-027-AC8, TC-15-027-AC9 | npx playwright test e2e/release/ui-25.spec.ts | artifacts/acceptance/TC-15-027/ |
| [TC-15-028](tickets/TC-15-028.md) | TC-15-028-AC1, TC-15-028-AC2, TC-15-028-AC3, TC-15-028-AC4, TC-15-028-AC5, TC-15-028-AC6, TC-15-028-AC7, TC-15-028-AC8, TC-15-028-AC9 | npx playwright test e2e/release/ui-26.spec.ts | artifacts/acceptance/TC-15-028/ |
| [TC-15-029](tickets/TC-15-029.md) | TC-15-029-AC1, TC-15-029-AC2, TC-15-029-AC3, TC-15-029-AC4, TC-15-029-AC5, TC-15-029-AC6, TC-15-029-AC7, TC-15-029-AC8, TC-15-029-AC9, TC-15-029-AC10 | npx playwright test e2e/release/ui-27.spec.ts | artifacts/acceptance/TC-15-029/ |
| [TC-15-030](tickets/TC-15-030.md) | TC-15-030-AC1, TC-15-030-AC2, TC-15-030-AC3, TC-15-030-AC4, TC-15-030-AC5, TC-15-030-AC6, TC-15-030-AC7, TC-15-030-AC8, TC-15-030-AC9 | npx playwright test e2e/release/ui-28.spec.ts | artifacts/acceptance/TC-15-030/ |
| [TC-15-031](tickets/TC-15-031.md) | TC-15-031-AC1, TC-15-031-AC2, TC-15-031-AC3, TC-15-031-AC4, TC-15-031-AC5, TC-15-031-AC6, TC-15-031-AC7, TC-15-031-AC8, TC-15-031-AC9 | npx playwright test e2e/release/ui-29.spec.ts | artifacts/acceptance/TC-15-031/ |
| [TC-15-032](tickets/TC-15-032.md) | TC-15-032-AC1, TC-15-032-AC2, TC-15-032-AC3, TC-15-032-AC4, TC-15-032-AC5, TC-15-032-AC6, TC-15-032-AC7, TC-15-032-AC8, TC-15-032-AC9 | npx playwright test e2e/release/ui-30.spec.ts | artifacts/acceptance/TC-15-032/ |
| [TC-15-033](tickets/TC-15-033.md) | TC-15-033-AC1, TC-15-033-AC2, TC-15-033-AC3, TC-15-033-AC4, TC-15-033-AC5, TC-15-033-AC6, TC-15-033-AC7, TC-15-033-AC8, TC-15-033-AC9, TC-15-033-AC10, TC-15-033-AC11, TC-15-033-AC12 | npx playwright test e2e/release/ui-31.spec.ts | artifacts/acceptance/TC-15-033/ |
| [TC-15-034](tickets/TC-15-034.md) | TC-15-034-AC1, TC-15-034-AC2, TC-15-034-AC3, TC-15-034-AC4, TC-15-034-AC5, TC-15-034-AC6, TC-15-034-AC7, TC-15-034-AC8 | npx playwright test e2e/release/ui-32.spec.ts | artifacts/acceptance/TC-15-034/ |
| [TC-15-035](tickets/TC-15-035.md) | TC-15-035-AC1, TC-15-035-AC2, TC-15-035-AC3, TC-15-035-AC4, TC-15-035-AC5, TC-15-035-AC6, TC-15-035-AC7, TC-15-035-AC8, TC-15-035-AC9, TC-15-035-AC10 | npx playwright test e2e/release/ui-33.spec.ts | artifacts/acceptance/TC-15-035/ |
| [TC-15-036](tickets/TC-15-036.md) | TC-15-036-AC1, TC-15-036-AC2, TC-15-036-AC3 | npx playwright test e2e/release/screen-connectors.spec.ts | artifacts/acceptance/TC-15-036/ |
| [TC-15-037](tickets/TC-15-037.md) | TC-15-037-AC1, TC-15-037-AC2, TC-15-037-AC3 | npx playwright test e2e/release/screen-credentials.spec.ts | artifacts/acceptance/TC-15-037/ |
| [TC-15-038](tickets/TC-15-038.md) | TC-15-038-AC1, TC-15-038-AC2, TC-15-038-AC3 | npx playwright test e2e/release/screen-jobs.spec.ts | artifacts/acceptance/TC-15-038/ |
| [TC-15-039](tickets/TC-15-039.md) | TC-15-039-AC1, TC-15-039-AC2, TC-15-039-AC3 | npx playwright test e2e/release/screen-trust-requests.spec.ts | artifacts/acceptance/TC-15-039/ |
| [TC-15-040](tickets/TC-15-040.md) | TC-15-040-AC1, TC-15-040-AC2, TC-15-040-AC3 | npx playwright test e2e/release/screen-shares.spec.ts | artifacts/acceptance/TC-15-040/ |
| [TC-15-041](tickets/TC-15-041.md) | TC-15-041-AC1, TC-15-041-AC2, TC-15-041-AC3 | npx playwright test e2e/release/screen-buyer-portal.spec.ts | artifacts/acceptance/TC-15-041/ |
| [TC-15-042](tickets/TC-15-042.md) | TC-15-042-AC1, TC-15-042-AC2, TC-15-042-AC3 | npx playwright test e2e/release/screen-controls.spec.ts | artifacts/acceptance/TC-15-042/ |
| [TC-15-043](tickets/TC-15-043.md) | TC-15-043-AC1, TC-15-043-AC2, TC-15-043-AC3 | npx playwright test e2e/release/screen-mappings.spec.ts | artifacts/acceptance/TC-15-043/ |
| [TC-15-044](tickets/TC-15-044.md) | TC-15-044-AC1, TC-15-044-AC2, TC-15-044-AC3 | npx playwright test e2e/release/screen-evidence-review.spec.ts | artifacts/acceptance/TC-15-044/ |
| [TC-15-045](tickets/TC-15-045.md) | TC-15-045-AC1, TC-15-045-AC2, TC-15-045-AC3 | npx playwright test e2e/release/screen-policies.spec.ts | artifacts/acceptance/TC-15-045/ |
| [TC-15-046](tickets/TC-15-046.md) | TC-15-046-AC1, TC-15-046-AC2, TC-15-046-AC3 | npx playwright test e2e/release/screen-monitoring.spec.ts | artifacts/acceptance/TC-15-046/ |
| [TC-15-047](tickets/TC-15-047.md) | TC-15-047-AC1, TC-15-047-AC2, TC-15-047-AC3 | npx playwright test e2e/release/screen-remediation.spec.ts | artifacts/acceptance/TC-15-047/ |
| [TC-15-048](tickets/TC-15-048.md) | TC-15-048-AC1, TC-15-048-AC2, TC-15-048-AC3 | npx playwright test e2e/release/screen-knowledge.spec.ts | artifacts/acceptance/TC-15-048/ |
| [TC-15-049](tickets/TC-15-049.md) | TC-15-049-AC1, TC-15-049-AC2, TC-15-049-AC3 | npx playwright test e2e/release/screen-deals.spec.ts | artifacts/acceptance/TC-15-049/ |
| [TC-15-050](tickets/TC-15-050.md) | TC-15-050-AC1, TC-15-050-AC2, TC-15-050-AC3 | npx playwright test e2e/release/screen-contracts.spec.ts | artifacts/acceptance/TC-15-050/ |
| [TC-15-051](tickets/TC-15-051.md) | TC-15-051-AC1, TC-15-051-AC2, TC-15-051-AC3 | npx playwright test e2e/release/screen-promises.spec.ts | artifacts/acceptance/TC-15-051/ |
| [TC-15-052](tickets/TC-15-052.md) | TC-15-052-AC1, TC-15-052-AC2, TC-15-052-AC3 | npx playwright test e2e/release/screen-billing.spec.ts | artifacts/acceptance/TC-15-052/ |
| [TC-15-053](tickets/TC-15-053.md) | TC-15-053-AC1, TC-15-053-AC2, TC-15-053-AC3 | npx playwright test e2e/release/screen-reports.spec.ts | artifacts/acceptance/TC-15-053/ |
| [TC-15-054](tickets/TC-15-054.md) | TC-15-054-AC1, TC-15-054-AC2, TC-15-054-AC3 | npx playwright test e2e/release/screen-analytics.spec.ts | artifacts/acceptance/TC-15-054/ |
| [TC-15-055](tickets/TC-15-055.md) | TC-15-055-AC1, TC-15-055-AC2, TC-15-055-AC3 | npx playwright test e2e/release/screen-traffic.spec.ts | artifacts/acceptance/TC-15-055/ |
| [TC-15-056](tickets/TC-15-056.md) | TC-15-056-AC1, TC-15-056-AC2, TC-15-056-AC3 | npx playwright test e2e/release/screen-trust-analytics.spec.ts | artifacts/acceptance/TC-15-056/ |
| [TC-15-057](tickets/TC-15-057.md) | TC-15-057-AC1, TC-15-057-AC2, TC-15-057-AC3 | npx playwright test e2e/release/screen-feedback.spec.ts | artifacts/acceptance/TC-15-057/ |
| [TC-15-058](tickets/TC-15-058.md) | TC-15-058-AC1, TC-15-058-AC2, TC-15-058-AC3 | npx playwright test e2e/release/screen-security-content.spec.ts | artifacts/acceptance/TC-15-058/ |
| [TC-15-059](tickets/TC-15-059.md) | TC-15-059-AC1, TC-15-059-AC2, TC-15-059-AC3 | npx playwright test e2e/release/screen-support.spec.ts | artifacts/acceptance/TC-15-059/ |
| [TC-15-060](tickets/TC-15-060.md) | TC-15-060-AC1, TC-15-060-AC2 | npx playwright test e2e/release/public-legal-pages.spec.ts | artifacts/acceptance/TC-15-060/ |
| [TC-15-061](tickets/TC-15-061.md) | TC-15-061-AC1, TC-15-061-AC2 | npx playwright test e2e/release/public-status-page.spec.ts | artifacts/acceptance/TC-15-061/ |
| [TC-15-062](tickets/TC-15-062.md) | TC-15-062-AC1, TC-15-062-AC2 | npx playwright test e2e/release/not-found-states.spec.ts | artifacts/acceptance/TC-15-062/ |
| [TC-15-063](tickets/TC-15-063.md) | TC-15-063-AC1, TC-15-063-AC2 | npx playwright test e2e/release/public-seo.spec.ts | artifacts/acceptance/TC-15-063/ |
| [TC-12-005](tickets/TC-12-005.md) | TC-12-005-AC1, TC-12-005-AC2, TC-12-005-AC3 | python -m pytest tests/release/test_domain_golden_answers.py -q | artifacts/acceptance/TC-12-005/ |
| [TC-12-006](tickets/TC-12-006.md) | TC-12-006-AC1, TC-12-006-AC2, TC-12-006-AC3 | python -m pytest tests/release/test_domain_answer_approval.py -q | artifacts/acceptance/TC-12-006/ |
| [TC-12-007](tickets/TC-12-007.md) | TC-12-007-AC1, TC-12-007-AC2, TC-12-007-AC3 | python -m pytest tests/release/test_domain_evidence_approval.py -q | artifacts/acceptance/TC-12-007/ |
| [TC-12-008](tickets/TC-12-008.md) | TC-12-008-AC1, TC-12-008-AC2, TC-12-008-AC3 | python -m pytest tests/release/test_domain_answer_tiers.py -q | artifacts/acceptance/TC-12-008/ |
| [TC-12-009](tickets/TC-12-009.md) | TC-12-009-AC1, TC-12-009-AC2, TC-12-009-AC3 | python -m pytest tests/release/test_domain_knowledge_packs.py -q | artifacts/acceptance/TC-12-009/ |
| [TC-12-010](tickets/TC-12-010.md) | TC-12-010-AC1, TC-12-010-AC2, TC-12-010-AC3 | python -m pytest tests/release/test_domain_citation_composer.py -q | artifacts/acceptance/TC-12-010/ |
| [TC-12-011](tickets/TC-12-011.md) | TC-12-011-AC1, TC-12-011-AC2, TC-12-011-AC3 | python -m pytest tests/release/test_domain_confidence_scoring.py -q | artifacts/acceptance/TC-12-011/ |
| [TC-12-012](tickets/TC-12-012.md) | TC-12-012-AC1, TC-12-012-AC2, TC-12-012-AC3 | python -m pytest tests/release/test_domain_confidence_routing.py -q | artifacts/acceptance/TC-12-012/ |
| [TC-12-013](tickets/TC-12-013.md) | TC-12-013-AC1, TC-12-013-AC2, TC-12-013-AC3 | python -m pytest tests/release/test_domain_evidence_cards.py -q | artifacts/acceptance/TC-12-013/ |
| [TC-12-014](tickets/TC-12-014.md) | TC-12-014-AC1, TC-12-014-AC2, TC-12-014-AC3 | python -m pytest tests/release/test_domain_feedback_capture.py -q | artifacts/acceptance/TC-12-014/ |
| [TC-17-001](tickets/TC-17-001.md) | TC-17-001-AC1, TC-17-001-AC2, TC-17-001-AC3 | python -m pytest tests/release/test_domain_trust_articles.py -q | artifacts/acceptance/TC-17-001/ |
| [TC-17-002](tickets/TC-17-002.md) | TC-17-002-AC1, TC-17-002-AC2, TC-17-002-AC3 | python -m pytest tests/release/test_domain_trust_center_publish.py -q | artifacts/acceptance/TC-17-002/ |
| [TC-17-003](tickets/TC-17-003.md) | TC-17-003-AC1, TC-17-003-AC2, TC-17-003-AC3 | python -m pytest tests/release/test_domain_security_page.py -q | artifacts/acceptance/TC-17-003/ |
| [TC-17-004](tickets/TC-17-004.md) | TC-17-004-AC1, TC-17-004-AC2, TC-17-004-AC3 | python -m pytest tests/release/test_domain_security_faq.py -q | artifacts/acceptance/TC-17-004/ |
| [TC-17-005](tickets/TC-17-005.md) | TC-17-005-AC1, TC-17-005-AC2, TC-17-005-AC3 | python -m pytest tests/release/test_domain_shareable_spaces.py -q | artifacts/acceptance/TC-17-005/ |
| [TC-17-006](tickets/TC-17-006.md) | TC-17-006-AC1, TC-17-006-AC2, TC-17-006-AC3 | python -m pytest tests/release/test_domain_nda_access.py -q | artifacts/acceptance/TC-17-006/ |
| [TC-17-007](tickets/TC-17-007.md) | TC-17-007-AC1, TC-17-007-AC2, TC-17-007-AC3 | python -m pytest tests/release/test_domain_buyer_portal.py -q | artifacts/acceptance/TC-17-007/ |
| [TC-18-001](tickets/TC-18-001.md) | TC-18-001-AC1, TC-18-001-AC2, TC-18-001-AC3 | python -m pytest tests/release/test_domain_trust_requests.py -q | artifacts/acceptance/TC-18-001/ |
| [TC-18-002](tickets/TC-18-002.md) | TC-18-002-AC1, TC-18-002-AC2, TC-18-002-AC3 | python -m pytest tests/release/test_domain_vendor_requests.py -q | artifacts/acceptance/TC-18-002/ |
| [TC-18-003](tickets/TC-18-003.md) | TC-18-003-AC1, TC-18-003-AC2, TC-18-003-AC3 | python -m pytest tests/release/test_domain_vendor_response.py -q | artifacts/acceptance/TC-18-003/ |
| [TC-21-001](tickets/TC-21-001.md) | TC-21-001-AC1, TC-21-001-AC2, TC-21-001-AC3 | python -m pytest tests/release/test_domain_compliance_frameworks.py -q | artifacts/acceptance/TC-21-001/ |
| [TC-21-002](tickets/TC-21-002.md) | TC-21-002-AC1, TC-21-002-AC2, TC-21-002-AC3 | python -m pytest tests/release/test_domain_controls.py -q | artifacts/acceptance/TC-21-002/ |
| [TC-21-003](tickets/TC-21-003.md) | TC-21-003-AC1, TC-21-003-AC2, TC-21-003-AC3 | python -m pytest tests/release/test_domain_compliance_controls.py -q | artifacts/acceptance/TC-21-003/ |
| [TC-21-004](tickets/TC-21-004.md) | TC-21-004-AC1, TC-21-004-AC2, TC-21-004-AC3 | python -m pytest tests/release/test_domain_compliance_evidence.py -q | artifacts/acceptance/TC-21-004/ |
| [TC-21-005](tickets/TC-21-005.md) | TC-21-005-AC1, TC-21-005-AC2, TC-21-005-AC3 | python -m pytest tests/release/test_domain_compliance_mappings.py -q | artifacts/acceptance/TC-21-005/ |
| [TC-21-006](tickets/TC-21-006.md) | TC-21-006-AC1, TC-21-006-AC2, TC-21-006-AC3 | python -m pytest tests/release/test_domain_compliance_gaps.py -q | artifacts/acceptance/TC-21-006/ |
| [TC-21-007](tickets/TC-21-007.md) | TC-21-007-AC1, TC-21-007-AC2, TC-21-007-AC3 | python -m pytest tests/release/test_domain_compliance_coverage.py -q | artifacts/acceptance/TC-21-007/ |
| [TC-21-008](tickets/TC-21-008.md) | TC-21-008-AC1, TC-21-008-AC2, TC-21-008-AC3 | python -m pytest tests/release/test_domain_compliance_alerts.py -q | artifacts/acceptance/TC-21-008/ |
| [TC-21-009](tickets/TC-21-009.md) | TC-21-009-AC1, TC-21-009-AC2, TC-21-009-AC3 | python -m pytest tests/release/test_domain_compliance_export.py -q | artifacts/acceptance/TC-21-009/ |
| [TC-21-010](tickets/TC-21-010.md) | TC-21-010-AC1, TC-21-010-AC2, TC-21-010-AC3 | python -m pytest tests/release/test_domain_compliance_audit.py -q | artifacts/acceptance/TC-21-010/ |
| [TC-21-011](tickets/TC-21-011.md) | TC-21-011-AC1, TC-21-011-AC2, TC-21-011-AC3 | python -m pytest tests/release/test_domain_ai_mappings.py -q | artifacts/acceptance/TC-21-011/ |
| [TC-21-012](tickets/TC-21-012.md) | TC-21-012-AC1, TC-21-012-AC2, TC-21-012-AC3 | python -m pytest tests/release/test_domain_ai_insights.py -q | artifacts/acceptance/TC-21-012/ |
| [TC-21-013](tickets/TC-21-013.md) | TC-21-013-AC1, TC-21-013-AC2, TC-21-013-AC3 | python -m pytest tests/release/test_domain_evidence_gaps.py -q | artifacts/acceptance/TC-21-013/ |
| [TC-22-001](tickets/TC-22-001.md) | TC-22-001-AC1, TC-22-001-AC2, TC-22-001-AC3 | python -m pytest tests/release/test_domain_ingestion.py -q | artifacts/acceptance/TC-22-001/ |
| [TC-22-002](tickets/TC-22-002.md) | TC-22-002-AC1, TC-22-002-AC2, TC-22-002-AC3 | python -m pytest tests/release/test_domain_control_engine.py -q | artifacts/acceptance/TC-22-002/ |
| [TC-22-003](tickets/TC-22-003.md) | TC-22-003-AC1, TC-22-003-AC2, TC-22-003-AC3 | python -m pytest tests/release/test_domain_control_timeline.py -q | artifacts/acceptance/TC-22-003/ |
| [TC-22-004](tickets/TC-22-004.md) | TC-22-004-AC1, TC-22-004-AC2, TC-22-004-AC3 | python -m pytest tests/release/test_domain_monitoring.py -q | artifacts/acceptance/TC-22-004/ |
| [TC-22-005](tickets/TC-22-005.md) | TC-22-005-AC1, TC-22-005-AC2, TC-22-005-AC3 | python -m pytest tests/release/test_domain_alert_management.py -q | artifacts/acceptance/TC-22-005/ |
| [TC-22-006](tickets/TC-22-006.md) | TC-22-006-AC1, TC-22-006-AC2, TC-22-006-AC3 | python -m pytest tests/release/test_domain_alerting_engine.py -q | artifacts/acceptance/TC-22-006/ |
| [TC-22-007](tickets/TC-22-007.md) | TC-22-007-AC1, TC-22-007-AC2, TC-22-007-AC3 | python -m pytest tests/release/test_domain_remediation.py -q | artifacts/acceptance/TC-22-007/ |
| [TC-22-008](tickets/TC-22-008.md) | TC-22-008-AC1, TC-22-008-AC2, TC-22-008-AC3 | python -m pytest tests/release/test_domain_freshness_policies.py -q | artifacts/acceptance/TC-22-008/ |
| [TC-22-009](tickets/TC-22-009.md) | TC-22-009-AC1, TC-22-009-AC2, TC-22-009-AC3 | python -m pytest tests/release/test_domain_signal_mapping.py -q | artifacts/acceptance/TC-22-009/ |
| [TC-22-010](tickets/TC-22-010.md) | TC-22-010-AC1, TC-22-010-AC2, TC-22-010-AC3 | python -m pytest tests/release/test_domain_sla_tracking.py -q | artifacts/acceptance/TC-22-010/ |
| [TC-22-011](tickets/TC-22-011.md) | TC-22-011-AC1, TC-22-011-AC2, TC-22-011-AC3 | python -m pytest tests/release/test_domain_operator_queue.py -q | artifacts/acceptance/TC-22-011/ |
| [TC-22-012](tickets/TC-22-012.md) | TC-22-012-AC1, TC-22-012-AC2, TC-22-012-AC3 | python -m pytest tests/release/test_domain_evidence_diff.py -q | artifacts/acceptance/TC-22-012/ |
| [TC-23-001](tickets/TC-23-001.md) | TC-23-001-AC1, TC-23-001-AC2, TC-23-001-AC3 | python -m pytest tests/release/test_domain_deals.py -q | artifacts/acceptance/TC-23-001/ |
| [TC-23-002](tickets/TC-23-002.md) | TC-23-002-AC1, TC-23-002-AC2, TC-23-002-AC3 | python -m pytest tests/release/test_domain_contracts.py -q | artifacts/acceptance/TC-23-002/ |
| [TC-23-003](tickets/TC-23-003.md) | TC-23-003-AC1, TC-23-003-AC2, TC-23-003-AC3 | python -m pytest tests/release/test_domain_promises.py -q | artifacts/acceptance/TC-23-003/ |
| [TC-23-004](tickets/TC-23-004.md) | TC-23-004-AC1, TC-23-004-AC2, TC-23-004-AC3 | python -m pytest tests/release/test_domain_proof_graph.py -q | artifacts/acceptance/TC-23-004/ |
| [TC-23-005](tickets/TC-23-005.md) | TC-23-005-AC1, TC-23-005-AC2, TC-23-005-AC3 | python -m pytest tests/release/test_domain_proof_widgets.py -q | artifacts/acceptance/TC-23-005/ |
| [TC-23-006](tickets/TC-23-006.md) | TC-23-006-AC1, TC-23-006-AC2, TC-23-006-AC3 | python -m pytest tests/release/test_domain_answer_outcomes.py -q | artifacts/acceptance/TC-23-006/ |
| [TC-13-007](tickets/TC-13-007.md) | TC-13-007-AC1, TC-13-007-AC2, TC-13-007-AC3 | python -m pytest tests/release/test_domain_export_pack.py -q | artifacts/acceptance/TC-13-007/ |
| [TC-25-001](tickets/TC-25-001.md) | TC-25-001-AC1, TC-25-001-AC2, TC-25-001-AC3 | python -m pytest tests/release/test_domain_dashboard_cards.py -q | artifacts/acceptance/TC-25-001/ |
| [TC-25-002](tickets/TC-25-002.md) | TC-25-002-AC1, TC-25-002-AC2, TC-25-002-AC3 | python -m pytest tests/release/test_domain_executive_dashboard.py -q | artifacts/acceptance/TC-25-002/ |
| [TC-25-003](tickets/TC-25-003.md) | TC-25-003-AC1, TC-25-003-AC2, TC-25-003-AC3 | python -m pytest tests/release/test_domain_benchmarks.py -q | artifacts/acceptance/TC-25-003/ |
| [TC-25-004](tickets/TC-25-004.md) | TC-25-004-AC1, TC-25-004-AC2, TC-25-004-AC3 | python -m pytest tests/release/test_domain_roi_calculator.py -q | artifacts/acceptance/TC-25-004/ |
| [TC-25-005](tickets/TC-25-005.md) | TC-25-005-AC1, TC-25-005-AC2, TC-25-005-AC3 | python -m pytest tests/release/test_domain_case_studies.py -q | artifacts/acceptance/TC-25-005/ |
| [TC-25-006](tickets/TC-25-006.md) | TC-25-006-AC1, TC-25-006-AC2, TC-25-006-AC3 | python -m pytest tests/release/test_domain_product_events.py -q | artifacts/acceptance/TC-25-006/ |
| [TC-25-007](tickets/TC-25-007.md) | TC-25-007-AC1, TC-25-007-AC2, TC-25-007-AC3 | python -m pytest tests/release/test_domain_reuse_analytics.py -q | artifacts/acceptance/TC-25-007/ |
| [TC-25-008](tickets/TC-25-008.md) | TC-25-008-AC1, TC-25-008-AC2, TC-25-008-AC3 | python -m pytest tests/release/test_domain_trust_center_analytics.py -q | artifacts/acceptance/TC-25-008/ |
| [TC-25-009](tickets/TC-25-009.md) | TC-25-009-AC1, TC-25-009-AC2, TC-25-009-AC3 | python -m pytest tests/release/test_domain_sli.py -q | artifacts/acceptance/TC-25-009/ |
| [TC-25-010](tickets/TC-25-010.md) | TC-25-010-AC1, TC-25-010-AC2, TC-25-010-AC3 | python -m pytest tests/release/test_domain_incident_pages.py -q | artifacts/acceptance/TC-25-010/ |
| [TC-25-011](tickets/TC-25-011.md) | TC-25-011-AC1, TC-25-011-AC2, TC-25-011-AC3 | python -m pytest tests/release/test_domain_demo_proof.py -q | artifacts/acceptance/TC-25-011/ |
| [TC-19-009](tickets/TC-19-009.md) | TC-19-009-AC1, TC-19-009-AC2, TC-19-009-AC3 | python -m pytest tests/release/test_domain_notifications.py -q | artifacts/acceptance/TC-19-009/ |
| [TC-19-010](tickets/TC-19-010.md) | TC-19-010-AC1, TC-19-010-AC2, TC-19-010-AC3 | python -m pytest tests/release/test_domain_in_app_notifications.py -q | artifacts/acceptance/TC-19-010/ |
| [TC-22-013](tickets/TC-22-013.md) | TC-22-013-AC1, TC-22-013-AC2 | python -m pytest tests/release/test_remediation_actions.py -q | artifacts/acceptance/TC-22-013/ |
| [TC-22-014](tickets/TC-22-014.md) | TC-22-014-AC1, TC-22-014-AC2 | python -m pytest tests/release/test_remediation_impact.py -q | artifacts/acceptance/TC-22-014/ |
| [TC-23-007](tickets/TC-23-007.md) | TC-23-007-AC1, TC-23-007-AC2 | python -m pytest tests/release/test_contract_extraction.py -q | artifacts/acceptance/TC-23-007/ |
| [TC-23-008](tickets/TC-23-008.md) | TC-23-008-AC1, TC-23-008-AC2 | python -m pytest tests/release/test_deal_risk.py -q | artifacts/acceptance/TC-23-008/ |
| [TC-20-008](tickets/TC-20-008.md) | TC-20-008-AC1, TC-20-008-AC2 | python -m pytest tests/release/test_provider_aws_connect.py -q | artifacts/acceptance/TC-20-008/ |
| [TC-20-009](tickets/TC-20-009.md) | TC-20-009-AC1, TC-20-009-AC2, TC-20-009-AC3 | python -m pytest tests/release/test_provider_aws_iam.py -q | artifacts/acceptance/TC-20-009/ |
| [TC-20-010](tickets/TC-20-010.md) | TC-20-010-AC1, TC-20-010-AC2, TC-20-010-AC3 | python -m pytest tests/release/test_provider_aws_s3.py -q | artifacts/acceptance/TC-20-010/ |
| [TC-20-011](tickets/TC-20-011.md) | TC-20-011-AC1, TC-20-011-AC2, TC-20-011-AC3 | python -m pytest tests/release/test_provider_aws_cloudtrail.py -q | artifacts/acceptance/TC-20-011/ |
| [TC-20-012](tickets/TC-20-012.md) | TC-20-012-AC1, TC-20-012-AC2, TC-20-012-AC3 | python -m pytest tests/release/test_provider_aws_securityhub.py -q | artifacts/acceptance/TC-20-012/ |
| [TC-20-013](tickets/TC-20-013.md) | TC-20-013-AC1, TC-20-013-AC2 | python -m pytest tests/release/test_provider_aws_qualify.py -q | artifacts/acceptance/TC-20-013/ |
| [TC-20-014](tickets/TC-20-014.md) | TC-20-014-AC1, TC-20-014-AC2 | python -m pytest tests/release/test_provider_github_connect.py -q | artifacts/acceptance/TC-20-014/ |
| [TC-20-015](tickets/TC-20-015.md) | TC-20-015-AC1, TC-20-015-AC2, TC-20-015-AC3 | python -m pytest tests/release/test_provider_github_repos.py -q | artifacts/acceptance/TC-20-015/ |
| [TC-20-016](tickets/TC-20-016.md) | TC-20-016-AC1, TC-20-016-AC2, TC-20-016-AC3 | python -m pytest tests/release/test_provider_github_access.py -q | artifacts/acceptance/TC-20-016/ |
| [TC-20-017](tickets/TC-20-017.md) | TC-20-017-AC1, TC-20-017-AC2, TC-20-017-AC3 | python -m pytest tests/release/test_provider_github_protection.py -q | artifacts/acceptance/TC-20-017/ |
| [TC-20-018](tickets/TC-20-018.md) | TC-20-018-AC1, TC-20-018-AC2, TC-20-018-AC3 | python -m pytest tests/release/test_provider_github_security.py -q | artifacts/acceptance/TC-20-018/ |
| [TC-20-019](tickets/TC-20-019.md) | TC-20-019-AC1, TC-20-019-AC2 | python -m pytest tests/release/test_provider_github_qualify.py -q | artifacts/acceptance/TC-20-019/ |
| [TC-20-020](tickets/TC-20-020.md) | TC-20-020-AC1, TC-20-020-AC2 | python -m pytest tests/release/test_provider_google_workspace_connect.py -q | artifacts/acceptance/TC-20-020/ |
| [TC-20-021](tickets/TC-20-021.md) | TC-20-021-AC1, TC-20-021-AC2, TC-20-021-AC3 | python -m pytest tests/release/test_provider_google_workspace_directory.py -q | artifacts/acceptance/TC-20-021/ |
| [TC-20-022](tickets/TC-20-022.md) | TC-20-022-AC1, TC-20-022-AC2, TC-20-022-AC3 | python -m pytest tests/release/test_provider_google_workspace_mfa.py -q | artifacts/acceptance/TC-20-022/ |
| [TC-20-023](tickets/TC-20-023.md) | TC-20-023-AC1, TC-20-023-AC2, TC-20-023-AC3 | python -m pytest tests/release/test_provider_google_workspace_roles.py -q | artifacts/acceptance/TC-20-023/ |
| [TC-20-024](tickets/TC-20-024.md) | TC-20-024-AC1, TC-20-024-AC2 | python -m pytest tests/release/test_provider_google_workspace_qualify.py -q | artifacts/acceptance/TC-20-024/ |
| [TC-20-025](tickets/TC-20-025.md) | TC-20-025-AC1, TC-20-025-AC2 | python -m pytest tests/release/test_provider_gcp_connect.py -q | artifacts/acceptance/TC-20-025/ |
| [TC-20-026](tickets/TC-20-026.md) | TC-20-026-AC1, TC-20-026-AC2, TC-20-026-AC3 | python -m pytest tests/release/test_provider_gcp_iam.py -q | artifacts/acceptance/TC-20-026/ |
| [TC-20-027](tickets/TC-20-027.md) | TC-20-027-AC1, TC-20-027-AC2, TC-20-027-AC3 | python -m pytest tests/release/test_provider_gcp_logs.py -q | artifacts/acceptance/TC-20-027/ |
| [TC-20-028](tickets/TC-20-028.md) | TC-20-028-AC1, TC-20-028-AC2, TC-20-028-AC3 | python -m pytest tests/release/test_provider_gcp_kms.py -q | artifacts/acceptance/TC-20-028/ |
| [TC-20-029](tickets/TC-20-029.md) | TC-20-029-AC1, TC-20-029-AC2, TC-20-029-AC3 | python -m pytest tests/release/test_provider_gcp_scc.py -q | artifacts/acceptance/TC-20-029/ |
| [TC-20-030](tickets/TC-20-030.md) | TC-20-030-AC1, TC-20-030-AC2 | python -m pytest tests/release/test_provider_gcp_qualify.py -q | artifacts/acceptance/TC-20-030/ |
| [TC-20-031](tickets/TC-20-031.md) | TC-20-031-AC1, TC-20-031-AC2 | python -m pytest tests/release/test_provider_azure_connect.py -q | artifacts/acceptance/TC-20-031/ |
| [TC-20-032](tickets/TC-20-032.md) | TC-20-032-AC1, TC-20-032-AC2, TC-20-032-AC3 | python -m pytest tests/release/test_provider_azure_directory.py -q | artifacts/acceptance/TC-20-032/ |
| [TC-20-033](tickets/TC-20-033.md) | TC-20-033-AC1, TC-20-033-AC2, TC-20-033-AC3 | python -m pytest tests/release/test_provider_azure_policies.py -q | artifacts/acceptance/TC-20-033/ |
| [TC-20-034](tickets/TC-20-034.md) | TC-20-034-AC1, TC-20-034-AC2, TC-20-034-AC3 | python -m pytest tests/release/test_provider_azure_security.py -q | artifacts/acceptance/TC-20-034/ |
| [TC-20-035](tickets/TC-20-035.md) | TC-20-035-AC1, TC-20-035-AC2 | python -m pytest tests/release/test_provider_azure_qualify.py -q | artifacts/acceptance/TC-20-035/ |
| [TC-20-036](tickets/TC-20-036.md) | TC-20-036-AC1, TC-20-036-AC2 | python -m pytest tests/release/test_provider_gitlab_connect.py -q | artifacts/acceptance/TC-20-036/ |
| [TC-20-037](tickets/TC-20-037.md) | TC-20-037-AC1, TC-20-037-AC2, TC-20-037-AC3 | python -m pytest tests/release/test_provider_gitlab_inventory.py -q | artifacts/acceptance/TC-20-037/ |
| [TC-20-038](tickets/TC-20-038.md) | TC-20-038-AC1, TC-20-038-AC2, TC-20-038-AC3 | python -m pytest tests/release/test_provider_gitlab_merge.py -q | artifacts/acceptance/TC-20-038/ |
| [TC-20-039](tickets/TC-20-039.md) | TC-20-039-AC1, TC-20-039-AC2, TC-20-039-AC3 | python -m pytest tests/release/test_provider_gitlab_scans.py -q | artifacts/acceptance/TC-20-039/ |
| [TC-20-040](tickets/TC-20-040.md) | TC-20-040-AC1, TC-20-040-AC2 | python -m pytest tests/release/test_provider_gitlab_qualify.py -q | artifacts/acceptance/TC-20-040/ |
| [TC-20-041](tickets/TC-20-041.md) | TC-20-041-AC1, TC-20-041-AC2 | python -m pytest tests/release/test_provider_okta_connect.py -q | artifacts/acceptance/TC-20-041/ |
| [TC-20-042](tickets/TC-20-042.md) | TC-20-042-AC1, TC-20-042-AC2, TC-20-042-AC3 | python -m pytest tests/release/test_provider_okta_directory.py -q | artifacts/acceptance/TC-20-042/ |
| [TC-20-043](tickets/TC-20-043.md) | TC-20-043-AC1, TC-20-043-AC2, TC-20-043-AC3 | python -m pytest tests/release/test_provider_okta_auth.py -q | artifacts/acceptance/TC-20-043/ |
| [TC-20-044](tickets/TC-20-044.md) | TC-20-044-AC1, TC-20-044-AC2, TC-20-044-AC3 | python -m pytest tests/release/test_provider_okta_tokens.py -q | artifacts/acceptance/TC-20-044/ |
| [TC-20-045](tickets/TC-20-045.md) | TC-20-045-AC1, TC-20-045-AC2 | python -m pytest tests/release/test_provider_okta_qualify.py -q | artifacts/acceptance/TC-20-045/ |
| [TC-20-046](tickets/TC-20-046.md) | TC-20-046-AC1, TC-20-046-AC2 | python -m pytest tests/release/test_provider_jira_connect.py -q | artifacts/acceptance/TC-20-046/ |
| [TC-20-047](tickets/TC-20-047.md) | TC-20-047-AC1, TC-20-047-AC2, TC-20-047-AC3 | python -m pytest tests/release/test_provider_jira_issues.py -q | artifacts/acceptance/TC-20-047/ |
| [TC-20-048](tickets/TC-20-048.md) | TC-20-048-AC1, TC-20-048-AC2 | python -m pytest tests/release/test_provider_jira_qualify.py -q | artifacts/acceptance/TC-20-048/ |
| [TC-20-049](tickets/TC-20-049.md) | TC-20-049-AC1, TC-20-049-AC2 | python -m pytest tests/release/test_crm_salesforce_connect.py -q | artifacts/acceptance/TC-20-049/ |
| [TC-20-050](tickets/TC-20-050.md) | TC-20-050-AC1, TC-20-050-AC2 | python -m pytest tests/release/test_crm_salesforce_data.py -q | artifacts/acceptance/TC-20-050/ |
| [TC-20-051](tickets/TC-20-051.md) | TC-20-051-AC1, TC-20-051-AC2 | python -m pytest tests/release/test_crm_salesforce_qualify.py -q | artifacts/acceptance/TC-20-051/ |
| [TC-20-052](tickets/TC-20-052.md) | TC-20-052-AC1, TC-20-052-AC2 | python -m pytest tests/release/test_crm_hubspot_connect.py -q | artifacts/acceptance/TC-20-052/ |
| [TC-20-053](tickets/TC-20-053.md) | TC-20-053-AC1, TC-20-053-AC2 | python -m pytest tests/release/test_crm_hubspot_data.py -q | artifacts/acceptance/TC-20-053/ |
| [TC-20-054](tickets/TC-20-054.md) | TC-20-054-AC1, TC-20-054-AC2 | python -m pytest tests/release/test_crm_hubspot_qualify.py -q | artifacts/acceptance/TC-20-054/ |
| [TC-26-016](tickets/TC-26-016.md) | TC-26-016-AC1, TC-26-016-AC2 | npx playwright test e2e/release/analytics-revenue.spec.ts | artifacts/acceptance/TC-26-016/ |
| [TC-26-017](tickets/TC-26-017.md) | TC-26-017-AC1, TC-26-017-AC2 | npx playwright test e2e/release/analytics-domain-events.spec.ts | artifacts/acceptance/TC-26-017/ |
| [TC-26-018](tickets/TC-26-018.md) | TC-26-018-AC1, TC-26-018-AC2 | npx playwright test e2e/release/analytics-telemetry.spec.ts | artifacts/acceptance/TC-26-018/ |
| [TC-08-010](tickets/TC-08-010.md) | TC-08-010-AC1, TC-08-010-AC2 | python -m pytest tests/release/test_unified_evidence_search.py -q | artifacts/acceptance/TC-08-010/ |
| [TC-08-011](tickets/TC-08-011.md) | TC-08-011-AC1, TC-08-011-AC2 | python -m pytest tests/release/test_tag_vocabulary.py -q | artifacts/acceptance/TC-08-011/ |
| [TC-15-064](tickets/TC-15-064.md) | TC-15-064-AC1, TC-15-064-AC2 | npx playwright test e2e/release/screen-operator-queue.spec.ts | artifacts/acceptance/TC-15-064/ |
| [TC-15-065](tickets/TC-15-065.md) | TC-15-065-AC1, TC-15-065-AC2 | npx playwright test e2e/release/public-share.spec.ts | artifacts/acceptance/TC-15-065/ |
| [TC-15-066](tickets/TC-15-066.md) | TC-15-066-AC1, TC-15-066-AC2 | npx playwright test e2e/release/public-buyer.spec.ts | artifacts/acceptance/TC-15-066/ |
| [TC-15-067](tickets/TC-15-067.md) | TC-15-067-AC1, TC-15-067-AC2 | npx playwright test e2e/release/public-nda.spec.ts | artifacts/acceptance/TC-15-067/ |
| [TC-09-007](tickets/TC-09-007.md) | TC-09-007-AC1, TC-09-007-AC2 | python -m pytest tests/release/test_legacy_conversion.py -q | artifacts/acceptance/TC-09-007/ |
| [TC-09-008](tickets/TC-09-008.md) | TC-09-008-AC1, TC-09-008-AC2 | python -m pytest tests/release/test_text_questionnaire.py -q | artifacts/acceptance/TC-09-008/ |
| [TC-17-008](tickets/TC-17-008.md) | TC-17-008-AC1, TC-17-008-AC2 | python -m pytest tests/release/test_portal_match.py -q | artifacts/acceptance/TC-17-008/ |
| [TC-17-009](tickets/TC-17-009.md) | TC-17-009-AC1, TC-17-009-AC2 | python -m pytest tests/release/test_portal_changes.py -q | artifacts/acceptance/TC-17-009/ |
| [TC-17-010](tickets/TC-17-010.md) | TC-17-010-AC1, TC-17-010-AC2 | python -m pytest tests/release/test_portal_escalations.py -q | artifacts/acceptance/TC-17-010/ |
| [TC-21-014](tickets/TC-21-014.md) | TC-21-014-AC1, TC-21-014-AC2 | python -m pytest tests/release/test_catalog_soc2.py -q | artifacts/acceptance/TC-21-014/ |
| [TC-21-015](tickets/TC-21-015.md) | TC-21-015-AC1, TC-21-015-AC2 | python -m pytest tests/release/test_catalog_hipaa.py -q | artifacts/acceptance/TC-21-015/ |
| [TC-21-016](tickets/TC-21-016.md) | TC-21-016-AC1, TC-21-016-AC2 | python -m pytest tests/release/test_catalog_iso27001.py -q | artifacts/acceptance/TC-21-016/ |
| [TC-21-017](tickets/TC-21-017.md) | TC-21-017-AC1, TC-21-017-AC2 | python -m pytest tests/release/test_catalog_nist_csf2.py -q | artifacts/acceptance/TC-21-017/ |
| [TC-21-018](tickets/TC-21-018.md) | TC-21-018-AC1, TC-21-018-AC2 | python -m pytest tests/release/test_catalog_nist80053.py -q | artifacts/acceptance/TC-21-018/ |
| [TC-21-019](tickets/TC-21-019.md) | TC-21-019-AC1, TC-21-019-AC2 | python -m pytest tests/release/test_catalog_nist800171.py -q | artifacts/acceptance/TC-21-019/ |
| [TC-21-020](tickets/TC-21-020.md) | TC-21-020-AC1, TC-21-020-AC2 | python -m pytest tests/release/test_catalog_sig.py -q | artifacts/acceptance/TC-21-020/ |
| [TC-21-021](tickets/TC-21-021.md) | TC-21-021-AC1, TC-21-021-AC2 | python -m pytest tests/release/test_catalog_caiq.py -q | artifacts/acceptance/TC-21-021/ |
| [TC-21-022](tickets/TC-21-022.md) | TC-21-022-AC1, TC-21-022-AC2 | python -m pytest tests/release/test_catalog_hitrust.py -q | artifacts/acceptance/TC-21-022/ |
| [TC-05-010](tickets/TC-05-010.md) | TC-05-010-AC1, TC-05-010-AC2 | python -m pytest tests/release/test_platform_operator.py -q | artifacts/acceptance/TC-05-010/ |
| [TC-26-019](tickets/TC-26-019.md) | TC-26-019-AC1, TC-26-019-AC2 | npx playwright test e2e/release/analytics-attribution.spec.ts | artifacts/acceptance/TC-26-019/ |
