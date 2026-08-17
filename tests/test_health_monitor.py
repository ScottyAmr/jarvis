import builtins
import logging
import time

import pytest

from health_monitor import HealthMonitor, _WARNING_COOLDOWN


def test_report_prunes_old_errors_and_calculates_latency():
    monitor = HealthMonitor()
    now = time.monotonic()
    monitor._errors.append(now - 120)
    monitor.record_error()
    monitor.record_latency(100)
    monitor.record_latency(200)
    monitor.record_latency(300)

    report = monitor.report()

    assert report["errors_last_minute"] == 1
    assert report["avg_latency_ms"] == 200
    assert report["p95_latency_ms"] == 290


def test_status_flags_error_rate_warning():
    monitor = HealthMonitor()
    for _ in range(5):
        monitor.record_error()

    status = monitor.status()

    assert status["ok"] is False
    assert "error_rate" in status["warnings"]


def test_memory_reporting_falls_back_when_psutil_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("psutil missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert HealthMonitor().report()["memory_rss_mb"] == -1.0


@pytest.mark.asyncio
async def test_start_is_idempotent():
    monitor = HealthMonitor()
    monitor.start()
    first_task = monitor._task

    monitor.start()

    assert monitor._task is first_task
    monitor.stop()


def test_warning_cooldown_prevents_log_spam(caplog):
    monitor = HealthMonitor()
    for _ in range(5):
        monitor.record_error()

    now = 100.0
    with caplog.at_level(logging.WARNING, logger="jarvis.health"):
        monitor._check_thresholds(now)
        monitor._check_thresholds(now + 1)
        monitor._check_thresholds(now + _WARNING_COOLDOWN + 1)

    warnings = [r for r in caplog.records if "errors in the last minute" in r.message]
    assert len(warnings) == 2


def test_first_warning_is_not_suppressed_during_first_cooldown_window(caplog):
    monitor = HealthMonitor()

    with caplog.at_level(logging.WARNING, logger="jarvis.health"):
        monitor._warn("startup", "startup warning", now=1.0)

    warnings = [r for r in caplog.records if "startup warning" in r.message]
    assert len(warnings) == 1
