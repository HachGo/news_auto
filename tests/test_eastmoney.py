import json
from pathlib import Path
from unittest.mock import MagicMock

from sources import eastmoney

FIX = Path(__file__).parent / "fixtures" / "eastmoney_sh.json"
FIX_ULIST = Path(__file__).parent / "fixtures" / "eastmoney_ulist.json"


def test_parse_sh_index():
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    item = eastmoney._parse_one(raw, "上证指数")
    assert item["name"] == "上证指数"
    assert item["price"] == 3832.26  # f43/100
    assert item["change_pct"] == 0.72  # f170/100
    assert item["amount"] == 1187681546393.3  # f48 成交额


def test_fetch_quotes_from_ulist(monkeypatch):
    raw = json.loads(FIX_ULIST.read_text(encoding="utf-8"))
    monkeypatch.setattr(eastmoney, "fetch_feed_json", lambda url, retries=3: raw)
    monkeypatch.setattr(eastmoney, "_fetch_sina_quotes", lambda: [])
    monkeypatch.setattr(eastmoney, "_fetch_yahoo_quotes", lambda: [])
    quotes = eastmoney.fetch_quotes()
    assert isinstance(quotes, list)
    assert len(quotes) >= 3
    names = {q["name"] for q in quotes}
    assert "上证指数" in names
    assert quotes[0]["price"] > 0


def test_fetch_quotes_sina_fallback(monkeypatch):
    monkeypatch.setattr(eastmoney, "_fetch_eastmoney_batch", lambda: [])
    monkeypatch.setattr(
        eastmoney,
        "_fetch_sina_quotes",
        lambda: [{"name": "上证指数", "price": 3800.0, "change_pct": 1.2, "amount": 1e12}],
    )
    monkeypatch.setattr(eastmoney, "_fetch_yahoo_quotes", lambda: [])
    quotes = eastmoney.fetch_quotes()
    assert len(quotes) == 1
    assert quotes[0]["name"] == "上证指数"


def test_fetch_quotes_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(eastmoney, "_fetch_eastmoney_batch", lambda: [])
    monkeypatch.setattr(eastmoney, "_fetch_sina_quotes", lambda: [])
    monkeypatch.setattr(eastmoney, "_fetch_yahoo_quotes", lambda: [])
    assert eastmoney.fetch_quotes() is None


def test_fetch_quotes_partial_then_fill(monkeypatch):
    monkeypatch.setattr(
        eastmoney,
        "_fetch_eastmoney_batch",
        lambda: [{"name": "上证指数", "price": 3832.26, "change_pct": 0.72, "amount": 1e12}],
    )
    monkeypatch.setattr(
        eastmoney,
        "_fetch_sina_quotes",
        lambda: [{"name": "VIX", "price": 16.0, "change_pct": -1.0, "amount": None}],
    )
    monkeypatch.setattr(
        eastmoney,
        "_fetch_yahoo_quotes",
        lambda: [{"name": "VIX", "price": 15.99, "change_pct": -6.4, "amount": None}],
    )
    quotes = eastmoney.fetch_quotes()
    names = [q["name"] for q in quotes]
    assert names[0] == "上证指数"
    # sina 先补上 VIX，yahoo 不再覆盖已有
    assert "VIX" in names
    assert quotes[names.index("VIX")]["price"] == 16.0


def test_parse_sina_s_fields():
    fields = "上证指数,3832.2624,27.5698,0.72,5975294,118768155".split(",")
    item = eastmoney._parse_sina_fields("上证指数", fields, "s")
    assert item["price"] == 3832.2624
    assert item["change_pct"] == 0.72
    assert abs(item["amount"] - 1187681550000) < 1
