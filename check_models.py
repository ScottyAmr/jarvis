#!/usr/bin/env python3
"""List the models your configured LLM provider actually offers.

Model IDs change over time, so rather than guessing, ask the provider:

    ./.venv/bin/python check_models.py

Reads .env the same way server.py does, then queries the provider named by
LLM_PROVIDER. Copy a suitable ID into LLM_FAST_MODEL (and LLM_DEEP_MODEL).
"""

import asyncio
import os
import sys
from pathlib import Path

# Load .env exactly as server.py does
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from llm_provider import (  # noqa: E402
    AsyncGemini, AsyncOpenAICompat, OPENAI_COMPAT_BASES, LOCAL_PROVIDERS,
)

PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()


async def main() -> int:
    if PROVIDER == "gemini":
        key = os.getenv("GEMINI_API_KEY", "")
        if not key or key.startswith("your-"):
            print("GEMINI_API_KEY is not set in .env")
            return 1
        client = AsyncGemini(key)

    elif PROVIDER in OPENAI_COMPAT_BASES or PROVIDER == "custom":
        key = os.getenv("LLM_API_KEY", "")
        if PROVIDER not in LOCAL_PROVIDERS and (not key or key.startswith("your-")):
            print(f"LLM_API_KEY is not set in .env (needed for {PROVIDER})")
            return 1
        client = AsyncOpenAICompat(
            PROVIDER, api_key=key, base_url=os.getenv("LLM_BASE_URL", ""),
            fast_model="placeholder",
        )

    else:
        print(f"Nothing to list for LLM_PROVIDER={PROVIDER!r}.")
        print("Set it to gemini, groq, openrouter, together, openai, ollama or lmstudio.")
        return 1

    print(f"Provider: {PROVIDER}")
    try:
        models = await client.list_models()
    except Exception as e:
        print(f"\nCould not list models: {e}")
        if PROVIDER in LOCAL_PROVIDERS:
            print("Is the local server running?  (e.g. `ollama serve`)")
        return 1

    if not models:
        print("No models returned — the key may lack permissions.")
        return 1

    print(f"{len(models)} model(s) available:\n")
    for m in sorted(models):
        print(f"  {m}")
    print("\nCopy one into LLM_FAST_MODEL in .env (a small/fast model suits the "
          "voice loop; a larger one suits LLM_DEEP_MODEL for research).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
