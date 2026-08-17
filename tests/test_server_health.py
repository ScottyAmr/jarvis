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


@pytest.mark.asyncio
async def test_settings_status_uses_quick_access_probes(monkeypatch):
    async def fake_calendar_access():
        return True

    async def fake_mail_access():
        return True

    async def fake_notes_access():
        return True

    async def fail_if_calendar_events_loaded():
        raise AssertionError("settings status should not refresh calendar events")

    async def fail_if_unread_counted():
        raise AssertionError("settings status should not count unread mail")

    async def fail_if_recent_notes_loaded(count=1):
        raise AssertionError("settings status should not scan recent notes")

    monkeypatch.setattr(server, "check_calendar_access", fake_calendar_access)
    monkeypatch.setattr(server, "check_mail_access", fake_mail_access)
    monkeypatch.setattr(server, "check_notes_access", fake_notes_access)
    monkeypatch.setattr(server, "get_todays_events", fail_if_calendar_events_loaded)
    monkeypatch.setattr(server, "get_unread_count", fail_if_unread_counted)
    monkeypatch.setattr(server, "get_recent_notes", fail_if_recent_notes_loaded)
    monkeypatch.setattr(server, "get_important_memories", lambda limit=9999: [])
    monkeypatch.setattr(server, "get_open_tasks", lambda: [])

    response = await server.api_settings_status()

    assert response["calendar_accessible"] is True
    assert response["mail_accessible"] is True
    assert response["notes_accessible"] is True
    assert response["memory_count"] == 0
    assert response["task_count"] == 0
