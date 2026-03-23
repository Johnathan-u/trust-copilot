"""Tests for pilot product features: evidence gaps, coverage scoring, speed optimizations."""

import json
from unittest.mock import MagicMock, patch

from app.services.answer_cache import _cache_key, batch_get, batch_set
from app.services.answer_evidence_policy import only_low_tier_evidence, prioritize_evidence_for_answer
from app.services.answer_generation import (
    DEFAULT_MODEL,
    DEFAULT_RESPONSE_STYLE,
    _job_payload,
    resolve_model,
    resolve_response_style,
    validate_answer_text,
)
from app.services.coverage_score import _health_label
from app.services.evidence_gap_service import generate_gap_analysis
from app.services.retrieval import RetrievalService
from app.models.evidence_gap import GAP_STATUSES, GAP_TYPES, EvidenceGap


# ─── Unit tests: answer_cache.batch_get / batch_set ───


class TestAnswerCacheBatch:
    """Test batch cache operations (D1 optimization)."""

    def test_batch_get_empty_keys(self):
        result = batch_get(MagicMock(), [])
        assert result == {}

    def test_batch_set_empty_entries(self):
        batch_set(MagicMock(), [])

    def test_cache_key_deterministic(self):
        k1 = _cache_key(1, "abc", "balanced", "fp123")
        k2 = _cache_key(1, "abc", "balanced", "fp123")
        assert k1 == k2
        k3 = _cache_key(1, "abc", "precise", "fp123")
        assert k1 != k3

    def test_cache_key_different_workspace(self):
        k1 = _cache_key(1, "abc", "balanced", "fp")
        k2 = _cache_key(2, "abc", "balanced", "fp")
        assert k1 != k2


# ─── Unit tests: coverage_score ───


class TestCoverageScore:
    """Test coverage score calculation."""

    def test_health_label_high(self):
        assert _health_label(85.0) == "high"
        assert _health_label(80.0) == "high"
        assert _health_label(100.0) == "high"

    def test_health_label_medium(self):
        assert _health_label(50.0) == "medium"
        assert _health_label(79.9) == "medium"

    def test_health_label_low(self):
        assert _health_label(0.0) == "low"
        assert _health_label(49.9) == "low"


# ─── Unit tests: evidence_gap_service ───


class TestEvidenceGapService:
    """Test evidence gap analysis service."""

    def test_generate_gap_analysis_no_api_key(self):
        with patch("app.services.evidence_gap_service.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key="")
            result = generate_gap_analysis("What is your DR plan?")
            assert result is None

    @patch("app.services.evidence_gap_service.get_settings")
    def test_generate_gap_analysis_success(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="test-key",
            mapping_classification_model="gpt-4o-mini",
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "gap_type": "missing_procedure_detail",
            "reason": "No disaster recovery procedure documented",
            "proposed_policy_addition": "The Company shall maintain a formal DR plan...",
            "suggested_evidence_doc_title": "DR Policy",
            "confidence": 0.85,
        })

        with patch("app.services.mapping_llm_classify._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_fn.return_value = mock_client

            result = generate_gap_analysis(
                "What is your disaster recovery plan?",
                classification={"frameworks": ["SOC 2"], "subjects": ["Business Continuity"]},
            )

        assert result is not None
        assert result["gap_type"] == "missing_procedure_detail"
        assert "DR" in result["reason"] or "disaster" in result["reason"].lower()
        assert result["confidence"] == 0.85

    @patch("app.services.evidence_gap_service.get_settings")
    def test_generate_gap_analysis_invalid_gap_type_defaults_to_other(self, mock_settings):
        mock_settings.return_value = MagicMock(
            openai_api_key="test-key",
            mapping_classification_model="gpt-4o-mini",
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "gap_type": "nonexistent_type",
            "reason": "Missing something",
            "proposed_policy_addition": "Add this policy",
            "confidence": 0.5,
        })

        with patch("app.services.mapping_llm_classify._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_client_fn.return_value = mock_client

            result = generate_gap_analysis("Test question")

        assert result is not None
        assert result["gap_type"] == "other"

    @patch("app.services.evidence_gap_service.time.sleep")
    @patch("app.services.evidence_gap_service.get_settings")
    def test_generate_gap_analysis_llm_failure_returns_none(self, mock_settings, _mock_sleep):
        mock_settings.return_value = MagicMock(
            openai_api_key="test-key",
            mapping_classification_model="gpt-4o-mini",
        )

        with patch("app.services.mapping_llm_classify._get_client") as mock_client_fn:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception("API error")
            mock_client_fn.return_value = mock_client

            result = generate_gap_analysis("Test question")

        assert result is None


# ─── Unit tests: EvidenceGap model ───


class TestEvidenceGapModel:
    """Test EvidenceGap model and constants."""

    def test_gap_types_defined(self):
        assert "missing_procedure_detail" in GAP_TYPES
        assert "missing_control_statement" in GAP_TYPES
        assert "other" in GAP_TYPES

    def test_gap_statuses_defined(self):
        assert "open" in GAP_STATUSES
        assert "accepted" in GAP_STATUSES
        assert "dismissed" in GAP_STATUSES

    def test_model_tablename(self):
        assert EvidenceGap.__tablename__ == "evidence_gaps"


# ─── Unit tests: answer_evidence_policy with doc_tier_cache ───


class TestEvidencePolicyTierCache:
    """Test document tier cache threading (D5 optimization)."""

    def test_prioritize_evidence_empty_list(self):
        result = prioritize_evidence_for_answer(MagicMock(), [])
        assert result == []

    def test_only_low_tier_evidence_with_cache(self):
        cache = {1: 3, 2: 3}
        evidence = [
            {"metadata": {"document_id": 1}, "score": 0.9},
            {"metadata": {"document_id": 2}, "score": 0.8},
        ]
        assert only_low_tier_evidence(MagicMock(), evidence, doc_tier_cache=cache) is True

    def test_not_all_low_tier_with_cache(self):
        cache = {1: 0, 2: 3}
        evidence = [
            {"metadata": {"document_id": 1}, "score": 0.9},
            {"metadata": {"document_id": 2}, "score": 0.8},
        ]
        assert only_low_tier_evidence(MagicMock(), evidence, doc_tier_cache=cache) is False


# ─── Unit tests: validate_answer_text (regression) ───


class TestAnswerGenRegression:
    """Regression tests to ensure existing answer generation behavior is preserved."""

    def test_validate_answer_text_empty(self):
        assert validate_answer_text(None) == ""
        assert validate_answer_text("") == ""

    def test_validate_answer_text_banned_prefix(self):
        assert validate_answer_text("Sorry, I cannot answer that") == ""
        assert validate_answer_text("As an AI, I cannot") == ""

    def test_validate_answer_text_normal(self):
        result = validate_answer_text("We maintain SOC 2 Type II certification.")
        assert result == "We maintain SOC 2 Type II certification."

    def test_validate_answer_text_strips_meta_phrases(self):
        result = validate_answer_text("Based on the evidence provided, we maintain SOC 2.")
        assert result.startswith("We maintain") or result.startswith("we maintain")

    def test_validate_answer_text_truncates(self):
        long_text = "x" * 5000
        result = validate_answer_text(long_text)
        assert len(result) <= 4000


# ─── Unit tests: timing instrumentation (D7) ───


class TestTimingInstrumentation:
    """Verify timing stats are present in run_stats."""

    def test_job_payload_includes_timing(self):
        stats = {
            "drafted": 5,
            "insufficient_evidence": 2,
            "skipped_gated": 1,
            "llm_calls": 4,
            "embed_time_ms": 123.4,
            "retrieval_time_ms": 456.7,
            "gating_time_ms": 12.3,
            "llm_time_ms": 789.0,
            "duration_ms": 1500.0,
        }
        payload = json.loads(_job_payload(7, 10, stats))
        assert payload["generated"] == 7
        assert payload["total"] == 10
        assert payload["stats"]["embed_time_ms"] == 123.4
        assert payload["stats"]["retrieval_time_ms"] == 456.7


# ─── Unit tests: resolve_model / resolve_response_style (regression) ───


class TestModelResolution:
    """Ensure model/style resolution behavior is unchanged."""

    def test_resolve_model_default(self):
        assert resolve_model(None) == DEFAULT_MODEL
        assert resolve_model("") == DEFAULT_MODEL

    def test_resolve_model_allowed(self):
        assert resolve_model("gpt-4o-mini") == "gpt-4o-mini"
        assert resolve_model("gpt-4o") == "gpt-4o"

    def test_resolve_model_unsupported(self):
        assert resolve_model("gpt-3.5-turbo") == DEFAULT_MODEL

    def test_resolve_response_style_default(self):
        assert resolve_response_style(None) == DEFAULT_RESPONSE_STYLE

    def test_resolve_response_style_allowed(self):
        assert resolve_response_style("precise") == "precise"
        assert resolve_response_style("BALANCED") == "balanced"
        assert resolve_response_style("natural") == "natural"


# ─── Unit tests: batch retrieval (D2) ───


class TestBatchRetrieval:
    """Test batch retrieval service."""

    def test_batch_search_empty_queries(self):
        mock_db = MagicMock()
        svc = RetrievalService(mock_db)
        result = svc.batch_search(1, [])
        assert result == []
