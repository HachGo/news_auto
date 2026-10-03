"""中英文内容：模型英文字段、英文版页面渲染、与中文版共享条目锚点。"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from common import item_id, render_deep, render_item, render_sectioned, summarize, translate_lines
from generators import market
from published import load_published_post


def _client_returning(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = resp
    return client


def test_summarize_returns_english_fields_and_importance():
    client = _client_returning(
        '{"title_zh": "中文标题", "summary_zh": "中文摘要", "title_en": "English title",'
        ' "summary_en": "English summary.", "importance": 8}'
    )
    out = summarize(client, {"title": "x", "summary": "y"})
    assert out == {"title_zh": "中文标题", "summary_zh": "中文摘要", "title_en": "English title",
                   "summary_en": "English summary.", "importance": 8}


def test_summarize_drops_invalid_english_fields():
    client = _client_returning('{"title_zh": "中文标题", "summary_zh": "中文摘要", "title_en": 3, "summary_en": " "}')
    assert summarize(client, {"title": "x", "summary": "y"}) == {"title_zh": "中文标题", "summary_zh": "中文摘要"}


def test_translate_lines_requires_matching_count():
    assert translate_lines(_client_returning('{"lines": ["CPI", "PPI"]}'), ["消费者物价指数", "生产者物价指数"]) == ["CPI", "PPI"]
    with patch("common.time.sleep"):
        assert translate_lines(_client_returning('{"lines": ["CPI"]}'), ["一", "二"]) is None
    assert translate_lines(None, ["一"]) is None


ITEM = {"title": "Model launch", "title_zh": "模型发布", "summary_zh": "中文摘要",
        "summary_en": "English summary.", "source": "S", "link": "https://x/1", "score": 9}


def test_zh_and_en_items_share_heading_anchor():
    anchor = "{#" + item_id(ITEM) + "}"
    zh = render_item(ITEM, 1)
    en = render_item(ITEM, 1, lang="en")
    assert zh[0] == f"### 1. 【重点】模型发布 {anchor}"
    assert en[0] == f"### 1. Model launch {anchor}"
    assert "English summary." in en and "Source: [S](https://x/1)" in en
    assert "> Model launch" in zh and "来源：[S](https://x/1)" in zh


def test_english_item_without_model_output_uses_original_title_only():
    item = {"title": "原标题", "summary": "中文 RSS 摘要", "source": "S", "link": "https://x/2"}
    en = render_item(item, 2, lang="en")
    assert en[0].startswith("### 2. 原标题 {#i-")
    assert "中文 RSS 摘要" not in en


def test_render_sectioned_english_headings():
    items = [dict(ITEM, category="AI 动态"), dict(ITEM, link="https://x/3", category="社区热点", score=5)]
    out = render_sectioned(items, "AI & Tech 2026-09-05", "2 AI stories.", focus_count=1, lang="en")
    assert 'tags: ["Daily brief"]' in out
    assert "## Top stories" in out and "## Community picks" in out
    assert "今日焦点" not in out


def test_render_deep_english():
    items = [dict(ITEM, category="经济学人"), dict(ITEM, link="https://x/4", category="科学美国人")]
    out = render_deep(items, "Deep reads 2026-09-05", "2 long reads.", lang="en")
    assert "## Today's picks" in out and "## By publication" in out
    assert "### The Economist" in out and "deep-dek" not in out
    assert 'target="_blank" rel="noopener"' in out


def test_market_english_page_translates_labels_and_quotes():
    quotes = [{"name": "上证指数", "price": 3930.12, "change_pct": -0.3, "amount": 9.383e11}]
    news = [{"title": "央行降准", "title_zh": "央行降准", "title_en": "PBOC cuts RRR", "summary_en": "Cut.",
             "source": "第一财经", "link": "https://m/1"}]
    out = market._render("2026-09-05", quotes, [], [], news, [], lang="en")
    assert 'title: "Finance 2026-09-05"' in out
    assert "| SSE Composite | 3930.12 | ▼0.30% |" in out
    assert "Shanghai turnover: CNY 938.3bn" in out
    assert "## Finance news" in out and "### 1. PBOC cuts RRR {#" in out
    zh = market._render("2026-09-05", quotes, [], [], news, [])
    assert "| 上证指数 | 3930.12 | ▼0.30% |" in zh and "沪市成交额：9383 亿元" in zh


def test_published_reader_strips_anchor_and_recovers_original_title(tmp_path):
    path = tmp_path / "2026-09-05.md"
    path.write_text(render_sectioned([dict(ITEM, category="AI 动态")], "AI与科技 2026-09-05", "1 条"),
                    encoding="utf-8")
    item = load_published_post(path, "ai")["items"][0]
    assert item["title"] == "Model launch"
    assert item["title_zh"] == "模型发布"
    assert item["link"] == "https://x/1"
    assert item_id(item) == item_id(ITEM)
