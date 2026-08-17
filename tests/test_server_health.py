import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


def test_fast_health_command_bypasses_llm():
    assert server.detect_action_fast("health check") == {"action": "check_health"}
    assert server.detect_action_fast("system status") == {"action": "check_health"}


def test_extract_action_accepts_health_tag():
    clean, action = server.extract_action("Running diagnostics, sir. [ACTION:HEALTH]")

    assert clean == "Running diagnostics, sir."
    assert action == {"action": "health", "target": ""}


@pytest.mark.asyncio
async def test_api_health_includes_monitor_snapshot(monkeypatch):
    def fake_status():
        return {
            "ok": True,
            "warnings": [],
            "uptime_hours": 1.2,
            "active_sessions": 0,
            "errors_last_minute": 0,
            "avg_latency_ms": 42,
            "p95_latency_ms": 84,
            "idle_seconds": 1,
            "memory_rss_mb": 123.4,
        }

    monkeypatch.setattr(server.health_monitor, "status", fake_status)

    response = await server.health()

    assert response["status"] == "online"
    assert response["health"]["avg_latency_ms"] == 42
    assert response["health"]["ok"] is True
