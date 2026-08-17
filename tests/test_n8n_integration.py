"""
Tests for the n8n workflow-automation bridge (integrations/n8n/) and its
wiring into server.py's action dispatch. All httpx calls are mocked — none
of these tests need a real n8n instance.
"""

import hmac
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.n8n.client import N8nClient
from integrations.n8n.registry import WORKFLOWS, get_workflow, describe_workflows_for_prompt


def _mock_http_client(response=None, raise_exc=None):
    """Build a MagicMock standing in for `httpx.AsyncClient()` used as an
    `async with` context manager, whose .post()/.get() either returns
    `response` or raises `raise_exc`."""
    inner = AsyncMock()
    if raise_exc is not None:
        inner.post.side_effect = raise_exc
        inner.get.side_effect = raise_exc
    else:
        inner.post.return_value = response
        inner.get.return_value = response
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=inner)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _resp(status_code, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.text = text or json.dumps(json_body or {})
    r.json = MagicMock(return_value=json_body if json_body is not None else {})
    return r


# ── N8nClient ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_workflow_success():
    client = N8nClient(base_url="http://localhost:5678", api_key="secret")
    with patch("integrations.n8n.client.httpx.AsyncClient",
               return_value=_mock_http_client(_resp(200, {"ok": True, "received": {"a": "b"}}))):
        result = await client.trigger_workflow("jarvis-ping-test", {"a": "b"})
    assert result["ok"] is True
    assert result["kind"] is None
    assert result["data"]["ok"] is True


@pytest.mark.asyncio
async def test_trigger_workflow_auth_failure():
    client = N8nClient(base_url="http://localhost:5678", api_key="wrong")
    with patch("integrations.n8n.client.httpx.AsyncClient",
               return_value=_mock_http_client(_resp(401, text="unauthorized"))):
        result = await client.trigger_workflow("jarvis-ping-test", {})
    assert result["ok"] is False
    assert result["kind"] == "auth"


@pytest.mark.asyncio
async def test_trigger_workflow_timeout_no_raise():
    import httpx
    client = N8nClient(base_url="http://localhost:5678")
    with patch("integrations.n8n.client.httpx.AsyncClient",
               return_value=_mock_http_client(raise_exc=httpx.TimeoutException("timed out"))):
        with patch("integrations.n8n.client.asyncio.sleep", new=AsyncMock()):
            result = await client.trigger_workflow("jarvis-ping-test", {})
    assert result["ok"] is False
    assert result["kind"] == "timeout"


@pytest.mark.asyncio
async def test_trigger_workflow_unconfigured_client_never_raises():
    client = N8nClient(base_url="")  # no base_url — unconfigured
    result = await client.trigger_workflow("jarvis-ping-test", {"a": "b"})
    assert result["ok"] is False
    assert result["kind"] == "unavailable"


@pytest.mark.asyncio
async def test_health_check_up():
    client = N8nClient(base_url="http://localhost:5678")
    with patch("integrations.n8n.client.httpx.AsyncClient", return_value=_mock_http_client(_resp(200))):
        result = await client.health_check()
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_health_check_down():
    import httpx
    client = N8nClient(base_url="http://localhost:5678")
    with patch("integrations.n8n.client.httpx.AsyncClient",
               return_value=_mock_http_client(raise_exc=httpx.ConnectError("refused"))):
        result = await client.health_check()
    assert result["ok"] is False


@pytest.mark.asyncio
async def test_health_check_unconfigured():
    client = N8nClient(base_url="")
    result = await client.health_check()
    assert result["ok"] is False
    assert "not" in result["message"].lower() or "isn't" in result["message"].lower()


# ── Registry ─────────────────────────────────────────────────────────────

def test_registry_has_ping_test_workflow():
    assert any(w["id"] == "ping_test" for w in WORKFLOWS)


def test_get_workflow_found_and_missing():
    assert get_workflow("ping_test") is not None
    assert get_workflow("does_not_exist") is None


def test_describe_workflows_for_prompt_lists_registered_ids():
    desc = describe_workflows_for_prompt()
    assert "ping_test" in desc
    assert "READ_ONLY" in desc


# ── server.py dispatch glue ─────────────────────────────────────────────

def test_parse_n8n_target_flat_fields():
    from server import _parse_n8n_target
    workflow_id, payload = _parse_n8n_target("ping_test ||| message=hello ||| priority=high")
    assert workflow_id == "ping_test"
    assert payload == {"message": "hello", "priority": "high"}


def test_parse_n8n_target_trailing_narrative_does_not_corrupt_other_fields():
    # Same bug class already hit twice this session (ADD_TASK due_date, MUSIC
    # volume): the LLM occasionally glues trailing narrative onto the LAST
    # field. With flat key=value pairs (not JSON), the garbage just becomes
    # part of that one field's value instead of breaking parsing entirely.
    from server import _parse_n8n_target
    workflow_id, payload = _parse_n8n_target("ping_test ||| message=helloDone, sir.")
    assert workflow_id == "ping_test"
    assert payload["message"] == "helloDone, sir."  # ugly but doesn't crash or misparse workflow_id


def test_parse_n8n_target_no_fields():
    from server import _parse_n8n_target
    workflow_id, payload = _parse_n8n_target("ping_test")
    assert workflow_id == "ping_test"
    assert payload == {}


def test_parse_n8n_target_field_without_equals_is_dropped():
    from server import _parse_n8n_target
    workflow_id, payload = _parse_n8n_target("ping_test ||| garbage-no-equals ||| ok=yes")
    assert payload == {"ok": "yes"}


# ── CONFIRM-tier pending-action resolution ──────────────────────────────

def test_resolve_confirmation_no_pending():
    from server import _resolve_n8n_confirmation
    assert _resolve_n8n_confirmation(None, "yes") == "none"


def test_resolve_confirmation_confirm_phrase():
    from server import _resolve_n8n_confirmation
    pending = {"workflow_id": "x", "payload": {}, "ts": time.time()}
    assert _resolve_n8n_confirmation(pending, "yes go ahead") == "confirm"


def test_resolve_confirmation_decline_phrase():
    from server import _resolve_n8n_confirmation
    pending = {"workflow_id": "x", "payload": {}, "ts": time.time()}
    assert _resolve_n8n_confirmation(pending, "no, cancel that") == "decline"


def test_resolve_confirmation_unrelated_utterance():
    from server import _resolve_n8n_confirmation
    pending = {"workflow_id": "x", "payload": {}, "ts": time.time()}
    assert _resolve_n8n_confirmation(pending, "what's the weather") == "none"


def test_resolve_confirmation_expired():
    from server import _resolve_n8n_confirmation, SELF_DISPATCH_TIMEOUT
    pending = {"workflow_id": "x", "payload": {}, "ts": time.time() - SELF_DISPATCH_TIMEOUT - 5}
    assert _resolve_n8n_confirmation(pending, "yes") == "none"


# ── Webhook signature validation ────────────────────────────────────────

@pytest.mark.asyncio
async def test_n8n_webhook_rejects_bad_signature(monkeypatch):
    from server import n8n_webhook
    monkeypatch.setenv("N8N_WEBHOOK_SECRET", "shhh")
    body = json.dumps({"result": "ok"}).encode()
    req = MagicMock()
    req.body = AsyncMock(return_value=body)
    req.headers = {"X-N8N-Signature": "not-the-right-signature"}
    resp = await n8n_webhook(req)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_n8n_webhook_accepts_valid_signature(monkeypatch):
    from server import n8n_webhook
    monkeypatch.setenv("N8N_WEBHOOK_SECRET", "shhh")
    body = json.dumps({"result": "ok"}).encode()
    signature = hmac.new(b"shhh", body, "sha256").hexdigest()
    req = MagicMock()
    req.body = AsyncMock(return_value=body)
    req.headers = {"X-N8N-Signature": signature}
    result = await n8n_webhook(req)
    assert result == {"ok": True}
