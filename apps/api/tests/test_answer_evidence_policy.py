"""Unit tests for answer_evidence_policy (gating + placeholder detection)."""

from unittest.mock import MagicMock

from app.services.answer_evidence_policy import (
    EXPORT_NOT_READY_PLACEHOLDER,
    INSUFFICIENT_EVIDENCE_TEXT,
    answer_text_for_export,
    classify_answer_status_from_text,
    is_insufficient_answer_text,
    is_placeholder_insufficient,
    should_skip_llm,
)


def test_insufficient_constant_has_period():
    assert INSUFFICIENT_EVIDENCE_TEXT.endswith(".")


def test_is_placeholder_insufficient_variants():
    assert is_placeholder_insufficient("Insufficient evidence.")
    assert is_placeholder_insufficient("insufficient evidence")
    assert is_placeholder_insufficient("")
    assert not is_placeholder_insufficient("We document access reviews annually.")


def test_is_insufficient_long_narrative():
    t = (
        "Insufficient evidence. The provided documentation does not specify whether we use VPNs for remote access."
    )
    assert is_insufficient_answer_text(t)


def test_is_insufficient_hedge_without_short_prefix():
    t = "The provided documentation does not specify whether the system is registered in a federal inventory."
    assert is_insufficient_answer_text(t)


def test_not_insufficient_substantive_answer():
    assert not is_insufficient_answer_text("We conduct annual access reviews per our security policy.")


def test_classify_answer_status_from_text():
    assert classify_answer_status_from_text("We document controls.") == "draft"
    assert classify_answer_status_from_text("Insufficient evidence. The docs do not specify X.") == "insufficient_evidence"


def test_answer_text_for_export():
    assert answer_text_for_export(text="Yes", status="draft") == "Yes"
    assert answer_text_for_export(text="Insufficient evidence.", status="insufficient_evidence") == EXPORT_NOT_READY_PLACEHOLDER
    assert (
        answer_text_for_export(text="Insufficient evidence. The docs do not specify.", status="draft")
        == EXPORT_NOT_READY_PLACEHOLDER
    )


def test_should_skip_llm_no_evidence():
    skip, reason = should_skip_llm(MagicMock(), [], False)
    assert skip and reason == "no_evidence"


def test_should_skip_llm_noise_floor(monkeypatch):
    from app.services import answer_evidence_policy as aep

    monkeypatch.setattr(aep, "only_low_tier_evidence", lambda db, ev, **kw: False)
    monkeypatch.setattr(aep, "evidence_top_score", lambda ev: 0.20)
    skip, reason = aep.should_skip_llm(MagicMock(), [{"score": 0.2}], True)
    assert skip and reason == "retrieval_noise_floor"


def test_should_skip_llm_weak_despite_control_mapping(monkeypatch):
    from app.services import answer_evidence_policy as aep

    monkeypatch.setattr(aep, "only_low_tier_evidence", lambda db, ev, **kw: False)
    monkeypatch.setattr(aep, "evidence_top_score", lambda ev: 0.28)
    skip, reason = aep.should_skip_llm(MagicMock(), [{"score": 0.28}], True)
    assert skip and reason == "weak_control_path"


def test_should_not_skip_strong_score_with_control(monkeypatch):
    from app.services import answer_evidence_policy as aep

    monkeypatch.setattr(aep, "only_low_tier_evidence", lambda db, ev, **kw: False)
    monkeypatch.setattr(aep, "evidence_top_score", lambda ev: 0.72)
    skip, reason = aep.should_skip_llm(MagicMock(), [{"score": 0.72}], True)
    assert not skip
