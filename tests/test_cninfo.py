import json
from pathlib import Path

from sources import cninfo

FIX = Path(__file__).parent / "fixtures" / "cninfo_announcements.json"


def test_parse_announcements(monkeypatch):
    raw = json.loads(FIX.read_text(encoding="utf-8"))

    def fake_json(**kw):
        return raw

    monkeypatch.setattr(cninfo, "fetch_announcements_json", fake_json)
    items = cninfo.fetch_announcements(limit=5)
    assert len(items) >= 1
    assert items[0]["sec_name"] == "先导基电"
    assert "年度报告" in items[0]["title"]
    assert items[0]["url"].endswith(".PDF")


def test_fetch_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(cninfo, "fetch_announcements_json", lambda **kw: None)
    assert cninfo.fetch_announcements() is None


def test_fetch_respects_limit(monkeypatch):
    raw = {
        "announcements": [
            {
                "secCode": f"{i}",
                "secName": f"c{i}",
                "announcementTitle": f"t{i}",
                "adjunctUrl": f"u{i}.PDF",
                "announcementTime": 1785513600000 + i,
            }
            for i in range(10)
        ]
    }
    monkeypatch.setattr(cninfo, "fetch_announcements_json", lambda **kw: raw)
    items = cninfo.fetch_announcements(limit=3)
    assert len(items) == 3


def test_merges_categories_dedupes(monkeypatch):
    calls = []

    def fake_json(**kw):
        calls.append(kw.get("category"))
        return {
            "announcements": [
                {
                    "secCode": "1",
                    "secName": "A",
                    "announcementTitle": "同一标题",
                    "adjunctUrl": "a.PDF",
                    "announcementTime": 1785513600000,
                },
                {
                    "secCode": "2",
                    "secName": "B",
                    "announcementTitle": kw.get("category"),
                    "adjunctUrl": "b.PDF",
                    "announcementTime": 1785513600001,
                },
            ]
        }

    monkeypatch.setattr(cninfo, "fetch_announcements_json", fake_json)
    items = cninfo.fetch_announcements(limit=10)
    assert len(calls) == len(cninfo.CATEGORIES)
    titles = [i["title"] for i in items]
    assert titles.count("同一标题") == 1
    assert len(items) >= 2
