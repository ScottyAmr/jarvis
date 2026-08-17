import signal
from types import SimpleNamespace

import watchdog


class FakeResponse:
    status = 200

    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def test_poll_health_accepts_online_payload(monkeypatch):
    monkeypatch.setattr(
        watchdog.urllib.request,
        "urlopen",
        lambda url, timeout: FakeResponse(b'{"status":"online","health":{"ok":true}}'),
    )

    ok, reason, payload = watchdog.poll_health("http://test/health", timeout=1)

    assert ok is True
    assert reason == "ok"
    assert payload["status"] == "online"


def test_poll_health_can_use_insecure_tls_context(monkeypatch):
    calls = []

    def fake_urlopen(url, timeout, context=None):
        calls.append(context)
        return FakeResponse(b'{"status":"online","health":{"ok":true}}')

    monkeypatch.setattr(watchdog.urllib.request, "urlopen", fake_urlopen)

    ok, _, _ = watchdog.poll_health("https://test/health", timeout=1, insecure_tls=True)

    assert ok is True
    assert calls[0] is not None


def test_poll_health_rejects_bad_status(monkeypatch):
    monkeypatch.setattr(
        watchdog.urllib.request,
        "urlopen",
        lambda url, timeout: FakeResponse(b'{"status":"starting"}'),
    )

    ok, reason, payload = watchdog.poll_health("http://test/health", timeout=1)

    assert ok is False
    assert "bad status" in reason
    assert payload["status"] == "starting"


def test_restart_limiter_caps_restarts(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(watchdog.time, "time", lambda: now[0])
    limiter = watchdog.RestartLimiter(max_restarts=2, window_seconds=60)

    assert limiter.allow() is True
    assert limiter.allow() is True
    assert limiter.allow() is False

    now[0] += 61
    assert limiter.allow() is True


def test_terminate_backend_uses_sigkill_as_final_fallback(monkeypatch):
    signals = []
    monkeypatch.setattr(watchdog, "port_pids", lambda port: [123])
    monkeypatch.setattr(watchdog, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(watchdog.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(watchdog.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    killed = watchdog.terminate_backend(port=8340, grace_seconds=0)

    assert killed == [123]
    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)]


def test_recover_prefers_graceful_restart(monkeypatch):
    calls = []
    args = SimpleNamespace(
        port=8340,
        restart_url="http://test/restart",
        timeout=1,
        grace_seconds=1,
        restart_command="",
        insecure_tls=False,
    )
    monkeypatch.setattr(watchdog, "log_diagnostics", lambda reason, port: calls.append("diagnostics"))
    monkeypatch.setattr(watchdog, "request_restart", lambda url, timeout, insecure_tls=False: True)
    monkeypatch.setattr(watchdog, "terminate_backend", lambda port, grace_seconds: calls.append("terminate"))
    monkeypatch.setattr(watchdog, "start_backend", lambda command: calls.append("start"))

    watchdog.recover(args, "timeout")

    assert calls == ["diagnostics"]
