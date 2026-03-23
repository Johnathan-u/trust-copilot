"""Prompt builder for answer generation (AI-02, AI-01).

Accuracy-optimized: per-question evidence sections in batched prompts,
LLM classification labels fed into prompt context for domain-aware answers.
Framework metadata shapes answer style but never substitutes for evidence.
"""

from app.services.question_classifier import classify_question

_FRAMEWORK_STYLE_HINTS: dict[str, str] = {
    "SOC 2": "Use trust-services terminology (availability, processing integrity, confidentiality, privacy) where appropriate.",
    "HIPAA": "Reference applicable safeguard categories (administrative, physical, technical) where supported by evidence.",
    "ISO 27001": "Reference ISMS controls and Annex A controls where supported by evidence.",
    "ISO/IEC 27001": "Reference ISMS controls and Annex A controls where supported by evidence.",
    "NIST CSF 2.0": "Reference CSF functions (Govern, Identify, Protect, Detect, Respond, Recover) where supported by evidence.",
    "NIST SP 800-53": "Reference control families where supported by evidence.",
    "NIST SP 800-171": "Reference CUI protection requirements where supported by evidence.",
    "SIG": "Frame answers in terms of third-party risk management and vendor due diligence.",
    "Shared Assessments SIG": "Frame answers in terms of third-party risk management and vendor due diligence.",
    "CAIQ": "Frame answers in terms of cloud service provider controls and shared responsibility.",
    "CSA CAIQ": "Frame answers in terms of cloud service provider controls and shared responsibility.",
}


def _format_evidence(evidence: list[dict], limit: int = 10) -> str:
    """Format evidence list into block text with source attribution."""
    parts = []
    for e in evidence[:limit]:
        text = e.get("text", "")
        meta = e.get("metadata") or {}
        src = meta.get("filename", "document")
        parts.append(f"[{src}]: {text}")
    return "\n\n".join(parts)


def _framework_style_context(classification_labels: dict | None) -> str:
    """Build framework-specific style hint from classification labels."""
    if not classification_labels:
        return ""
    frameworks = classification_labels.get("frameworks", [])
    subjects = classification_labels.get("subjects", [])
    parts: list[str] = []
    if frameworks:
        parts.append(f"Frameworks: {', '.join(frameworks)}")
    if subjects:
        parts.append(f"Subjects: {', '.join(subjects)}")
    context = ""
    if parts:
        context = f"\nClassification context: {'; '.join(parts)}\n"
    style_hints: list[str] = []
    for fw in frameworks:
        hint = _FRAMEWORK_STYLE_HINTS.get(fw)
        if hint:
            style_hints.append(hint)
    if style_hints:
        context += f"Style guidance: {' '.join(style_hints)}\n"
    return context


def build_prompt(
    question: str,
    evidence: list[dict],
    instructions: str = "",
    classification_labels: dict | None = None,
) -> str:
    """Single-question prompt with evidence, category hint, and optional classification labels."""
    category = classify_question(question)
    evidence_text = _format_evidence(evidence)
    hint = _category_instruction(category)
    label_context = _framework_style_context(classification_labels)
    return f"""Question: {question}
{label_context}
Evidence:
{evidence_text}

Instructions: {hint} Write the answer as if you are responding to a customer or auditor. Use natural, professional language and complete sentences, and write in the first person plural ("we") when describing the organization's controls, policies, and procedures. Do not include meta-commentary such as "Based on the evidence above" or "According to the documentation" unless the question explicitly asks for that phrasing. Avoid long bullet lists unless the question clearly requests a list. Prefer truthful incompleteness over confident overclaiming: only state what the evidence supports. Framework metadata may shape answer style but must never substitute for missing evidence. If the evidence does not substantiate a direct yes/no, say so or respond with exactly "Insufficient evidence." Do not infer federal obligations, alternate processing sites, or compliance attestations without explicit supporting text. Be concise but complete.
{instructions}
"""


def _category_instruction(category: str) -> str:
    if category == "control":
        return "Provide a direct, authoritative description of how we design, operate, and monitor this control, focusing on ownership, governance, and oversight, and cite specific evidence when possible."
    if category == "policy":
        return "Name the relevant policy or document (including the filename from evidence when available) and describe in clear, plain language what it requires or states."
    if category == "procedure":
        return "Explain the operational process in clear active voice, describing what we do, who is responsible, and when it occurs; cite evidence if available."
    if category == "evidence_request":
        return "List or describe the requested artifacts or documents in a factual, professional way. If there is no relevant evidence in context, say 'No evidence provided'."
    return "Answer based on the provided evidence in a natural, professional tone, and say 'Insufficient evidence.' only when there is no relevant supporting information."


def build_batched_prompt(
    questions: list[str],
    evidence: list[dict],
    per_question_evidence: list[list[dict]] | None = None,
    classification_labels: list[dict | None] | None = None,
) -> str:
    """Build one prompt for N questions. Uses per-question evidence sections when available for accuracy."""
    n = len(questions)

    if per_question_evidence and len(per_question_evidence) == n:
        q_blocks = []
        for i, q in enumerate(questions):
            ev_text = _format_evidence(per_question_evidence[i], limit=6)
            label_line = ""
            if classification_labels and i < len(classification_labels) and classification_labels[i]:
                labels = classification_labels[i]
                parts = []
                fw = labels.get("frameworks", [])
                sb = labels.get("subjects", [])
                if fw:
                    parts.append(f"Frameworks: {', '.join(fw)}")
                if sb:
                    parts.append(f"Subjects: {', '.join(sb)}")
                if parts:
                    label_line = f"\n  Context: {'; '.join(parts)}"
                style_hints = []
                for fw_label in fw:
                    hint = _FRAMEWORK_STYLE_HINTS.get(fw_label)
                    if hint:
                        style_hints.append(hint)
                if style_hints:
                    label_line += f"\n  Style: {' '.join(style_hints)}"
            q_blocks.append(f"Question {i+1}: {q}{label_line}\n  Evidence for Question {i+1}:\n  {ev_text}")
        questions_section = "\n\n".join(q_blocks)
    else:
        evidence_text = _format_evidence(evidence)
        questions_section = f"Shared Evidence:\n{evidence_text}\n\n"
        questions_section += "\n\n".join(f"Question {i+1}: {q}" for i, q in enumerate(questions))

    num_list = " ".join(f"Answer {i+1}:" for i in range(n))
    return f"""{questions_section}

Instructions: For each question, write exactly one concise answer grounded ONLY in the evidence provided for that question. Use professional first person plural ("we"). Say "Insufficient evidence." only when the evidence truly has no relevant information. Cite specific details from evidence (e.g., policy names, standards, timeframes) when available.

Format: Label each answer with its number using this exact format:
{num_list}

Example: "Answer 1: We enforce MFA for all administrative access via Okta." Then "Answer 2: ..." for all {n} questions."""
