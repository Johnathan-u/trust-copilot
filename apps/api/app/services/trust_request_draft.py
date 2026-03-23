"""TC-R-B4: Generate a suggested reply draft for a trust request using OpenAI."""

import logging

from app.core.config import get_settings
from app.services.answer_generation import DEFAULT_MODEL, resolve_model

logger = logging.getLogger(__name__)


def suggest_reply_draft(
    requester_email: str,
    subject: str | None,
    message: str,
    model_override: str | None = None,
) -> str:
    """Generate a short, professional draft reply to a trust request. Returns empty string if no API key or on error."""
    settings = get_settings()
    if not settings.openai_api_key:
        return ""
    message = (message or "").strip()
    if not message:
        return ""
    model = resolve_model(model_override or getattr(settings, "completion_model", None))
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        user_content = f"A prospect or customer sent this trust information request:\n\nFrom: {requester_email}\n"
        if subject:
            user_content += f"Subject: {subject}\n"
        user_content += f"\nMessage:\n{message}\n\nDraft a brief, professional reply (2–4 short paragraphs) that acknowledges the request and offers to provide the requested information. Do not invent specific compliance details; keep it general and helpful. Sign off as the trust or security team."
        r = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a trust or security team member drafting a reply to a customer trust request. Be professional, concise, and welcoming. Do not make up specific certifications or dates.",
                },
                {"role": "user", "content": user_content},
            ],
            max_tokens=400,
            temperature=0.35,
        )
        raw = (r.choices[0].message.content or "").strip()
        return raw
    except Exception as e:
        logger.warning("trust_request_draft: %s", e)
        return ""
