"""Regression tests for answer-generation prompt structure and tone controls."""

from app.services.prompt_builder import build_prompt
from app.services.answer_generation import (
    ALLOWED_MODELS,
    ALLOWED_RESPONSE_STYLES,
    RESPONSE_STYLE_TEMPERATURE,
    validate_answer_text,
    _strip_leading_phrases,
    _parse_batched_answers,
    _pool_embeddings,
    is_allowed_model,
    is_allowed_response_style,
    resolve_model,
    resolve_response_style,
    resolve_temperature_from_style,
)


def test_build_prompt_includes_professional_style_instructions() -> None:
    prompt = build_prompt(
        "Describe your access control policy.",
        evidence=[{"text": "We have a documented access control policy.", "metadata": {"filename": "policy.docx"}}],
    )
    assert "responding to a customer or auditor" in prompt
    assert "Insufficient evidence" in prompt


def test_strip_leading_phrases_removes_robotic_intro() -> None:
    text = "Based on the evidence provided, we enforce MFA for all admin accounts."
    cleaned = _strip_leading_phrases(text, [])
    # With no phrases configured, string is unchanged.
    assert cleaned == text


def test_validate_answer_text_blocks_banned_prefixes() -> None:
    blocked = validate_answer_text("As an AI, I cannot answer this.")
    assert blocked == ""


def test_validate_answer_text_keeps_normal_answer() -> None:
    ok = validate_answer_text("We maintain a documented information security policy approved annually by leadership.")
    assert ok.startswith("We maintain")


def test_resolve_model_allowed_values() -> None:
    assert resolve_model("gpt-4o-mini") == "gpt-4o-mini"
    assert resolve_model("gpt-4o") == "gpt-4o"
    assert resolve_model("gpt-4.1-mini") == "gpt-4.1-mini"


def test_resolve_model_invalid_defaults() -> None:
    assert resolve_model(None) == "gpt-4o-mini"
    assert resolve_model("") == "gpt-4o-mini"
    assert resolve_model("gpt-5") == "gpt-4o-mini"
    assert resolve_model("invalid") == "gpt-4o-mini"


def test_resolve_temperature_from_style() -> None:
    assert resolve_temperature_from_style("precise") == 0.2
    assert resolve_temperature_from_style("balanced") == 0.35
    assert resolve_temperature_from_style("natural") == 0.5
    assert resolve_temperature_from_style(None) == 0.35
    assert resolve_temperature_from_style("") == 0.35
    assert resolve_temperature_from_style("unknown") == 0.35


def test_is_allowed_model() -> None:
    for m in ALLOWED_MODELS:
        assert is_allowed_model(m) is True
    assert is_allowed_model("gpt-9000") is False
    assert is_allowed_model("invalid") is False
    assert is_allowed_model(None) is False
    assert is_allowed_model("") is False
    assert is_allowed_model("  ") is False


def test_is_allowed_response_style() -> None:
    for s in ALLOWED_RESPONSE_STYLES:
        assert is_allowed_response_style(s) is True
    assert is_allowed_response_style("Precise") is True
    assert is_allowed_response_style("BALANCED") is True
    assert is_allowed_response_style("Natural") is True
    assert is_allowed_response_style("invalid") is False
    assert is_allowed_response_style(None) is False
    assert is_allowed_response_style("") is False
    assert is_allowed_response_style("  ") is False


def test_resolve_response_style() -> None:
    assert resolve_response_style("precise") == "precise"
    assert resolve_response_style("balanced") == "balanced"
    assert resolve_response_style("natural") == "natural"
    assert resolve_response_style("Precise") == "precise"
    assert resolve_response_style("BALANCED") == "balanced"
    assert resolve_response_style("Natural") == "natural"
    assert resolve_response_style(None) == "balanced"
    assert resolve_response_style("") == "balanced"
    assert resolve_response_style("invalid") == "balanced"
    assert resolve_response_style("unknown") == "balanced"


def test_temperature_mapping_consistent() -> None:
    """Precise → 0.2, Balanced → 0.35, Natural → 0.5. Natural must be 0.5 (not 0.6)."""
    assert RESPONSE_STYLE_TEMPERATURE["precise"] == 0.2
    assert RESPONSE_STYLE_TEMPERATURE["balanced"] == 0.35
    assert RESPONSE_STYLE_TEMPERATURE["natural"] == 0.5
    assert resolve_temperature_from_style("natural") == 0.5


def test_invalid_model_resolution_returns_allowed_model() -> None:
    """Invalid or missing model must never reach OpenAI; resolution returns an allowed model."""
    from app.services.answer_generation import DEFAULT_MODEL

    assert resolve_model("gpt-9000") in ALLOWED_MODELS
    assert resolve_model("invalid") in ALLOWED_MODELS
    assert resolve_model(None) == DEFAULT_MODEL
    assert resolve_model("") == DEFAULT_MODEL


def test_invalid_style_resolution_returns_allowed_temperature() -> None:
    """Invalid or missing style must produce a safe temperature from mapping."""
    from app.services.answer_generation import DEFAULT_TEMPERATURE

    assert resolve_temperature_from_style("invalid") == DEFAULT_TEMPERATURE
    assert resolve_temperature_from_style(None) == DEFAULT_TEMPERATURE
    assert resolve_temperature_from_style(resolve_response_style("invalid")) == DEFAULT_TEMPERATURE


def test_parse_batched_answers_standard_format() -> None:
    raw = "Answer 1: We use MFA.\n\nAnswer 2: We audit annually."
    out = _parse_batched_answers(raw, 2)
    assert out is not None
    assert out == ["We use MFA.", "We audit annually."]


def test_parse_batched_answers_with_headings_and_blank_lines() -> None:
    raw = "## Answer 1:\n\nFirst response here.\n\n\nAnswer 2: Second response."
    out = _parse_batched_answers(raw, 2)
    assert out is not None
    assert "First response" in out[0]
    assert "Second response" in out[1]


def test_parse_batched_answers_unnumbered_returns_none() -> None:
    """Unnumbered output is ambiguous; we do not map by block order. Returns None so caller uses per-question generation."""
    raw = "We use MFA for all users.\n\nWe conduct annual audits."
    out = _parse_batched_answers(raw, 2)
    assert out is None


def test_parse_batched_answers_returns_none_when_insufficient() -> None:
    assert _parse_batched_answers("Answer 1: Only one.", 2) is None
    assert _parse_batched_answers("", 1) is None
    assert _parse_batched_answers("  \n  ", 1) is None


def test_pool_embeddings_normalizes_and_returns_unit_vector() -> None:
    # Two 3-d embeddings; average then L2-normalize.
    a, b = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]
    out = _pool_embeddings([a, b])
    assert out is not None
    assert len(out) == 3
    dot = sum(x * x for x in out) ** 0.5
    assert abs(dot - 1.0) < 1e-6


def test_pool_embeddings_returns_none_when_empty() -> None:
    assert _pool_embeddings([]) is None
    assert _pool_embeddings([None]) is None
