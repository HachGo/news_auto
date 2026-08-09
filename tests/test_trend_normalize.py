from trends.deduplicate import cluster_news
from trends.normalize import canonical_url, classify_topics, normalize_news, normalize_quote


def test_canonical_url_removes_fragment_and_trailing_slash():
    assert canonical_url("HTTPS://Example.com/story/#part") == "https://example.com/story"


def test_classify_topics_handles_multiple_topics():
    topics = classify_topics("Open source GPU data center funding")
    assert "open_source" in topics
    assert "chips_compute" in topics
    assert "funding_ma" in topics


def test_normalize_news_bounds_untrusted_values():
    item = normalize_news({"title": "AI", "source": "Reddit", "score": 99, "novelty": "bad"}, "ai", "2026-08-09T00:00:00+00:00")
    assert item["importance"] == 10
    assert item["novelty"] == 1
    assert item["topics"]


def test_cluster_news_keeps_one_representative_and_counts_sources():
    first = normalize_news({"title": "AI chip funding announced", "source": "A", "link": "https://a.example/1", "score": 6}, "ai", "2026-08-09T00:00:00+00:00")
    second = normalize_news({"title": "AI chip funding announced", "source": "B", "link": "https://b.example/1", "score": 8}, "market", "2026-08-09T00:00:00+00:00")
    result = cluster_news([first, second])
    assert len(result) == 1
    assert result[0]["corroborating_sources"] == 2


def test_normalize_quote_preserves_trading_date():
    quote = normalize_quote({"name": "上证指数", "price": 1, "change_pct": 2, "trading_date": "2026-08-08"}, "2026-08-09")
    assert quote["trading_date"] == "2026-08-08"
    assert quote["market"] == "CN"
