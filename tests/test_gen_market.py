from unittest.mock import patch, MagicMock

from generators import market


def _client(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = resp
    return client


def test_generate_renders_all_four_blocks(tmp_path):
    from datetime import date
    config = {"settings": {"hours_window": 240, "total_limit": 5, "per_source_limit": 4},
              "ai_keywords": [], "feeds": [{"name": "T", "url": "x", "section": "market",
              "category": "财经要闻", "ai_filter": False, "max_items": 5}]}
    candidates = [{"title": "央行降准", "link": "l", "summary": "s", "source": "T",
                   "category": "财经要闻", "section": "market", "time": None}]
    quotes = [{"name": "上证指数", "price": 3225.43, "change_pct": 0.82, "amount": 8e11}]
    calendar = [{"title": "7月PMI", "actual": "49.4", "previous": "49.5", "consensus": "49.5", "country": "中国"}]
    announces = [{"sec_code": "600641", "sec_name": "先导基电", "title": "年报", "url": "http://x/a.PDF", "pub_date": "2026-08-01"}]

    with patch("generators.market.rss.fetch_candidates", return_value=candidates), \
         patch("generators.market.summarize", return_value={"title_zh": "央行降准", "summary_zh": "摘要"}), \
         patch("generators.market.eastmoney.fetch_quotes", return_value=quotes), \
         patch("generators.market.jin10.fetch_calendar", return_value=calendar), \
         patch("generators.market.cninfo.fetch_announcements", return_value=announces):
        result = market.generate(config, {}, _client('{}'), date_str="2026-08-01", posts_dir=tmp_path)
    assert result["path"].exists()
    text = result["path"].read_text(encoding="utf-8")
    assert "行情速览" in text
    assert "上证指数" in text
    assert "宏观与政策" in text
    assert "7月PMI" in text
    assert "财经要闻" in text
    assert "公告" in text or "研报" in text


def test_generate_handles_source_failures(tmp_path):
    from datetime import date
    config = {"settings": {"hours_window": 240, "total_limit": 5, "per_source_limit": 4},
              "ai_keywords": [], "feeds": []}
    # 三个抓取源都失败返回 None，财经要闻也无
    with patch("generators.market.rss.fetch_candidates", return_value=[]), \
         patch("generators.market.eastmoney.fetch_quotes", return_value=None), \
         patch("generators.market.jin10.fetch_calendar", return_value=None), \
         patch("generators.market.cninfo.fetch_announcements", return_value=None):
        result = market.generate(config, {}, None, date_str="2026-08-01", posts_dir=tmp_path)
    # 全失败也应有占位文章
    assert result["path"].exists()
    text = result["path"].read_text(encoding="utf-8")
    assert "数据获取失败" in text
