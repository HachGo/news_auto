import json
from pathlib import Path
from unittest.mock import patch

from sources import cninfo

FIX = Path(__file__).parent / "fixtures" / "cninfo_announcements.json"


def test_parse_announcements(monkeypatch):
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    monkeypatch.setattr(cninfo, "fetch_announcements_json", lambda **kw: raw)
    items = cninfo.fetch_announcements(limit=5)
    assert len(items) >= 1
    assert items[0]["sec_name"] == "先导基电"
    assert items[0]["title"] == "2025年年度报告"
    assert items[0]["url"].endswith(".PDF")


def test_fetch_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(cninfo, "fetch_announcements_json", lambda **kw: None)
    assert cninfo.fetch_announcements() is None


def test_fetch_respects_limit(monkeypatch):
    raw = {"announcements": [{"secName": f"c{i}", "announcementTitle": f"t{i}", "adjunctUrl": f"u{i}.PDF", "announcementTime": 1785513600000} for i in range(10)]}
    monkeypatch.setattr(cninfo, "fetch_announcements_json", lambda **kw: raw)
    items = cninfo.fetch_announcements(limit=3)
    assert len(items) == 3
