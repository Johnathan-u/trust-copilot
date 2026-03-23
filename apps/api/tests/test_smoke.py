"""Smoke tests for core modules (RES-06)."""

def test_imports() -> None:
    """Core imports work."""
    from app.services.xlsx_writer import create_export_from_questionnaire
    from app.services.docx_writer import create_export_from_questionnaire_docx
    from app.services.fallback_export import create_fallback_pack_docx
    from app.services.retrieval import RetrievalService
    from app.services.prompt_builder import build_prompt
    from app.services.question_classifier import classify_question
    assert callable(create_export_from_questionnaire)
    assert callable(build_prompt)
    assert classify_question("Does the company have a security policy?") in ("control", "policy", "general")
