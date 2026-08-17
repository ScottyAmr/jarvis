"""Unit tests for mail_access.py's _run_mail_script — the AppleScript subprocess
wrapper shared by every Mail.app call.

Regression coverage for two bugs found via live testing on 2026-08-16:
1. get_unread_count()/get_unread_messages() used to return "" on failure/timeout,
   silently indistinguishable from a genuinely empty result — now raises
   MailAccessError instead.
2. asyncio.wait_for's TimeoutError only stops *awaiting* the subprocess, it does
   NOT kill it — a timed-out osascript call (seen live: 30+ minutes against a
   2600+-message inbox) kept running as an orphaned background process. Now the
   process is explicitly killed and reaped on timeout.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import mail_access


@pytest.fixture(autouse=True)
def no_real_mail_launch(monkeypatch):
    """Never actually try to launch/activate Mail.app during unit tests."""
    monkeypatch.setattr(mail_access, "_ensure_mail_running", AsyncMock(return_value=None))


def make_mock_proc(returncode=0, stdout=b"", stderr=b"", hang=False):
    proc = AsyncMock()
    proc.returncode = returncode
    if hang:
        async def never_completes():
            await asyncio.sleep(999)
        proc.communicate = AsyncMock(side_effect=never_completes)
    else:
        proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = Mock()  # real asyncio.subprocess.Process.kill() is synchronous, not a coroutine
    proc.wait = AsyncMock(return_value=None)
    return proc


async def _patched_create_subprocess(monkeypatch, proc):
    async def fake_create_subprocess_exec(*args, **kwargs):
        return proc
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)


# ---------------- success path ----------------

def test_run_mail_script_returns_stdout_on_success(monkeypatch):
    proc = make_mock_proc(returncode=0, stdout=b"  total:3\n  ")
    asyncio.run(_patched_create_subprocess(monkeypatch, proc))

    result = asyncio.run(mail_access._run_mail_script("tell application \"Mail\" to return 1", timeout=5))
    assert result == "total:3"


# ---------------- failure path: raises, doesn't swallow ----------------

def test_run_mail_script_raises_on_nonzero_exit(monkeypatch):
    proc = make_mock_proc(returncode=1, stderr=b"Mail got an error: not authorized")
    asyncio.run(_patched_create_subprocess(monkeypatch, proc))

    with pytest.raises(mail_access.MailAccessError, match="not authorized"):
        asyncio.run(mail_access._run_mail_script("bad script", timeout=5))


def test_run_mail_script_failure_does_not_return_empty_string(monkeypatch):
    # Regression: the old contract silently returned "" on failure, which is
    # indistinguishable from a real "genuinely nothing to report" result.
    proc = make_mock_proc(returncode=1, stderr=b"boom")
    asyncio.run(_patched_create_subprocess(monkeypatch, proc))

    with pytest.raises(mail_access.MailAccessError):
        asyncio.run(mail_access._run_mail_script("bad script", timeout=5))


# ---------------- timeout path: raises AND kills the process ----------------

def test_run_mail_script_timeout_raises_mail_access_error(monkeypatch):
    proc = make_mock_proc(hang=True)
    asyncio.run(_patched_create_subprocess(monkeypatch, proc))

    with pytest.raises(mail_access.MailAccessError, match="timed out"):
        asyncio.run(mail_access._run_mail_script("tell application \"Mail\" to return 1", timeout=0.05))


def test_run_mail_script_timeout_kills_the_orphaned_process(monkeypatch):
    proc = make_mock_proc(hang=True)
    asyncio.run(_patched_create_subprocess(monkeypatch, proc))

    with pytest.raises(mail_access.MailAccessError):
        asyncio.run(mail_access._run_mail_script("tell application \"Mail\" to return 1", timeout=0.05))

    proc.kill.assert_called_once_with()
    proc.wait.assert_awaited_once()
