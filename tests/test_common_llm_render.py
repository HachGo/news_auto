from unittest.mock import MagicMock

from common import summarize, rank_and_select, select_deep, render_item, render_sectioned


def _client_returning(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = resp
    return client


def test_summarize_returns_zh_fields():
    client = _client_returning('{"title_zh": "中文标题", "summary_zh": "中文摘要"}')
    out = summarize(client, {"title": "x", "summary": "y"})
    assert out == {"title_zh": "中文标题", "summary_zh": "中文摘要"}


def test_summarize_returns_none_on_bad_json():
    client = _client_returning("not json")
    assert summarize(client, {"title": "x", "summary": "y"}) is None


def test_summarize_returns_none_when_no_client():
    assert summarize(None, {"title": "x", "summary": "y"}) is None


def test_rank_and_select_uses_llm_indices():
    cands = [
        {"title": f"t{i}", "link": f"l{i}", "summary": "s", "source": "S",
         "category": "AI 动态", "time": None} for i in range(5)
    ]
    client = _client_returning('{"selected": [{"index": 2, "score": 9}, {"index": 0, "score": 7}]}')
    picked = rank_and_select(client, cands, {"settings": {"total_limit": 2}})
    assert len(picked) == 2
    assert picked[0]["score"] == 9
    assert picked[0]["title"] == "t2"


def test_rank_and_select_fallback_when_no_client():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    cands = [
        {"title": f"t{i}", "link": f"l{i}", "summary": "s", "source": "S",
         "category": "AI 动态", "time": now} for i in range(5)
    ]
    picked = rank_and_select(None, cands, {"settings": {"total_limit": 2, "per_source_limit": 4}})
    assert len(picked) == 2


def test_select_deep_balances_sources():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    cands = [
        {"title": "a1", "source": "A", "category": "深度精选", "time": now},
        {"title": "a2", "source": "A", "category": "深度精选", "time": now},
        {"title": "b1", "source": "B", "category": "深度精选", "time": now},
    ]
    picked = select_deep(cands, {"settings": {"deep_limit": 3, "deep_per_source_limit": 1}})
    sources = [p["source"] for p in picked]
    assert sources.count("A") == 1
    assert sources.count("B") == 1


def test_render_item_with_zh_title():
    item = {"title_zh": "中文", "title": "Eng", "summary_zh": "摘要", "source": "S", "link": "https://x"}
    block = render_item(item, 1)
    assert "1. 中文" in block[0]
    assert "> Eng" in block
    assert "来源：[S](https://x)" in block


def test_render_item_highlights_high_score():
    item = {"title": "Eng", "summary": "s", "source": "S", "link": "https://x", "score": 9}
    block = render_item(item, 1)
    assert "【重点】" in block[0]


def test_render_sectioned_has_focus_and_categories():
    # 3 条目、focus_count=1：1 条进焦点区，2 条进分类区，两个分类标题都会出现
    items = [
        {"title_zh": "焦点", "title": "e1", "summary_zh": "s", "source": "S", "link": "l1",
         "category": "国际新闻", "score": 9},
        {"title_zh": "AI条", "title": "e2", "summary_zh": "s", "source": "S", "link": "l2",
         "category": "AI 动态", "score": 5},
        {"title_zh": "社区条", "title": "e3", "summary_zh": "s", "source": "S", "link": "l3",
         "category": "社区热点", "score": 3},
    ]
    out = render_sectioned(items, "每日资讯 2026-08-01", summary="今日 3 条", focus_count=1)
    assert "今日焦点" in out
    assert "AI 动态" in out
    assert "社区热点" in out
