"""Unit tests for the shopping-list feature (server.py + memory.py's tasks table,
project="shopping"). detect_action_fast tests are pure; the _shopping_* handlers
run against an isolated tmp_path SQLite DB — never the real data/jarvis.db.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# server.py reads ANTHROPIC_API_KEY etc. from the environment at import time —
# load .env first so `import server` doesn't warn/misbehave, same as test_classifier.py.
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import pytest

import memory
from server import detect_action_fast, _shopping_add, _shopping_list_voice, _shopping_check, _split_items


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Every test in this file runs against a throwaway DB, never the real one."""
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "test_jarvis.db")
    memory.init_db()


# ---------------- _split_items ----------------

def test_split_items_comma_separated():
    assert _split_items("milk, eggs, bread") == ["milk", "eggs", "bread"]


def test_split_items_with_and():
    assert _split_items("milk, eggs and bread") == ["milk", "eggs", "bread"]


def test_split_items_single():
    assert _split_items("milk") == ["milk"]


def test_split_items_empty():
    assert _split_items("") == []
    assert _split_items("   ") == []


# ---------------- detect_action_fast: add ----------------

def test_detect_add_to_shopping_list():
    result = detect_action_fast("add milk to my shopping list")
    assert result == {"action": "shopping_add", "items": "milk"}


def test_detect_add_multiple_to_grocery_list():
    result = detect_action_fast("add milk, eggs and bread to the grocery list")
    assert result == {"action": "shopping_add", "items": "milk, eggs and bread"}


def test_detect_put_on_shopping_list():
    result = detect_action_fast("put bananas on my shopping list")
    assert result == {"action": "shopping_add", "items": "bananas"}


# ---------------- detect_action_fast: list ----------------

def test_detect_whats_on_shopping_list():
    assert detect_action_fast("what's on my shopping list") == {"action": "shopping_list"}


def test_detect_whats_on_grocery_list_no_apostrophe():
    assert detect_action_fast("whats on the grocery list") == {"action": "shopping_list"}


def test_detect_read_my_shopping_list():
    assert detect_action_fast("read my shopping list") == {"action": "shopping_list"}


def test_detect_what_do_i_need_to_buy():
    assert detect_action_fast("what do i need to buy") == {"action": "shopping_list"}


def test_detect_what_do_i_need_bare():
    assert detect_action_fast("what do i need") == {"action": "shopping_list"}


# ---------------- detect_action_fast: check off ----------------

def test_detect_check_off_bare():
    result = detect_action_fast("check off milk")
    assert result == {"action": "shopping_check", "items": "milk"}


def test_detect_check_off_from_list():
    result = detect_action_fast("check off milk from my shopping list")
    assert result == {"action": "shopping_check", "items": "milk"}


def test_detect_cross_off():
    result = detect_action_fast("cross off eggs")
    assert result == {"action": "shopping_check", "items": "eggs"}


def test_detect_remove_from_list_requires_list_mention():
    result = detect_action_fast("remove milk from my shopping list")
    assert result == {"action": "shopping_check", "items": "milk"}


def test_bare_remove_does_not_match_shopping():
    # "remove" alone (no list mention) is too generic to safely claim as shopping intent.
    assert detect_action_fast("remove that reminder") is None


# ---------------- detect_action_fast: no false positives ----------------

def test_unrelated_phrase_not_matched():
    assert detect_action_fast("what's the weather like") is None


def test_add_task_phrasing_not_swallowed_by_shopping():
    # Generic task add (no "shopping"/"grocery list" mention) must NOT be
    # misread as shopping-list intent — whatever else it matches (a separate,
    # pre-existing "check_tasks" fast-path also fires on the word "tasks",
    # unrelated to this feature) is out of scope here.
    result = detect_action_fast("add call the dentist to my tasks")
    assert result is None or not str(result.get("action", "")).startswith("shopping")


# ---------------- _shopping_add / _shopping_list_voice / _shopping_check (DB-backed) ----------------

def test_add_single_item_then_list():
    msg = _shopping_add("milk")
    assert "milk" in msg
    assert "sir" in msg
    listing = _shopping_list_voice()
    assert "milk" in listing


def test_add_multiple_items_then_list():
    _shopping_add("milk, eggs, bread")
    listing = _shopping_list_voice()
    assert "milk" in listing and "eggs" in listing and "bread" in listing


def test_empty_list_message():
    assert "empty" in _shopping_list_voice().lower()


def test_add_empty_string_gives_friendly_message():
    msg = _shopping_add("")
    assert "sir" in msg
    assert _shopping_list_voice().lower().count("empty") == 1  # nothing was actually added


def test_check_off_removes_from_list():
    _shopping_add("milk, eggs")
    msg = _shopping_check("milk")
    assert "milk" in msg
    listing = _shopping_list_voice()
    assert "milk" not in listing
    assert "eggs" in listing


def test_check_off_fuzzy_match():
    _shopping_add("oat milk")
    msg = _shopping_check("milk")
    assert "oat milk" in msg
    assert "empty" in _shopping_list_voice().lower()


def test_check_off_item_not_on_list():
    _shopping_add("milk")
    msg = _shopping_check("bananas")
    assert "couldn't find" in msg.lower()
    assert "milk" in _shopping_list_voice()  # untouched


def test_check_off_multiple_items():
    _shopping_add("milk, eggs, bread")
    msg = _shopping_check("milk, bread")
    assert "milk" in msg and "bread" in msg
    listing = _shopping_list_voice()
    assert "eggs" in listing
    assert "milk" not in listing and "bread" not in listing


def test_shopping_list_does_not_leak_other_projects():
    memory.create_task(title="Ship the report", project="work")
    _shopping_add("milk")
    listing = _shopping_list_voice()
    assert "milk" in listing
    assert "report" not in listing
