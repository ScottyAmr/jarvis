"""
JARVIS File Organizer — dry-run scan + apply for sorting Downloads/Desktop clutter.

scan() is pure and read-only: it only ever produces a plan, never touches disk.
apply_plan() is the only function that moves files, and it only moves files into
category subfolders or (for exact duplicates) to the macOS Trash — never a hard
delete. Nothing in this module writes outside the scanned directories except the
plan/report files under ~/.jarvis.
"""

import asyncio
import hashlib
import json
import logging
import shutil
import time
from pathlib import Path

log = logging.getLogger("jarvis.organizer")

JARVIS_DIR = Path.home() / ".jarvis"
PLAN_PATH = JARVIS_DIR / "organize_plan.json"
REPORT_PATH = JARVIS_DIR / "organize_report.html"
PLAN_MAX_AGE = 3600  # seconds — a stale plan must be rescanned before it can be applied

DEFAULT_DIRS = [Path.home() / "Downloads", Path.home() / "Desktop"]

CATEGORY_RULES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".heic", ".webp", ".svg", ".bmp", ".tiff"},
    "Documents": {".pdf", ".doc", ".docx", ".pages", ".txt", ".rtf", ".md"},
    "Spreadsheets": {".xls", ".xlsx", ".csv", ".numbers"},
    "Presentations": {".ppt", ".pptx", ".key"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Installers": {".dmg", ".pkg"},
    "Audio": {".mp3", ".wav", ".m4a", ".flac", ".aac"},
    "Video": {".mp4", ".mov", ".avi", ".mkv"},
    "Code": {".py", ".js", ".ts", ".json", ".sh", ".html", ".css"},
}
EXT_TO_CATEGORY = {ext: cat for cat, exts in CATEGORY_RULES.items() for ext in exts}

SKIP_NAMES = {".DS_Store", ".localized"}
SORTED_FOLDER_NAME = "JARVIS Sorted"
STALE_DAYS = 90


def parse_scope(target: str) -> list[Path] | None:
    """Map a spoken scope ('downloads', 'desktop', or empty) to target dirs."""
    t = (target or "").lower()
    dirs = []
    if "download" in t:
        dirs.append(Path.home() / "Downloads")
    if "desktop" in t:
        dirs.append(Path.home() / "Desktop")
    return dirs or None  # None => caller should use DEFAULT_DIRS


def _listdir_retry(directory: Path, attempts: int = 5) -> list[Path]:
    """os.scandir can raise InterruptedError (EINTR) when run under launchd —
    seen in practice on the scheduled daily scan. Retry a few times before
    giving up on this directory rather than crashing the whole scan."""
    last_err: OSError | None = None
    for _ in range(attempts):
        try:
            return list(directory.iterdir())
        except InterruptedError as e:
            last_err = e
            continue
    raise last_err


def _iter_candidate_files(directory: Path):
    if not directory.exists():
        return
    try:
        entries = _listdir_retry(directory)
    except OSError as e:
        log.warning(f"could not list {directory}, skipping: {e}")
        return
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.name in SKIP_NAMES or entry.name == SORTED_FOLDER_NAME:
            continue
        if entry.is_dir() or entry.suffix.lower() == ".app":
            continue  # never touch folders or application bundles automatically
        yield entry


def _hash_file(path: Path, chunk_size: int = 65536) -> str:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def scan(dirs: list[Path] | None = None) -> dict:
    """Read-only scan of target directories. Returns a plan; touches nothing."""
    dirs = dirs or DEFAULT_DIRS
    moves = []
    by_hash: dict[str, list[dict]] = {}
    now = time.time()

    for directory in dirs:
        for entry in _iter_candidate_files(directory):
            try:
                stat = entry.stat()
            except OSError:
                continue
            category = EXT_TO_CATEGORY.get(entry.suffix.lower(), "Other")
            dest = directory / SORTED_FOLDER_NAME / category / entry.name
            age_days = (now - stat.st_mtime) / 86400
            moves.append({
                "src": str(entry),
                "dest": str(dest),
                "category": category,
                "size": stat.st_size,
                "age_days": round(age_days, 1),
                "stale": age_days > STALE_DAYS,
            })
            file_hash = _hash_file(entry)
            if file_hash:
                by_hash.setdefault(file_hash, []).append(
                    {"path": str(entry), "mtime": stat.st_mtime, "size": stat.st_size}
                )

    duplicates = []
    for files in by_hash.values():
        if len(files) < 2:
            continue
        files.sort(key=lambda f: f["mtime"], reverse=True)  # newest kept
        keep = files[0]
        for dup in files[1:]:
            duplicates.append({"keep": keep["path"], "trash": dup["path"], "size": dup["size"]})

    # A file going to Trash as a duplicate must not ALSO be scheduled as a
    # move — otherwise apply_plan moves it first, the trash step then finds
    # nothing at the original path, and the duplicate silently survives
    # (mis-sorted, never trashed) instead of being removed.
    trash_paths = {d["trash"] for d in duplicates}
    moves = [m for m in moves if m["src"] not in trash_paths]

    return {
        "scanned_at": now,
        "dirs": [str(d) for d in dirs],
        "moves": moves,
        "duplicates": duplicates,
    }


def save_plan(plan: dict) -> None:
    JARVIS_DIR.mkdir(exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan))


def load_plan() -> dict | None:
    """Load the last scanned plan, or None if missing/stale — never silently rescans."""
    if not PLAN_PATH.exists():
        return None
    try:
        plan = json.loads(PLAN_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if time.time() - plan.get("scanned_at", 0) > PLAN_MAX_AGE:
        return None
    return plan


def clear_plan() -> None:
    PLAN_PATH.unlink(missing_ok=True)


def summarize_plan(plan: dict) -> str:
    moves = plan.get("moves", [])
    dupes = plan.get("duplicates", [])
    if not moves and not dupes:
        return "Nothing to sort, sir — everything's already tidy."
    categories = {m["category"] for m in moves}
    parts = []
    if moves:
        parts.append(f"found {len(moves)} files to sort into {len(categories)} categories")
    if dupes:
        parts.append(f"{len(dupes)} likely duplicates to send to the Trash")
    summary = " and ".join(parts)
    return f"I've {summary} — take a look at the report, then say the word and I'll apply it, sir."


def _dedupe_name(dest: Path) -> Path:
    """Avoid overwriting an existing file at dest by appending ' (2)', ' (3)', ..."""
    if not dest.exists():
        return dest
    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    i = 2
    candidate = parent / f"{stem} ({i}){suffix}"
    while candidate.exists():
        i += 1
        candidate = parent / f"{stem} ({i}){suffix}"
    return candidate


def _apply_moves(plan: dict) -> tuple[int, list[str]]:
    """Blocking file-move loop — run this via asyncio.to_thread."""
    moved = 0
    errors = []
    for m in plan.get("moves", []):
        src = Path(m["src"])
        if not src.exists():
            continue  # already handled/moved since the scan
        dest = Path(m["dest"])
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest = _dedupe_name(dest)
            shutil.move(str(src), str(dest))
            moved += 1
        except OSError as e:
            errors.append(f"{src.name}: {e}")
    return moved, errors


async def _move_to_trash(path: Path) -> bool:
    """Move a file to the macOS Trash (reversible) via Finder — never a hard delete."""
    escaped = str(path).replace("\\", "\\\\").replace('"', '\\"')
    script = f'tell application "Finder" to delete POSIX file "{escaped}"'
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        log.warning(f"trash failed for {path}: {stderr.decode()}")
        return False
    return True


async def apply_plan(plan: dict) -> dict:
    """Execute a previously-scanned plan. Sorts files into category folders and
    sends flagged duplicates to Trash. Only ever acts on files still present."""
    moved, move_errors = await asyncio.to_thread(_apply_moves, plan)

    trashed = 0
    trash_errors = []
    for d in plan.get("duplicates", []):
        src = Path(d["trash"])
        if not src.exists():
            continue
        if await _move_to_trash(src):
            trashed += 1
        else:
            trash_errors.append(Path(d["trash"]).name)

    return {"moved": moved, "trashed": trashed, "move_errors": move_errors, "trash_errors": trash_errors}


def render_report_html(plan: dict) -> Path:
    """Render the dry-run plan as a dark-themed HTML report and return its path."""
    moves = plan.get("moves", [])
    dupes = plan.get("duplicates", [])

    by_category: dict[str, list[dict]] = {}
    for m in moves:
        by_category.setdefault(m["category"], []).append(m)

    def fmt_size(n: float) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f}{unit}"
            n /= 1024
        return f"{n:.1f}TB"

    sections = []
    for category in sorted(by_category, key=lambda c: -len(by_category[c])):
        items = by_category[category]
        rows = "\n".join(
            f'<tr><td>{Path(m["src"]).name}</td><td>{fmt_size(m["size"])}</td>'
            f'<td>{m["age_days"]}d{" ⚠ stale" if m["stale"] else ""}</td></tr>'
            for m in items
        )
        sections.append(
            f'<h2>{category} <span class="count">({len(items)})</span></h2>'
            f'<table><tr><th>File</th><th>Size</th><th>Age</th></tr>{rows}</table>'
        )

    dupe_rows = "\n".join(
        f'<tr><td>{Path(d["trash"]).name}</td><td>{fmt_size(d["size"])}</td>'
        f'<td>keeping {Path(d["keep"]).name}</td></tr>'
        for d in dupes
    )
    dupe_section = (
        f'<h2>Duplicates <span class="count">({len(dupes)})</span></h2>'
        f'<table><tr><th>File (→ Trash)</th><th>Size</th><th>Note</th></tr>{dupe_rows}</table>'
        if dupes else ""
    )

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>JARVIS Organize Report</title>
<style>
  body {{ background:#0d1117; color:#c9d1d9; font-family:-apple-system,sans-serif; padding:2rem 3rem; }}
  h1 {{ color:#58a6ff; font-weight:600; }}
  h2 {{ margin-top:2rem; color:#e6edf3; font-size:1.1rem; }}
  .count {{ color:#8b949e; font-weight:400; }}
  table {{ width:100%; border-collapse:collapse; margin-top:0.5rem; }}
  th, td {{ text-align:left; padding:0.4rem 0.6rem; border-bottom:1px solid #21262d; font-size:0.9rem; }}
  th {{ color:#8b949e; font-weight:500; }}
  .meta {{ color:#8b949e; font-size:0.85rem; }}
</style></head>
<body>
  <h1>JARVIS Organize — Dry Run</h1>
  <p class="meta">Scanned: {", ".join(plan.get("dirs", []))} · This is a preview only — nothing has moved yet.</p>
  {"".join(sections) or "<p>Nothing to sort.</p>"}
  {dupe_section}
</body></html>"""

    JARVIS_DIR.mkdir(exist_ok=True)
    REPORT_PATH.write_text(html)
    return REPORT_PATH
