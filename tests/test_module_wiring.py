"""
Guards against the specific failure mode that's hit this project repeatedly:
a fully-written module sitting at the repo root that nobody ever imported
into server.py (conversation_memory.py, music_control.py, write_integrations.py,
and browser.py all shipped this way before being noticed and fixed by hand).

This test doesn't judge WHETHER a module should be wired in — some are
legitimately standalone CLI tools (has a __main__ guard) and some are a
known, tracked exception (see KNOWN_DISCONNECTED below). It just makes sure
a new module can't go silently unnoticed the way the previous ones did: it
has to be imported somewhere, have a __main__ guard, or be explicitly and
deliberately listed as a tracked exception with a reason.
"""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Modules at the repo root that are known to be disconnected from server.py
# right now, tracked deliberately rather than silently — see JARVIS_MEMORY.md
# "Known issues" for the reasoning behind each. Remove an entry once it's
# either wired in or deleted; don't add one without a comment explaining why.
KNOWN_DISCONNECTED = {
    "browser.py": "not wired to any action yet — fixed for headless/leak safety, not yet connected",
    # qa.py/tracking.py/suggestions.py were referenced by an auto-QA-retry
    # pipeline (ClaudeTaskManager._run_qa) in the very first commit — but
    # that code called qa_agent/success_tracker/suggest_followup without
    # ever importing them, so it was never actually functional, not merely
    # "disconnected later." Decision (2026-08-17): archive rather than
    # finish-and-wire-in — auto-retry-with-cost-implications on every build
    # deserves its own scoped design pass, not a blind reconnect. Same call
    # for ab_testing.py/evolution.py, which have zero trace of ever being
    # wired in at any point in git history.
    "ab_testing.py": "template-evolution subsystem — archived, see comment above",
    "evolution.py": "template-evolution subsystem — archived, see comment above",
    "learning.py": "template-evolution subsystem — archived, see comment above",
    "qa.py": "template-evolution subsystem — archived, see comment above",
    "suggestions.py": "template-evolution subsystem — archived, see comment above",
    "tracking.py": "template-evolution subsystem — archived, see comment above",
}

# Never expected to be imported — files that aren't importable Python modules
# in the relevant sense (setup/config scripts) are excluded by the glob below
# (only top-level *.py siblings of server.py are scanned).


def _has_main_guard(path: Path) -> bool:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
            ):
                return True
    return False


def _root_modules() -> list[Path]:
    return sorted(
        p for p in ROOT.glob("*.py")
        if p.name not in ("server.py", "conftest.py")
    )


def _imported_module_names() -> set[str]:
    """Every project-local module name reachable from server.py — a BFS over
    the import graph starting at server.py, so a module imported only by
    something server.py imports (e.g. templates.py via planner.py) still
    counts as wired in, not just server.py's direct imports."""
    imported = set()
    seen_files = set()
    to_scan = [ROOT / "server.py"]
    while to_scan:
        f = to_scan.pop()
        if f in seen_files or not f.exists():
            continue
        seen_files.add(f)
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    imported.add(top)
                    candidate = ROOT / f"{top}.py"
                    if candidate.exists():
                        to_scan.append(candidate)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                imported.add(top)
                candidate = ROOT / f"{top}.py"
                if candidate.exists():
                    to_scan.append(candidate)
    return imported


def test_every_root_module_is_wired_standalone_or_tracked():
    imported = _imported_module_names()
    unexplained = []
    for path in _root_modules():
        name = path.stem
        if name in imported:
            continue
        if _has_main_guard(path):
            continue
        if path.name in KNOWN_DISCONNECTED:
            continue
        unexplained.append(path.name)

    assert not unexplained, (
        f"{unexplained} are imported nowhere in server.py's dependency graph, "
        "have no __main__ guard (so aren't a standalone CLI tool), and aren't "
        "listed in KNOWN_DISCONNECTED. Either wire them in, add a __main__ "
        "guard if they're meant to run standalone, or add them to "
        "KNOWN_DISCONNECTED with a one-line reason so this doesn't have to "
        "be rediscovered by hand again."
    )


def test_known_disconnected_list_has_no_stale_entries():
    """If a tracked module gets wired in later, its KNOWN_DISCONNECTED entry
    should be removed — otherwise this list silently stops meaning anything."""
    imported = _imported_module_names()
    stale = [name for name in KNOWN_DISCONNECTED if Path(name).stem in imported]
    assert not stale, (
        f"{stale} are now imported by server.py but still listed in "
        "KNOWN_DISCONNECTED — remove their entries, they're wired in now."
    )
