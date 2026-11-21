import threading
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
    with patch("sources.rss.requests.get", side_effect=Exception("boom")), \
         patch("sources.rss.time.sleep"):
        assert rss.fetch_feed("https://x") is None


def test_fetch_candidates_filters_by_keywords_and_dedup():
    # hours_window 设极大值，避免固定 pubDate 随运行日期被时间窗口过滤
    config = {
        "settings": {"hours_window": 876000},
        "ai_keywords": ["ai"],
        "block_keywords": [],
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


BLOCK_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Test</title>
<item>
  <title>Taiwan election update</title>
  <link>https://example.com/tw</link>
  <description>politics</description>
  <pubDate>Wed, 30 Jul 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title>New chip breakthrough</title>
  <link>https://example.com/chip</link>
  <description>semiconductor research</description>
  <pubDate>Wed, 30 Jul 2026 11:00:00 GMT</pubDate>
</item>
<item>
  <title>白宫宣布新外交政策</title>
  <link>https://example.com/cn</link>
  <description>涉及制裁</description>
  <pubDate>Wed, 30 Jul 2026 12:00:00 GMT</pubDate>
</item>
</channel></rss>""".encode("utf-8")


def test_fetch_candidates_applies_block_keywords():
    config = {
        "settings": {"hours_window": 876000},
        "ai_keywords": [],
        "block_keywords": ["Taiwan", "politics", "白宫", "制裁", "外交"],
        "feeds": [
            {"name": "T", "url": "https://x", "category": "国际新闻",
             "ai_filter": False, "max_items": 10, "section": "world"},
        ],
    }
    with patch("sources.rss.requests.get", return_value=_mock_resp(BLOCK_RSS)):
        cands = rss.fetch_candidates(config, {})
    assert len(cands) == 1
    assert cands[0]["title"] == "New chip breakthrough"


def test_empty_feed_is_reported_as_failed_during_protected_refresh():
    config = {
        "settings": {},
        "feeds": [{"name": "T", "url": "https://x", "section": "ai"}],
    }
    with patch("sources.rss.fetch_feed", return_value=MagicMock(entries=[], bozo=False)):
        candidates, failures = rss.fetch_candidates(
            config, {}, return_failures=True, empty_is_failure=True,
        )
    assert candidates == []
    assert failures == {"T"}


def test_malformed_empty_feed_is_reported_as_failed():
    config = {
        "settings": {},
        "feeds": [{"name": "T", "url": "https://x", "section": "ai"}],
    }
    with patch("sources.rss.fetch_feed", return_value=MagicMock(entries=[], bozo=True)):
        candidates, failures = rss.fetch_candidates(config, {}, return_failures=True)
    assert candidates == []
    assert failures == {"T"}


# ---- 并发抓取 ----

def _feed(name, host="example.test"):
    return {"name": name, "url": f"https://{host}/{name}", "section": "ai",
            "category": "AI 动态", "max_items": 10}


def _entry(name):
    return {"title": name, "link": f"https://example.com/{name}", "summary": "s",
            "published": "Wed, 30 Jul 2026 10:00:00 GMT"}


def test_feeds_are_fetched_concurrently():
    """两个源必须同时在飞，否则 24 个源又要串行等 2 秒×N。"""
    barrier = threading.Barrier(2, timeout=5)
    errors = []

    def fake_fetch(url):
        try:
            barrier.wait()  # 串行执行时第二个源永远到不了，这里会超时
        except threading.BrokenBarrierError as exc:
            errors.append(exc)
        return MagicMock(entries=[], bozo=False)

    config = {"settings": {"hours_window": 876000}, "ai_keywords": [], "block_keywords": [],
              "feeds": [_feed("a", "a.test"), _feed("b", "b.test")]}
    with patch("sources.rss.fetch_feed", side_effect=fake_fetch):
        rss.fetch_candidates(config, {})

    assert errors == []


def test_candidates_keep_feed_order_when_responses_arrive_out_of_order():
    import time as _time

    def fake_fetch(url):
        _time.sleep(0.05 if url.endswith("/a") else 0)  # a 慢、b 快
        name = url.rsplit("/", 1)[-1]
        return MagicMock(entries=[_entry(name)], bozo=False)

    config = {"settings": {"hours_window": 876000}, "ai_keywords": [], "block_keywords": [],
              "feeds": [_feed("a", "a.test"), _feed("b", "b.test")]}
    with patch("sources.rss.fetch_feed", side_effect=fake_fetch):
        candidates = rss.fetch_candidates(config, {})

    assert [c["source"] for c in candidates] == ["a", "b"]


def test_same_host_requests_are_spaced_but_other_hosts_are_not(monkeypatch):
    sleeps = []
    monkeypatch.setattr(rss.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(rss.time, "sleep", sleeps.append)
    slots = {}

    rss._reserve_host_slot(slots, "https://a.test/1", 2.0)
    assert sleeps == []                       # 同源首次不等待

    rss._reserve_host_slot(slots, "https://a.test/2", 2.0)
    assert sleeps and sleeps[0] > 0           # 同源第二次要排队

    sleeps.clear()
    rss._reserve_host_slot(slots, "https://b.test/1", 2.0)
    assert sleeps == []                       # 不同源互不影响


def test_host_interval_can_be_disabled(monkeypatch):
    sleeps = []
    monkeypatch.setattr(rss.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(rss.time, "sleep", sleeps.append)
    slots = {}

    rss._reserve_host_slot(slots, "https://a.test/1", 0)
    rss._reserve_host_slot(slots, "https://a.test/2", 0)

    assert sleeps == []


def test_worker_exception_is_treated_as_failed_source():
    config = {"settings": {}, "feeds": [_feed("a", "a.test")]}
    with patch.object(rss, "_fetch_one", side_effect=RuntimeError("boom")):
        candidates, failures = rss.fetch_candidates(config, {}, return_failures=True)
    assert candidates == []
    assert failures == {"a"}
