"""
JARVIS n8n Client — authenticated bridge to a self-hosted n8n instance.

Jarvis's model router (llm_provider.py) never imports this module and this
module never imports it back — n8n is reached only through the generic
[ACTION:N8N] tag in server.py, so it works identically no matter which LLM
provider is active.

Every public call returns a structured dict and NEVER raises — a down or
misconfigured n8n instance must not crash Jarvis. Configuration comes from
the environment (N8N_BASE_URL, N8N_API_KEY); if unset, the client reports
itself unconfigured rather than erroring, so Jarvis runs fully normally with
no n8n set up at all.
"""

import asyncio
import logging
import os
import time
from typing import Optional

import httpx

log = logging.getLogger("jarvis.n8n")

DEFAULT_TIMEOUT = float(os.getenv("N8N_TIMEOUT_SECONDS", "20"))
MAX_RETRIES = 1  # transient failures only — one retry, capped wait, never hang a voice reply
MAX_RETRY_WAIT = 5.0


def _classify(exc: Optional[Exception], status: Optional[int]) -> str:
    """Map a request outcome to one of the error kinds Jarvis needs to speak
    differently about: auth | rate_limit | workflow_failure | timeout |
    network | invalid_payload | unavailable | unknown."""
    if exc is not None:
        if isinstance(exc, httpx.TimeoutException):
            return "timeout"
        if isinstance(exc, httpx.ConnectError):
            return "unavailable"
        if isinstance(exc, httpx.RequestError):
            return "network"
        return "unknown"
    if status is None:
        return "unknown"
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "unavailable"  # webhook not found / workflow not activated
    if status == 429:
        return "rate_limit"
    if status == 400:
        return "invalid_payload"
    if 500 <= status < 600:
        return "workflow_failure"
    return "unknown"


def _human_message(kind: str, workflow: str) -> str:
    return {
        "auth": "n8n rejected the request — check N8N_API_KEY",
        "rate_limit": "n8n is rate-limiting requests right now",
        "workflow_failure": f"the '{workflow}' workflow failed on n8n's side",
        "timeout": f"the '{workflow}' workflow took too long to respond",
        "network": "couldn't reach n8n over the network",
        "invalid_payload": f"n8n rejected the payload for '{workflow}'",
        "unavailable": f"n8n (or the '{workflow}' workflow) isn't available — is it running and activated?",
    }.get(kind, f"the '{workflow}' workflow failed for an unknown reason")


class N8nClient:
    def __init__(self, base_url: str = "", api_key: str = "", timeout: float = DEFAULT_TIMEOUT):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def trigger_workflow(self, webhook_path: str, payload: dict, timeout: Optional[float] = None) -> dict:
        """POST payload to an n8n webhook and return a structured result.
        Never raises — every failure path is returned, not thrown."""
        if not self.configured:
            return {"ok": False, "kind": "unavailable", "data": None,
                     "message": "n8n isn't configured (set N8N_BASE_URL in .env)"}

        url = f"{self.base_url}/webhook/{webhook_path.lstrip('/')}"
        req_timeout = timeout or self.timeout
        start = time.monotonic()
        attempt = 0
        kind = "unknown"
        last_exc: Optional[Exception] = None
        last_status: Optional[int] = None
        last_body = ""

        while True:
            try:
                async with httpx.AsyncClient(timeout=req_timeout) as http:
                    resp = await http.post(url, json=payload, headers=self._headers())
                last_status = resp.status_code
                last_body = resp.text
                if 200 <= resp.status_code < 300:
                    duration = time.monotonic() - start
                    log.info(f"n8n workflow '{webhook_path}' completed in {duration:.2f}s")
                    try:
                        data = resp.json()
                    except Exception:
                        data = resp.text
                    return {"ok": True, "kind": None, "data": data, "message": "done"}
                kind = _classify(None, resp.status_code)
            except Exception as e:
                last_exc = e
                kind = _classify(e, None)

            transient = kind in ("timeout", "network", "rate_limit")
            if not transient or attempt >= MAX_RETRIES:
                break
            attempt += 1
            wait = min(1.5 * attempt, MAX_RETRY_WAIT)
            log.warning(f"n8n workflow '{webhook_path}' {kind}; retry {attempt}/{MAX_RETRIES} in {wait:.1f}s")
            await asyncio.sleep(wait)

        duration = time.monotonic() - start
        detail = (
            f"HTTP {last_status}: {last_body[:200]}" if last_status is not None
            else f"{type(last_exc).__name__}: {last_exc}" if last_exc is not None
            else "unknown error"
        )
        log.error(f"n8n workflow '{webhook_path}' failed ({kind}) after {duration:.2f}s — {detail}")
        return {"ok": False, "kind": kind, "data": None, "message": _human_message(kind, webhook_path)}

    async def health_check(self) -> dict:
        if not self.configured:
            return {"ok": False, "message": "n8n isn't configured"}
        url = f"{self.base_url}/healthz"
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.get(url)
            if resp.status_code == 200:
                return {"ok": True, "message": "n8n is reachable"}
            return {"ok": False, "message": f"n8n returned HTTP {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "message": f"n8n unreachable: {e}"}


_client: Optional[N8nClient] = None


def get_client() -> N8nClient:
    """Singleton client built from environment config."""
    global _client
    if _client is None:
        _client = N8nClient(
            base_url=os.getenv("N8N_BASE_URL", ""),
            api_key=os.getenv("N8N_API_KEY", ""),
        )
    return _client


def reset_client():
    """Test-only: drop the cached singleton so a new one picks up fresh env/config."""
    global _client
    _client = None
