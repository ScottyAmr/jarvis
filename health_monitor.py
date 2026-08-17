"""
Background health monitor for JARVIS.

Runs as an asyncio task; tracks response latency, error rates, and memory
usage. Surfaces warnings via the root logger (picked up by the rotating file
handler). No continuous LLM calls — metrics are collected cheaply and an LLM
analysis is only triggered when the user explicitly asks via [ACTION:HEALTH].
"""

import asyncio
import collections
import logging
import os
import time
from typing import Any

log = logging.getLogger("jarvis.health")

# Rolling window for error and latency tracking
_WINDOW = 60  # seconds

# Thresholds
_ERROR_RATE_WARN = 5      # errors per minute
_LATENCY_WARN_MS = 8_000  # ms — warn if p95 exceeds this
_MEMORY_WARN_MB = 500     # RSS warn threshold


class HealthMonitor:
    """Lightweight async health monitor. Call start() once at server startup."""

    def __init__(self) -> None:
        # Timestamped deques for rolling-window calculations
        self._errors: collections.deque[float] = collections.deque()
        self._latencies: collections.deque[tuple[float, float]] = collections.deque()  # (ts, ms)
        self._last_activity: float = time.monotonic()
        self._session_count: int = 0
        self._start_time: float = time.monotonic()
        self._task: asyncio.Task | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="health-monitor")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def record_error(self) -> None:
        self._errors.append(time.monotonic())

    def record_latency(self, ms: float) -> None:
        self._last_activity = time.monotonic()
        self._latencies.append((time.monotonic(), ms))

    def record_activity(self) -> None:
        self._last_activity = time.monotonic()

    def on_session_open(self) -> None:
        self._session_count += 1

    def on_session_close(self) -> None:
        self._session_count = max(0, self._session_count - 1)

    def report(self) -> dict[str, Any]:
        """Return a snapshot dict suitable for voice reporting."""
        now = time.monotonic()
        self._prune(now)

        errors_per_min = len(self._errors)
        latencies = [ms for _, ms in self._latencies]
        p95 = _percentile(latencies, 95) if latencies else 0.0
        avg = sum(latencies) / len(latencies) if latencies else 0.0
        idle_s = now - self._last_activity
        uptime_h = (now - self._start_time) / 3600

        try:
            import psutil
            proc = psutil.Process(os.getpid())
            rss_mb = proc.memory_info().rss / 1_048_576
        except Exception:
            rss_mb = -1.0

        return {
            "uptime_hours": round(uptime_h, 1),
            "active_sessions": self._session_count,
            "errors_last_minute": errors_per_min,
            "avg_latency_ms": round(avg),
            "p95_latency_ms": round(p95),
            "idle_seconds": round(idle_s),
            "memory_rss_mb": round(rss_mb, 1),
        }

    def format_voice_report(self) -> str:
        """One or two sentences suitable for JARVIS to speak aloud."""
        r = self.report()
        parts = []

        if r["errors_last_minute"] >= _ERROR_RATE_WARN:
            parts.append(f"{r['errors_last_minute']} errors in the last minute")
        if r["p95_latency_ms"] >= _LATENCY_WARN_MS:
            parts.append(f"p95 response latency at {r['p95_latency_ms']}ms")
        if r["memory_rss_mb"] >= _MEMORY_WARN_MB:
            parts.append(f"memory at {r['memory_rss_mb']}MB")

        status = "All systems nominal." if not parts else f"Heads up: {'; '.join(parts)}."
        summary = (
            f"Uptime {r['uptime_hours']}h, "
            f"{r['active_sessions']} active session(s), "
            f"average response {r['avg_latency_ms']}ms."
        )
        return f"{status} {summary}"

    # ── Background loop ───────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(30)
                now = time.monotonic()
                self._prune(now)
                self._check_thresholds(now)
            except asyncio.CancelledError:
                return
            except Exception:
                log.exception("health monitor loop error")

    def _prune(self, now: float) -> None:
        cutoff = now - _WINDOW
        while self._errors and self._errors[0] < cutoff:
            self._errors.popleft()
        while self._latencies and self._latencies[0][0] < cutoff:
            self._latencies.popleft()

    def _check_thresholds(self, now: float) -> None:
        r = self.report()
        if r["errors_last_minute"] >= _ERROR_RATE_WARN:
            log.warning("health: %d errors in the last minute", r["errors_last_minute"])
        if r["p95_latency_ms"] >= _LATENCY_WARN_MS:
            log.warning("health: p95 latency %dms exceeds %dms threshold", r["p95_latency_ms"], _LATENCY_WARN_MS)
        if 0 <= r["memory_rss_mb"] >= _MEMORY_WARN_MB:
            log.warning("health: RSS %sMB exceeds %dMB threshold", r["memory_rss_mb"], _MEMORY_WARN_MB)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _percentile(data: list[float], p: int) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# Module-level singleton used by server.py
monitor = HealthMonitor()
