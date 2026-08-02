import json
from datetime import date
from pathlib import Path

from sources import jin10

FIX = Path(__file__).parent / "fixtures" / "jin10_calendar.json"
FIX_FF = Path(__file__).parent / "fixtures" / "forexfactory_calendar.json"


def test_parse_calendar_filters_today(monkeypatch):
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: raw)
    items = jin10.fetch_calendar(date(2026, 7, 31))
    assert len(items) >= 1
    assert items[0]["title"] == "7月制造业PMI"
    assert items[0]["actual"] == "49.4"


def test_fetch_calendar_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: None)
    monkeypatch.setattr(jin10, "_fetch_forexfactory", lambda today: None)
    assert jin10.fetch_calendar(date(2026, 7, 31)) is None


def test_fetch_calendar_empty_returns_empty_list(monkeypatch):
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: [])
    assert jin10.fetch_calendar(date(2026, 7, 31)) == []


def test_forexfactory_fallback(monkeypatch):
    raw = json.loads(FIX_FF.read_text(encoding="utf-8"))
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: None)
    monkeypatch.setattr(jin10, "_fetch_forexfactory", lambda today: jin10._parse_ff_items(raw, today))
    items = jin10.fetch_calendar(date(2026, 7, 31))
    assert len(items) == 1  # Low impact + other day filtered out
    assert "CPI" in items[0]["title"]
    assert items[0]["consensus"] == "0.2%"
    assert items[0]["actual"] == "0.2%"
