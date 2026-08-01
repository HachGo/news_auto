from unittest.mock import patch, MagicMock

from sources import rss


SAMPLE_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Test</title>
<item>
  <title>News A</title>
  <link>https://example.com/a</link>
  <description>hello</description>
  <pubDate>Wed, 30 Jul 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title>News B</title>
  <link>https://example.com/b</link>
  <description>ai ai ai</description>
  <pubDate>Wed, 30 Jul 2026 11:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def _mock_resp(content):
    resp = MagicMock()
    resp.status_code = 200
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_feed_parses_rss():
    with patch("sources.rss.requests.get", return_value=_mock_resp(SAMPLE_RSS)):
        parsed = rss.fetch_feed("https://x")
    assert parsed is not None
    assert len(parsed.entries) == 2


def test_fetch_feed_returns_none_on_failure():
    with patch("sources.rss.requests.get", side_effect=Exception("boom")):
        assert rss.fetch_feed("https://x") is None


def test_fetch_candidates_filters_by_keywords_and_dedup():
    # hours_window 设极大值，避免固定 pubDate 随运行日期被时间窗口过滤
    config = {
        "settings": {"hours_window": 876000},
        "ai_keywords": ["ai"],
        "feeds": [
            {"name": "T", "url": "https://x", "category": "AI 动态",
             "ai_filter": True, "max_items": 10, "section": "ai"},
        ],
    }
    seen = {}
    with patch("sources.rss.requests.get", return_value=_mock_resp(SAMPLE_RSS)):
        cands = rss.fetch_candidates(config, seen)
    # 只有 News B 含 "ai" 关键词通过过滤
    assert len(cands) == 1
    assert cands[0]["title"] == "News B"
    assert cands[0]["section"] == "ai"
