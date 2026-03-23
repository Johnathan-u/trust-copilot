"""Question taxonomy/classifier (AI-01). Categorizes questions for prompt shaping."""

import re

CATEGORY_CONTROL = "control"
CATEGORY_POLICY = "policy"
CATEGORY_PROCEDURE = "procedure"
CATEGORY_EVIDENCE = "evidence_request"
CATEGORY_GENERAL = "general"


def classify_question(text: str | None) -> str:
    """Return question category: control, policy, procedure, evidence_request, or general."""
    if not text or len(text.strip()) < 5:
        return CATEGORY_GENERAL
    t = text.lower().strip()
    if re.search(r"\b(control|governance|oversight|ownership)\b", t):
        return CATEGORY_CONTROL
    if re.search(r"\b(policy|policies|written\s+policy|documented)\b", t):
        return CATEGORY_POLICY
    if re.search(r"\b(procedure|process|workflow|how\s+do)\b", t):
        return CATEGORY_PROCEDURE
    if re.search(r"\b(evidence|document|provide|attach|submit)\b", t):
        return CATEGORY_EVIDENCE
    return CATEGORY_GENERAL
