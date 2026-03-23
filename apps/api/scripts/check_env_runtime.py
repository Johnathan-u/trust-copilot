"""
Runtime environment check for OpenAI and mapping rerank settings.

Run inside API container:
  docker compose exec api python -m scripts.check_env_runtime

Does not print secret values — only presence and optional length.
"""
from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from dotenv import load_dotenv

load_dotenv(API_ROOT / ".env")

from app.core.config import get_settings

get_settings.cache_clear()


def main() -> None:
    s = get_settings()
    key = s.openai_api_key or ""
    present = bool(key.strip())

    print("OPENAI_API_KEY present:", present)
    if present:
        print("OPENAI_API_KEY length:", len(key))
    else:
        print("OPENAI_API_KEY length: (n/a)")

    mllm = "1" if s.mapping_llm_rerank_enabled else "0"
    print("MAPPING_LLM_RERANK:", mllm)
    print("MAPPING_RERANK_MODEL:", s.mapping_rerank_model)

    env = s.app_env
    if env in ("development", "dev"):
        env_label = "dev"
    elif env in ("test", "testing"):
        env_label = "test"
    else:
        env_label = env
    print("APP_ENV:", env_label)


if __name__ == "__main__":
    main()
