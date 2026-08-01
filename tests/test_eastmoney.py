import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from sources import eastmoney

FIX = Path(__file__).parent / "fixtures" / "eastmoney_sh.json"


def _mock_resp(content):
    resp = MagicMock()
    resp.status_code = 200
    resp.content = content.encode() if isinstance(content, str) else content
    resp.raise_for_status = MagicMock()
    return resp


def test_parse_sh_index():
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    item = eastmoney._parse_one(raw, "上证指数")
    assert item["name"] == "上证指数"
    assert item["price"] == 3832.26  # f43/100
    assert item["change_pct"] == 0.72  # f170/100
    assert item["amount"] == 1187681546393.3  # f48 成交额


def test_fetch_quotes_returns_list(monkeypatch):
    # 用 fixture 替代网络
    raw = FIX.read_bytes()
    monkeypatch.setattr(eastmoney, "fetch_feed_json", lambda url: json.loads(raw))
    quotes = eastmoney.fetch_quotes()
    assert isinstance(quotes, list)
    assert quotes[0]["price"] > 0


def test_fetch_quotes_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(eastmoney, "fetch_feed_json", lambda url: None)
    assert eastmoney.fetch_quotes() is None


def test_fetch_quotes_partial_failure(monkeypatch):
    # 上证成功，其余失败：部分成功应返回只含成功的列表，不整体失败
    raw = json.loads(FIX.read_bytes())

    def fake_json(url):
        if "1.000001" in url:  # 上证 secid
            return raw
        return None

    monkeypatch.setattr(eastmoney, "fetch_feed_json", fake_json)
    quotes = eastmoney.fetch_quotes()
    assert isinstance(quotes, list)
    assert len(quotes) == 1
    assert quotes[0]["name"] == "上证指数"
