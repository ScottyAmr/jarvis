"""
Regression tests for a real incident (2026-08-17): the backend process died
with no Python-level traceback and no persistent log to diagnose it from
afterward. While investigating, found and fixed two related reliability
gaps: unbounded per-connection memory growth, and zero log persistence.
These tests guard against both regressing.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server import _rotate_history


# ── History rotation (unbounded-growth fix) ─────────────────────────────

def test_rotate_history_trims_in_place():
    history = [{"role": "user", "content": str(i)} for i in range(25)]
    original_object = history  # same list identity throughout
    rotated = _rotate_history(history, keep=20)

    assert len(rotated) == 5
    assert len(history) == 20
    assert history is original_object  # mutated in place, not reassigned
    assert history[0]["content"] == "5"  # the oldest 5 were the ones rotated out
    assert rotated[0]["content"] == "0"


def test_rotate_history_noop_when_under_threshold():
    history = [{"role": "user", "content": str(i)} for i in range(10)]
    rotated = _rotate_history(history, keep=20)
    assert rotated == []
    assert len(history) == 10  # untouched


def test_rotate_history_background_task_reference_still_sees_trim():
    """The actual bug this regression-tests: a background task (like
    _execute_prompt_project) is handed `history` as a parameter and later
    calls history.append(...). Reassigning `history = history[-20:]` in the
    caller would leave that background task's reference pointing at the old,
    now-abandoned list. In-place mutation (what _rotate_history does) means
    every holder of the reference sees the same trimmed-and-still-growing
    list — simulated here by capturing a second reference before rotating.
    """
    history = [{"role": "user", "content": str(i)} for i in range(25)]
    background_task_ref = history  # simulates a function called with history=history

    _rotate_history(history, keep=20)
    background_task_ref.append({"role": "assistant", "content": "from background task"})

    assert history[-1]["content"] == "from background task"
    assert len(history) == 21


def test_history_never_grows_unbounded_across_many_turns():
    """Simulates 200 conversation turns and confirms history stays bounded
    instead of growing linearly forever (the actual production bug)."""
    history = []
    for i in range(200):
        history.append({"role": "user", "content": f"turn {i}"})
        history.append({"role": "assistant", "content": f"response {i}"})
        if len(history) > 20:
            _rotate_history(history, keep=20)
    assert len(history) <= 20


# ── Log persistence (diagnosability fix) ────────────────────────────────

def test_data_dir_log_file_configured():
    """server.py must configure a persistent rotating file handler — the
    2026-08-17 incident was undiagnosable afterward specifically because
    logs only ever went to whatever terminal was open at the time."""
    import server  # noqa: F401  (importing re-runs the module-level logging setup)

    root_logger = logging.getLogger()
    file_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]
    assert file_handlers, "no RotatingFileHandler configured on the root logger"
    assert file_handlers[0].maxBytes > 0
    assert file_handlers[0].backupCount >= 1
