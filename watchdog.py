#!/usr/bin/env python3
"""
External watchdog for JARVIS.

Polls the cheap /api/health endpoint from a separate process. If the backend
stops responding repeatedly, it records diagnostics, asks for a graceful restart
when possible, then terminates the backend port. SIGKILL is the final fallback.
"""

from __future__ import annotations

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shlex
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "data"
LOG_FILE = LOG_DIR / "watchdog.log"
JARVIS_LOG = LOG_DIR / "jarvis.log"

log = logging.getLogger("jarvis.watchdog")


def configure_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler], force=True)


def _ssl_context(insecure_tls: bool) -> ssl.SSLContext | None:
    if insecure_tls:
        return ssl._create_unverified_context()
    return None


def poll_health(url: str, timeout: float, insecure_tls: bool = False) -> tuple[bool, str, dict[str, Any]]:
    try:
        context = _ssl_context(insecure_tls)
        if context:
            resp_ctx = urllib.request.urlopen(url, timeout=timeout, context=context)
        else:
            resp_ctx = urllib.request.urlopen(url, timeout=timeout)
        with resp_ctx as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status_code = getattr(resp, "status", 200)
        if status_code < 200 or status_code >= 300:
            return False, f"HTTP {status_code}", {}
        payload = json.loads(body)
        if payload.get("status") not in ("online", "degraded"):
            return False, f"bad status: {payload.get('status')!r}", payload
        return True, "ok", payload
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}", {}
    except Exception as e:
        return False, str(e), {}


def port_pids(port: int) -> list[int]:
    proc = subprocess.run(
        ["lsof", "-ti", f":{port}"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    pids = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def process_snapshot(port: int) -> str:
    proc = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return (proc.stdout or proc.stderr or "").strip()


def tail_file(path: Path, lines: int = 80) -> str:
    try:
        data = path.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return "(jarvis.log not found)"
    except Exception as e:
        return f"(could not read {path.name}: {e})"
    return "\n".join(data[-lines:]) if data else "(jarvis.log is empty)"


def log_diagnostics(reason: str, port: int) -> None:
    log.warning("backend health failed repeatedly: %s", reason)
    snapshot = process_snapshot(port)
    if snapshot:
        log.warning("listening processes on port %s:\n%s", port, snapshot)
    else:
        log.warning("no listening process found on port %s", port)
    log.warning("recent jarvis.log tail:\n%s", tail_file(JARVIS_LOG))


def request_restart(url: str, timeout: float, insecure_tls: bool = False) -> bool:
    req = urllib.request.Request(url, method="POST")
    try:
        context = _ssl_context(insecure_tls)
        if context:
            resp_ctx = urllib.request.urlopen(req, timeout=timeout, context=context)
        else:
            resp_ctx = urllib.request.urlopen(req, timeout=timeout)
        with resp_ctx as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception as e:
        log.info("graceful restart request failed: %s", e)
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def terminate_backend(port: int, grace_seconds: float) -> list[int]:
    pids = port_pids(port)
    if not pids:
        return []

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        if not any(_pid_alive(pid) for pid in pids):
            return pids
        time.sleep(0.2)

    for pid in pids:
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return pids


def start_backend(command: str | None) -> None:
    if not command:
        return
    args = shlex.split(command)
    if not args:
        return
    subprocess.Popen(args, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.info("started backend with restart command: %s", command)


class RestartLimiter:
    def __init__(self, max_restarts: int, window_seconds: int) -> None:
        self.max_restarts = max_restarts
        self.window_seconds = window_seconds
        self.window_started = time.time()
        self.count = 0

    def allow(self) -> bool:
        now = time.time()
        if now - self.window_started > self.window_seconds:
            self.window_started = now
            self.count = 0
        if self.count >= self.max_restarts:
            return False
        self.count += 1
        return True


def recover(args: argparse.Namespace, reason: str) -> None:
    log_diagnostics(reason, args.port)

    if request_restart(args.restart_url, args.timeout, args.insecure_tls):
        log.warning("requested graceful restart via %s", args.restart_url)
        return

    killed = terminate_backend(args.port, args.grace_seconds)
    if killed:
        log.warning("terminated backend pids on port %s: %s", args.port, killed)
    else:
        log.warning("no backend pid found to terminate")
    start_backend(args.restart_command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="External JARVIS health watchdog")
    parser.add_argument("--health-url", default="http://127.0.0.1:8340/api/health")
    parser.add_argument("--restart-url", default="http://127.0.0.1:8340/api/restart")
    parser.add_argument("--port", type=int, default=8340)
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--failures", type=int, default=3)
    parser.add_argument("--grace-seconds", type=float, default=8.0)
    parser.add_argument("--max-restarts", type=int, default=3)
    parser.add_argument("--restart-window", type=int, default=600)
    parser.add_argument("--restart-command", default="")
    parser.add_argument("--insecure-tls", action="store_true", help="Trust local self-signed HTTPS certs")
    parser.add_argument("--once", action="store_true", help="Poll once and exit without recovery")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    limiter = RestartLimiter(args.max_restarts, args.restart_window)
    failures = 0
    last_reason = ""

    log.info("watchdog started for %s", args.health_url)

    while True:
        ok, reason, payload = poll_health(args.health_url, args.timeout, args.insecure_tls)
        if ok:
            failures = 0
            health = payload.get("health", {})
            warnings = health.get("warnings") or []
            if warnings:
                log.info("backend responsive with warnings: %s", ", ".join(warnings))
        else:
            failures += 1
            last_reason = reason
            log.warning("health poll failed (%s/%s): %s", failures, args.failures, reason)

        if args.once:
            return 0 if ok else 1

        if failures >= args.failures:
            if not limiter.allow():
                log.critical(
                    "restart cap reached: %s restarts in %ss; refusing recovery loop",
                    args.max_restarts,
                    args.restart_window,
                )
                return 2
            recover(args, last_reason)
            failures = 0

        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
