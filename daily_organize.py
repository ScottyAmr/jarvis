#!/usr/bin/env python3
"""JARVIS daily organize scan — run on a schedule via launchd.

Only ever scans and notifies. Never moves or deletes anything: applying the
plan still requires the user to confirm with JARVIS ("organize confirm").
"""
import logging
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import file_organizer as fo

log = logging.getLogger("jarvis.daily_organize")
logging.basicConfig(level=logging.INFO)


def notify(title: str, message: str) -> None:
    escaped_msg = message.replace("\\", "\\\\").replace('"', '\\"')
    escaped_title = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{escaped_msg}" with title "{escaped_title}"'
    subprocess.run(["osascript", "-e", script], check=False)


def main() -> None:
    try:
        plan = fo.scan()
        fo.save_plan(plan)
        fo.render_report_html(plan)
    except Exception:
        log.exception("daily organize scan failed")
        notify("JARVIS — Daily Organize", "Today's scan hit an error and didn't finish — check daily_organize.err.")
        return

    moves = len(plan["moves"])
    dupes = len(plan["duplicates"])
    if not moves and not dupes:
        notify("JARVIS", "Daily scan complete — nothing to sort today.")
        return

    parts = []
    if moves:
        parts.append(f"{moves} files to sort")
    if dupes:
        parts.append(f"{dupes} likely duplicates")
    notify("JARVIS — Daily Organize", f"Found {' and '.join(parts)}. Ask JARVIS to organize to review and apply.")


if __name__ == "__main__":
    main()
