import json
from pathlib import Path

from common import load_seen, save_seen


def test_load_seen_returns_empty_when_missing(tmp_path):
    assert load_seen(tmp_path / "nope.json") == {}


def test_save_then_load_roundtrip(tmp_path):
    seen_file = tmp_path / "seen.json"
    save_seen(seen_file, {"abc": "2026-08-01T00:00:00+00:00"})
    loaded = load_seen(seen_file)
    assert loaded["abc"] == "2026-08-01T00:00:00+00:00"


def test_save_seen_prunes_old_entries(tmp_path):
    from datetime import datetime, timezone, timedelta
    seen_file = tmp_path / "seen.json"
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    save_seen(seen_file, {"old": old, "new": recent})
    loaded = load_seen(seen_file)
    assert "new" in loaded
    assert "old" not in loaded


def test_save_seen_creates_parent_dir(tmp_path):
    seen_file = tmp_path / "sub" / "dir" / "seen.json"
    save_seen(seen_file, {"x": "2026-08-01T00:00:00+00:00"})
    assert seen_file.exists()
