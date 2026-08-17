"""Unit tests for file_organizer.py — scan/plan/apply for Downloads/Desktop cleanup.

All tests operate on pytest's tmp_path, never on real Downloads/Desktop. apply_plan's
duplicate-trash step is monkeypatched so tests never shell out to Finder/AppleScript.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import file_organizer as fo


def write(p: Path, content: bytes | None = None, mtime: float | None = None) -> Path:
    # Default content is unique per filename so unrelated test files never
    # accidentally hash-collide into false "duplicate" detections — tests that
    # want a real duplicate pass matching `content` explicitly.
    p.write_bytes(content if content is not None else f"data-{p.name}".encode())
    if mtime is not None:
        import os
        os.utime(p, (mtime, mtime))
    return p


# ---------------- scan() ----------------

def test_scan_categorizes_by_extension(tmp_path):
    write(tmp_path / "photo.jpg")
    write(tmp_path / "report.pdf")
    write(tmp_path / "song.mp3")

    plan = fo.scan([tmp_path])
    by_name = {Path(m["src"]).name: m["category"] for m in plan["moves"]}
    assert by_name["photo.jpg"] == "Images"
    assert by_name["report.pdf"] == "Documents"
    assert by_name["song.mp3"] == "Audio"


def test_scan_unknown_extension_goes_to_other(tmp_path):
    write(tmp_path / "weird.xyz")
    plan = fo.scan([tmp_path])
    assert plan["moves"][0]["category"] == "Other"


def test_scan_skips_dotfiles(tmp_path):
    write(tmp_path / ".DS_Store")
    write(tmp_path / ".hidden")
    plan = fo.scan([tmp_path])
    assert plan["moves"] == []


def test_scan_skips_directories_and_app_bundles(tmp_path):
    (tmp_path / "Some Folder").mkdir()
    (tmp_path / "Thing.app").mkdir()
    write(tmp_path / "real.txt")
    plan = fo.scan([tmp_path])
    names = [Path(m["src"]).name for m in plan["moves"]]
    assert names == ["real.txt"]


def test_scan_skips_own_sorted_folder(tmp_path):
    sorted_dir = tmp_path / fo.SORTED_FOLDER_NAME
    sorted_dir.mkdir()
    write(sorted_dir / "already_sorted.txt")
    plan = fo.scan([tmp_path])
    assert plan["moves"] == []


def test_scan_flags_stale_files(tmp_path):
    old = write(tmp_path / "old.txt", mtime=time.time() - fo.STALE_DAYS * 86400 - 3600)
    fresh = write(tmp_path / "fresh.txt")
    plan = fo.scan([tmp_path])
    by_name = {Path(m["src"]).name: m["stale"] for m in plan["moves"]}
    assert by_name["old.txt"] is True
    assert by_name["fresh.txt"] is False


def test_scan_missing_directory_is_skipped_not_an_error(tmp_path):
    missing = tmp_path / "does-not-exist"
    plan = fo.scan([missing])
    assert plan["moves"] == []
    assert plan["duplicates"] == []


def test_scan_dest_is_under_category_subfolder(tmp_path):
    write(tmp_path / "photo.jpg")
    plan = fo.scan([tmp_path])
    dest = Path(plan["moves"][0]["dest"])
    assert dest.parent == tmp_path / fo.SORTED_FOLDER_NAME / "Images"


# ---------------- duplicate detection ----------------

def test_scan_detects_exact_duplicates_keeps_newest(tmp_path):
    older = write(tmp_path / "older.jpg", content=b"same-bytes", mtime=1000)
    newer = write(tmp_path / "newer.jpg", content=b"same-bytes", mtime=2000)

    plan = fo.scan([tmp_path])
    assert len(plan["duplicates"]) == 1
    dup = plan["duplicates"][0]
    assert dup["keep"] == str(newer)
    assert dup["trash"] == str(older)


def test_duplicate_files_excluded_from_moves(tmp_path):
    # A file flagged for Trash must not also be scheduled as a move — otherwise
    # apply_plan moves it first and the trash step finds nothing there.
    write(tmp_path / "older.jpg", content=b"same-bytes", mtime=1000)
    write(tmp_path / "newer.jpg", content=b"same-bytes", mtime=2000)

    plan = fo.scan([tmp_path])
    move_srcs = {m["src"] for m in plan["moves"]}
    trash_srcs = {d["trash"] for d in plan["duplicates"]}
    assert move_srcs.isdisjoint(trash_srcs)
    # the kept copy still gets a normal move scheduled
    assert any(Path(s).name == "newer.jpg" for s in move_srcs)


def test_different_content_same_extension_not_flagged_duplicate(tmp_path):
    write(tmp_path / "a.jpg", content=b"aaaa")
    write(tmp_path / "b.jpg", content=b"bbbb")
    plan = fo.scan([tmp_path])
    assert plan["duplicates"] == []


# ---------------- parse_scope ----------------

def test_parse_scope_downloads():
    dirs = fo.parse_scope("clean up my downloads")
    assert dirs == [Path.home() / "Downloads"]


def test_parse_scope_desktop():
    dirs = fo.parse_scope("tidy the desktop")
    assert dirs == [Path.home() / "Desktop"]


def test_parse_scope_both():
    dirs = fo.parse_scope("downloads and desktop")
    assert dirs == [Path.home() / "Downloads", Path.home() / "Desktop"]


def test_parse_scope_empty_returns_none():
    assert fo.parse_scope("") is None
    assert fo.parse_scope("organize everything") is None


# ---------------- save_plan / load_plan ----------------

def test_save_and_load_plan_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(fo, "JARVIS_DIR", tmp_path)
    monkeypatch.setattr(fo, "PLAN_PATH", tmp_path / "organize_plan.json")

    plan = {"scanned_at": time.time(), "dirs": ["/x"], "moves": [], "duplicates": []}
    fo.save_plan(plan)
    loaded = fo.load_plan()
    assert loaded == plan


def test_load_plan_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(fo, "PLAN_PATH", tmp_path / "nonexistent.json")
    assert fo.load_plan() is None


def test_load_plan_stale_returns_none(tmp_path, monkeypatch):
    plan_path = tmp_path / "organize_plan.json"
    monkeypatch.setattr(fo, "PLAN_PATH", plan_path)
    stale_plan = {"scanned_at": time.time() - fo.PLAN_MAX_AGE - 60, "dirs": [], "moves": [], "duplicates": []}
    plan_path.write_text(json.dumps(stale_plan))
    assert fo.load_plan() is None


def test_load_plan_corrupt_json_returns_none(tmp_path, monkeypatch):
    plan_path = tmp_path / "organize_plan.json"
    monkeypatch.setattr(fo, "PLAN_PATH", plan_path)
    plan_path.write_text("{not valid json")
    assert fo.load_plan() is None


def test_clear_plan_removes_file_and_is_idempotent(tmp_path, monkeypatch):
    plan_path = tmp_path / "organize_plan.json"
    monkeypatch.setattr(fo, "PLAN_PATH", plan_path)
    plan_path.write_text("{}")
    fo.clear_plan()
    assert not plan_path.exists()
    fo.clear_plan()  # second call must not raise


# ---------------- summarize_plan ----------------

def test_summarize_plan_nothing_to_sort():
    summary = fo.summarize_plan({"moves": [], "duplicates": []})
    assert "nothing" in summary.lower()


def test_summarize_plan_mentions_counts():
    plan = {
        "moves": [{"category": "Images"}, {"category": "Documents"}],
        "duplicates": [{}],
    }
    summary = fo.summarize_plan(plan)
    assert "2 files" in summary
    assert "1 likely duplicates" in summary


# ---------------- _dedupe_name ----------------

def test_dedupe_name_no_collision_returns_same_path(tmp_path):
    dest = tmp_path / "file.txt"
    assert fo._dedupe_name(dest) == dest


def test_dedupe_name_collision_appends_counter(tmp_path):
    write(tmp_path / "file.txt")
    result = fo._dedupe_name(tmp_path / "file.txt")
    assert result == tmp_path / "file (2).txt"


def test_dedupe_name_multiple_collisions_increments(tmp_path):
    write(tmp_path / "file.txt")
    write(tmp_path / "file (2).txt")
    write(tmp_path / "file (3).txt")
    result = fo._dedupe_name(tmp_path / "file.txt")
    assert result == tmp_path / "file (4).txt"


# ---------------- apply_plan ----------------

def test_apply_plan_moves_files_into_category_folders(tmp_path):
    write(tmp_path / "photo.jpg")
    plan = fo.scan([tmp_path])

    result = asyncio.run(fo.apply_plan(plan))

    assert result["moved"] == 1
    assert result["move_errors"] == []
    dest = tmp_path / fo.SORTED_FOLDER_NAME / "Images" / "photo.jpg"
    assert dest.exists()
    assert not (tmp_path / "photo.jpg").exists()


def test_apply_plan_dedupes_on_name_collision(tmp_path):
    write(tmp_path / "photo.jpg", content=b"first")
    existing_dest = tmp_path / fo.SORTED_FOLDER_NAME / "Images" / "photo.jpg"
    existing_dest.parent.mkdir(parents=True)
    write(existing_dest, content=b"already-there")

    plan = fo.scan([tmp_path])
    result = asyncio.run(fo.apply_plan(plan))

    assert result["moved"] == 1
    assert existing_dest.read_bytes() == b"already-there"  # untouched
    assert (tmp_path / fo.SORTED_FOLDER_NAME / "Images" / "photo (2).jpg").exists()


def test_apply_plan_skips_files_already_gone(tmp_path):
    write(tmp_path / "photo.jpg")
    plan = fo.scan([tmp_path])
    (tmp_path / "photo.jpg").unlink()  # moved/deleted by something else since the scan

    result = asyncio.run(fo.apply_plan(plan))
    assert result["moved"] == 0
    assert result["move_errors"] == []


def test_apply_plan_calls_trash_for_each_duplicate_and_reports_result(tmp_path, monkeypatch):
    write(tmp_path / "older.jpg", content=b"same", mtime=1000)
    write(tmp_path / "newer.jpg", content=b"same", mtime=2000)
    plan = fo.scan([tmp_path])
    assert len(plan["duplicates"]) == 1

    trashed_paths = []

    async def fake_move_to_trash(path):
        trashed_paths.append(path)
        return True

    monkeypatch.setattr(fo, "_move_to_trash", fake_move_to_trash)

    result = asyncio.run(fo.apply_plan(plan))

    assert result["trashed"] == 1
    assert result["trash_errors"] == []
    assert trashed_paths == [Path(plan["duplicates"][0]["trash"])]


def test_apply_plan_reports_trash_failures(tmp_path, monkeypatch):
    write(tmp_path / "older.jpg", content=b"same", mtime=1000)
    write(tmp_path / "newer.jpg", content=b"same", mtime=2000)
    plan = fo.scan([tmp_path])

    async def fake_move_to_trash(path):
        return False

    monkeypatch.setattr(fo, "_move_to_trash", fake_move_to_trash)

    result = asyncio.run(fo.apply_plan(plan))
    assert result["trashed"] == 0
    assert result["trash_errors"] == ["older.jpg"]


# ---------------- EINTR hardening (regression: real launchd crash 2026-08-16) ----------------

def test_iter_candidate_files_retries_on_interrupted_error(tmp_path, monkeypatch):
    write(tmp_path / "photo.jpg")

    real_iterdir = Path.iterdir
    calls = {"n": 0}

    def flaky_iterdir(self):
        if self == tmp_path and calls["n"] == 0:
            calls["n"] += 1
            raise InterruptedError("simulated EINTR")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", flaky_iterdir)

    entries = list(fo._iter_candidate_files(tmp_path))
    assert [e.name for e in entries] == ["photo.jpg"]


def test_iter_candidate_files_gives_up_after_max_retries(tmp_path, monkeypatch):
    def always_interrupted(self):
        raise InterruptedError("simulated persistent EINTR")

    monkeypatch.setattr(Path, "iterdir", always_interrupted)

    # scan() must not crash even if a directory can never be listed —
    # it should log and skip, not raise.
    entries = list(fo._iter_candidate_files(tmp_path))
    assert entries == []


def test_scan_does_not_crash_when_one_directory_is_unreadable(tmp_path, monkeypatch):
    good_dir = tmp_path / "good"
    good_dir.mkdir()
    write(good_dir / "file.txt")
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()

    real_iterdir = Path.iterdir

    def flaky_iterdir(self):
        if self == bad_dir:
            raise InterruptedError("simulated EINTR")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", flaky_iterdir)

    plan = fo.scan([good_dir, bad_dir])
    assert [Path(m["src"]).name for m in plan["moves"]] == ["file.txt"]
