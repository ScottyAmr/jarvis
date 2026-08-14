"""Pluggable LLM backend for JARVIS.

JARVIS calls its language model through the Anthropic SDK shape:

    response = await client.messages.create(
        model=..., max_tokens=..., system=..., messages=[...]
    )
    text = response.content[0].text

There are 14 such call sites across server.py, planner.py, memory.py and
screen.py, all using that exact shape. Rather than rewrite each one, this
module provides adapters that *impersonate* the Anthropic client, so a
different provider can be dropped in at a single construction point.

Currently implemented: Google Gemini (has a free tier).

Anything the adapter must reproduce:
  * `system` may be a plain string OR a list of content blocks
    (JARVIS marks its static prompt with cache_control for prompt caching).
  * message `content` may be a string OR a list of blocks, including
    base64 images — screen.py sends screenshots for vision.
  * the response object needs `.content[0].text`, and ideally
    `.usage.input_tokens` / `.usage.output_tokens` for usage logging.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

import httpx

log = logging.getLogger("jarvis")

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"


# --------------------------------------------------------------------------
# Anthropic-shaped response objects
# --------------------------------------------------------------------------

class _TextBlock:
    __slots__ = ("type", "text")

    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _Usage:
    __slots__ = ("input_tokens", "output_tokens")

    def __init__(self, input_tokens: int = 0, output_tokens: int = 0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Response:
    """Mimics anthropic.types.Message closely enough for JARVIS."""

    __slots__ = ("content", "usage", "stop_reason")

    def __init__(self, text: str, usage: _Usage, stop_reason: str = "end_turn"):
        self.content = [_TextBlock(text)]
        self.usage = usage
        self.stop_reason = stop_reason


class LLMError(Exception):
    """Classified LLM failure. `.kind` is one of:
    auth | rate_limit_daily | rate_limit_minute | server | timeout | network | unknown
    """

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def classify_http_status(status: int, body: str) -> str:
    """Map an HTTP failure to an LLMError kind."""
    b = (body or "").lower()
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit_daily" if ("per day" in b or "tpd" in b) else "rate_limit_minute"
    if 500 <= status < 600:
        return "server"
    return "unknown"


def classify_exception(exc: Exception) -> str:
    """Map a transport exception to an LLMError kind."""
    if isinstance(exc, (httpx.TimeoutException,)):
        return "timeout"
    if isinstance(exc, (httpx.TransportError, httpx.ConnectError, httpx.NetworkError)):
        return "network"
    return "unknown"


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------

def _system_to_text(system: Any) -> str:
    """Flatten Anthropic's `system` into plain text.

    Accepts a string, or a list of content blocks. cache_control markers are
    dropped — Gemini manages its own context caching separately.
    """
    if not system:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts = []
        for block in system:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n\n".join(p for p in parts if p)
    return str(system)


def _content_to_parts(content: Any) -> list[dict]:
    """Convert Anthropic message content into Gemini `parts`."""
    if isinstance(content, str):
        return [{"text": content}]

    parts: list[dict] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append({"text": block})
                continue
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append({"text": block.get("text", "")})
            elif btype == "image":
                src = block.get("source") or {}
                if src.get("type") == "base64":
                    parts.append({
                        "inline_data": {
                            "mime_type": src.get("media_type", "image/png"),
                            "data": src.get("data", ""),
                        }
                    })
    return parts or [{"text": ""}]


class _GeminiMessages:
    def __init__(self, client: "AsyncGemini"):
        self._client = client

    async def create(
        self,
        model: str = "",
        max_tokens: int = 1024,
        system: Any = None,
        messages: Optional[list] = None,
        temperature: Optional[float] = None,
        **_ignored: Any,
    ) -> _Response:
        c = self._client
        target = c.resolve_model(model)

        contents = []
        for m in (messages or []):
            role = m.get("role", "user")
            contents.append({
                # Anthropic says "assistant"; Gemini says "model"
                "role": "model" if role == "assistant" else "user",
                "parts": _content_to_parts(m.get("content", "")),
            })

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if temperature is not None:
            payload["generationConfig"]["temperature"] = temperature

        sys_text = _system_to_text(system)
        if sys_text:
            payload["systemInstruction"] = {"parts": [{"text": sys_text}]}

        url = f"{GEMINI_ENDPOINT}/models/{target}:generateContent"
        async with httpx.AsyncClient(timeout=c.timeout) as http:
            resp = await http.post(
                url,
                params={"key": c.api_key},
                json=payload,
                headers={"Content-Type": "application/json"},
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"Gemini API error {resp.status_code} on model '{target}': {resp.text[:300]}"
            )

        data = resp.json()

        # Safety filters / empty candidates come back without content.
        text = ""
        candidates = data.get("candidates") or []
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts)
            if not text:
                reason = candidates[0].get("finishReason", "")
                if reason and reason != "STOP":
                    log.warning(f"Gemini returned no text (finishReason={reason})")
        else:
            fb = data.get("promptFeedback") or {}
            if fb.get("blockReason"):
                log.warning(f"Gemini blocked the prompt: {fb.get('blockReason')}")

        meta = data.get("usageMetadata") or {}
        usage = _Usage(
            input_tokens=int(meta.get("promptTokenCount", 0) or 0),
            output_tokens=int(meta.get("candidatesTokenCount", 0) or 0),
        )
        return _Response(text, usage)


class AsyncGemini:
    """Drop-in stand-in for anthropic.AsyncAnthropic, backed by Gemini.

    JARVIS passes Claude model IDs at every call site. Rather than edit them
    all, those IDs are mapped onto a fast model (voice turns) and a deep model
    (research), configurable via env.
    """

    def __init__(
        self,
        api_key: str,
        fast_model: str = "gemini-2.0-flash",
        deep_model: str = "gemini-2.0-flash",
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.fast_model = fast_model
        self.deep_model = deep_model
        self.timeout = timeout
        self.messages = _GeminiMessages(self)

    def resolve_model(self, requested: str) -> str:
        """Map a Claude model ID onto the configured Gemini model."""
        r = (requested or "").lower()
        if "opus" in r or "sonnet" in r:
            return self.deep_model
        if r.startswith("gemini") or r.startswith("models/"):
            return r.replace("models/", "", 1)
        return self.fast_model

    async def list_models(self) -> list[str]:
        """Model IDs available to this key — used to verify configuration."""
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.get(f"{GEMINI_ENDPOINT}/models", params={"key": self.api_key})
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini list-models failed {resp.status_code}: {resp.text[:200]}")
        out = []
        for m in resp.json().get("models", []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []):
                out.append(m.get("name", "").replace("models/", "", 1))
        return out


# --------------------------------------------------------------------------
# OpenAI-compatible providers (Groq, OpenRouter, Ollama, LM Studio, Together…)
# --------------------------------------------------------------------------

# Preset base URLs so LLM_PROVIDER=groq "just works" without hunting for a URL.
OPENAI_COMPAT_BASES = {
    "groq":       "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together":   "https://api.together.xyz/v1",
    "openai":     "https://api.openai.com/v1",
    "ollama":     "http://localhost:11434/v1",
    "lmstudio":   "http://localhost:1234/v1",
}
# Providers that run on your own machine and need no API key.
LOCAL_PROVIDERS = {"ollama", "lmstudio"}

# Free tiers rate-limit aggressively (429). Rather than fail the whole turn, wait
# the server-suggested time and retry — but cap the wait so a voice reply never
# hangs too long, and only retry a couple of times.
RATE_LIMIT_MAX_RETRIES = 2
RATE_LIMIT_MAX_WAIT = 6.0  # seconds — never make the user wait longer than this


def _retry_after_seconds(resp: httpx.Response) -> float:
    """Best-effort parse of how long to wait before retrying a 429."""
    hdr = resp.headers.get("retry-after")
    if hdr:
        try:
            return float(hdr)
        except ValueError:
            pass
    # Groq embeds it in the body: "Please try again in 7.875s"
    m = re.search(r"try again in ([\d.]+)\s*s", resp.text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return 2.0


# Reasoning models emit hidden thinking tokens that count against max_tokens.
# JARVIS asks for as few as 80 tokens on some calls, which reasoning would eat
# entirely — returning empty content and leaving JARVIS mute. For these models
# we request minimal reasoning effort and add headroom on top of the caller's
# budget, so the visible answer still fits.
REASONING_HINTS = ("gpt-oss", "deepseek-r1", "qwen3", "-o1", "-o3", "reasoner", "thinking")
REASONING_HEADROOM = 700


def _is_reasoning_model(model: str) -> bool:
    m = (model or "").lower()
    return any(h in m for h in REASONING_HINTS)


def _content_to_openai(content: Any) -> Any:
    """Convert Anthropic message content into OpenAI chat format.

    Plain strings pass through unchanged; block lists become the multimodal
    array form, with base64 images rewritten as data: URLs.
    """
    if isinstance(content, str):
        return content

    out: list[dict] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                out.append({"type": "text", "text": block})
                continue
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                out.append({"type": "text", "text": block.get("text", "")})
            elif btype == "image":
                src = block.get("source") or {}
                if src.get("type") == "base64":
                    mime = src.get("media_type", "image/png")
                    out.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{src.get('data','')}"},
                    })
    if not out:
        return ""
    # Collapse a lone text block back to a plain string — maximum compatibility,
    # since some servers reject the array form for text-only messages.
    if len(out) == 1 and out[0].get("type") == "text":
        return out[0]["text"]
    return out


class _CompatMessages:
    def __init__(self, client: "AsyncOpenAICompat"):
        self._client = client

    async def create(
        self,
        model: str = "",
        max_tokens: int = 1024,
        system: Any = None,
        messages: Optional[list] = None,
        temperature: Optional[float] = None,
        **_ignored: Any,
    ) -> _Response:
        c = self._client
        target = c.resolve_model(model)

        chat: list[dict] = []
        sys_text = _system_to_text(system)
        if sys_text:
            chat.append({"role": "system", "content": sys_text})

        has_image = False
        for m in (messages or []):
            converted = _content_to_openai(m.get("content", ""))
            if isinstance(converted, list):
                has_image = any(b.get("type") == "image_url" for b in converted)
            chat.append({
                "role": "assistant" if m.get("role") == "assistant" else "user",
                "content": converted,
            })

        if has_image and not c.supports_vision:
            # Fail fast so screen.py falls back to its window-list summary
            # instead of burning a round trip on a model that can't see.
            raise RuntimeError(
                f"Vision requested but provider '{c.provider}' is configured "
                "without vision support (set LLM_VISION=true to allow)"
            )

        headers = {"Content-Type": "application/json"}
        if c.api_key:
            headers["Authorization"] = f"Bearer {c.api_key}"
        if c.provider == "openrouter":
            headers["HTTP-Referer"] = "http://localhost:5173"
            headers["X-Title"] = "JARVIS"

        # Build the model order: the session's active model first (sticky —
        # a fallback that already worked stays selected), then primary, then
        # the remaining fallbacks. Each model has its own daily/minute quota.
        ordered = [c.active_model or target, target] + list(c.fallback_models)
        models_to_try: list[str] = []
        for m in ordered:
            if m and m not in models_to_try:
                models_to_try.append(m)

        resp = None
        last_kind = "unknown"
        last_detail = "no response"
        async with httpx.AsyncClient(timeout=c.timeout) as http:
            for mi, mdl in enumerate(models_to_try):
                payload: dict[str, Any] = {"model": mdl, "messages": chat, "max_tokens": max_tokens}
                if _is_reasoning_model(mdl):
                    payload["max_tokens"] = max_tokens + REASONING_HEADROOM
                    payload["reasoning_effort"] = "low"
                if temperature is not None:
                    payload["temperature"] = temperature

                # One model: transient failures (minute-429, 5xx, timeout,
                # network) get a couple of short retries; hard failures
                # (auth, daily-429) fall through immediately.
                attempt = 0
                kind = "unknown"
                resp = None
                while True:
                    try:
                        resp = await http.post(
                            f"{c.base_url}/chat/completions", json=payload, headers=headers
                        )
                    except Exception as e:  # timeout / network
                        kind = classify_exception(e)
                        last_kind, last_detail = kind, f"{type(e).__name__}: {e}"
                        resp = None
                    else:
                        if resp.status_code == 200:
                            break
                        kind = classify_http_status(resp.status_code, resp.text)
                        last_kind = kind
                        last_detail = f"HTTP {resp.status_code} on '{mdl}': {resp.text[:160]}"

                    transient = kind in ("rate_limit_minute", "server", "timeout", "network")
                    if not transient or attempt >= RATE_LIMIT_MAX_RETRIES:
                        break
                    wait = min(_retry_after_seconds(resp) + 0.25, RATE_LIMIT_MAX_WAIT) if resp is not None else 1.0
                    attempt += 1
                    log.warning(f"{c.provider}/{mdl} {kind}; retry {attempt}/{RATE_LIMIT_MAX_RETRIES} in {wait:.1f}s")
                    await asyncio.sleep(wait)

                if resp is not None and resp.status_code == 200:
                    if c.active_model != mdl:
                        log.info(f"{c.provider}: model now '{mdl}'"
                                 + (f" (fell back from '{models_to_try[0]}' — {last_kind})" if mi > 0 else ""))
                        c.active_model = mdl  # sticky for the rest of the session
                    break

                # this model failed — auth won't be fixed by another model
                if kind == "auth":
                    raise LLMError("auth", f"{c.provider} authentication failed: {last_detail}")
                if mi < len(models_to_try) - 1:
                    log.warning(f"{c.provider}: '{mdl}' failed ({kind}) — falling back to '{models_to_try[mi + 1]}'")
                    continue

        if resp is None or resp.status_code != 200:
            raise LLMError(last_kind, f"{c.provider}: all models failed ({', '.join(models_to_try)}). {last_detail}")

        target = c.active_model or target  # for the empty-content diagnostics below
        data = resp.json()
        choices = data.get("choices") or []
        text = ""
        if choices:
            msg = choices[0].get("message") or {}
            text = msg.get("content") or ""
            if isinstance(text, list):  # a few servers return block lists
                text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
            if not text.strip():
                finish = choices[0].get("finish_reason", "")
                if msg.get("reasoning"):
                    log.warning(
                        f"{c.provider}/{target} returned only reasoning and no answer "
                        f"(finish_reason={finish}) — raise max_tokens or use a "
                        "non-reasoning model for this call"
                    )
                else:
                    log.warning(
                        f"{c.provider}/{target} returned empty content "
                        f"(finish_reason={finish})"
                    )

        usage_raw = data.get("usage") or {}
        usage = _Usage(
            input_tokens=int(usage_raw.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage_raw.get("completion_tokens", 0) or 0),
        )
        return _Response(text, usage)


class AsyncOpenAICompat:
    """Anthropic-shaped client backed by any OpenAI-compatible endpoint."""

    def __init__(
        self,
        provider: str,
        api_key: str = "",
        base_url: str = "",
        fast_model: str = "",
        deep_model: str = "",
        supports_vision: bool = True,
        fallback_models: Optional[list] = None,
        timeout: float = 120.0,
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = (base_url or OPENAI_COMPAT_BASES.get(provider, "")).rstrip("/")
        self.fast_model = fast_model
        self.deep_model = deep_model or fast_model
        self.supports_vision = supports_vision
        self.fallback_models = fallback_models or []
        self.active_model: Optional[str] = None  # sticky: last model that worked
        self.timeout = timeout
        self.messages = _CompatMessages(self)
        if not self.base_url:
            raise ValueError(
                f"No base URL for provider '{provider}' — set LLM_BASE_URL"
            )

    def resolve_model(self, requested: str) -> str:
        """Map Claude model IDs onto the configured fast/deep models."""
        r = (requested or "").lower()
        if "opus" in r or "sonnet" in r:
            return self.deep_model
        if r.startswith("claude") or not r:
            return self.fast_model
        return requested  # already a native model ID

    async def list_models(self) -> list[str]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.get(f"{self.base_url}/models", headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"list-models failed {resp.status_code}: {resp.text[:200]}")
        return [m.get("id", "") for m in resp.json().get("data", [])]


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def build_client(provider: str, *, anthropic_key: str = "", gemini_key: str = "",
                 gemini_fast: str = "gemini-2.0-flash",
                 gemini_deep: str = "gemini-2.0-flash",
                 llm_key: str = "", base_url: str = "",
                 fast_model: str = "", deep_model: str = "",
                 supports_vision: bool = True, fallback_models: Optional[list] = None):
    """Return an Anthropic-shaped client for the configured provider.

    Supported: "anthropic", "gemini", and any OpenAI-compatible endpoint
    ("groq", "openrouter", "together", "openai", "ollama", "lmstudio", or
    "custom" with an explicit base_url).

    Returns None when required configuration is missing, matching how server.py
    already treats a missing client (LLM features simply disabled).
    """
    provider = (provider or "anthropic").lower()

    if provider == "gemini":
        if not gemini_key or gemini_key.startswith("your-"):
            log.warning("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set — LLM features disabled")
            return None
        log.info(f"LLM provider: Gemini (fast={gemini_fast}, deep={gemini_deep})")
        return AsyncGemini(gemini_key, fast_model=gemini_fast, deep_model=gemini_deep)

    if provider in OPENAI_COMPAT_BASES or provider == "custom":
        is_local = provider in LOCAL_PROVIDERS
        if not is_local and (not llm_key or llm_key.startswith("your-")):
            log.warning(f"LLM_PROVIDER={provider} but LLM_API_KEY is not set — LLM features disabled")
            return None
        if not fast_model:
            log.warning(f"LLM_PROVIDER={provider} but LLM_FAST_MODEL is not set — LLM features disabled")
            return None
        try:
            client = AsyncOpenAICompat(
                provider, api_key=llm_key, base_url=base_url,
                fast_model=fast_model, deep_model=deep_model,
                supports_vision=supports_vision, fallback_models=fallback_models,
            )
        except ValueError as e:
            log.warning(f"LLM provider misconfigured: {e}")
            return None
        log.info(
            f"LLM provider: {provider} @ {client.base_url} "
            f"(fast={client.fast_model}, deep={client.deep_model}, "
            f"fallbacks={client.fallback_models or 'none'}, vision={supports_vision})"
        )
        return client

    import anthropic  # imported lazily so other providers need not configure it
    if not anthropic_key or anthropic_key.startswith("your-"):
        log.warning("ANTHROPIC_API_KEY not set — LLM features disabled")
        return None
    log.info("LLM provider: Anthropic")
    return anthropic.AsyncAnthropic(api_key=anthropic_key)
