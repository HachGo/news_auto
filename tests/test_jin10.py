import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from sources import jin10

FIX = Path(__file__).parent / "fixtures" / "jin10_calendar.json"


def test_parse_calendar_filters_today(monkeypatch):
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: raw)
    items = jin10.fetch_calendar(date(2026, 7, 31))
    assert len(items) >= 1
    assert items[0]["title"] == "7月制造业PMI"
    assert items[0]["actual"] == "49.4"


def test_fetch_calendar_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: None)
    assert jin10.fetch_calendar(date(2026, 7, 31)) is None


def test_fetch_calendar_empty_returns_empty_list(monkeypatch):
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: [])
    assert jin10.fetch_calendar(date(2026, 7, 31)) == []
