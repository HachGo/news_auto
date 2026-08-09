from datetime import datetime, timezone, timedelta
from common import link_hash, strip_html, entry_time, matches_keywords, is_blocked


def test_link_hash_stable():
    assert link_hash("https://example.com/a") == link_hash("https://example.com/a")
    assert link_hash("https://example.com/a") != link_hash("https://example.com/b")


def test_strip_html_removes_tags_and_unescapes():
    assert strip_html("<p>Hello &amp; <b>world</b></p>") == "Hello & world"


def test_strip_html_collapses_whitespace():
    assert strip_html("  a\n\nb  ") == "a b"


def test_entry_time_parses_published():
    entry = {"published": "Wed, 30 Jul 2026 10:00:00 GMT"}
    dt = entry_time(entry)
    assert dt is not None
    assert dt.year == 2026 and dt.month == 7


def test_entry_time_returns_none_when_no_dates():
    assert entry_time({}) is None


def test_matches_keywords_short_word_boundary():
    # "AI" 不能误匹配 "aid"
    entry = {"title": "Healthcare aid program", "summary": ""}
    assert not matches_keywords(entry, ["AI"])
    entry = {"title": "New AI model released", "summary": ""}
    assert matches_keywords(entry, ["AI"])


def test_matches_keywords_long_substring():
    entry = {"title": "OpenAI announces GPT", "summary": ""}
    assert matches_keywords(entry, ["OpenAI", "transformer"])


def test_is_blocked_taiwan_and_politics():
    assert is_blocked({"title": "台北股市收涨", "summary": ""}, ["台北", "台湾", "politics"])
    assert is_blocked({"title": "Election results", "summary": ""}, ["election", "Taiwan"])
    assert not is_blocked({"title": "New AI chip", "summary": "benchmarks"}, ["Taiwan", "politics"])


def test_is_blocked_xi_jinping():
    kws = ["习近平", "習近平", "Xi Jinping", "习主席", "President Xi"]
    assert is_blocked({"title": "习近平会见外宾", "summary": ""}, kws)
    assert is_blocked({"title": "President Xi visits Europe", "summary": ""}, kws)
    assert is_blocked({"title": "习主席讲话全文", "summary": ""}, kws)
    assert not is_blocked({"title": "芯片行业周报", "summary": ""}, kws)


def test_matches_keywords_chinese_substring():
    entry = {"title": "关注台海局势最新进展", "summary": ""}
    assert matches_keywords(entry, ["台海"])
