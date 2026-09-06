"""生产回归：仅模拟外部服务，实际执行抓取、生成、持久化和首页流程。"""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import common
import fetch_news
from generators import ai, world, market, deep
from sources import cninfo, jin10, rss


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(rss.time, "sleep", lambda _: None)


@pytest.fixture
def repeated_run(tmp_path, monkeypatch):
    config = {
        "settings": {},
        "feeds": [
            {"name": "AI", "url": "https://fixture.invalid/ai", "section": "ai"},
            {"name": "Market", "url": "https://fixture.invalid/market", "section": "market"},
        ],
    }
    ai_entries = [{"title": "Original AI item", "link": "https://fixture.invalid/a"}]
    market_entries = [{"title": "Original market item", "link": "https://fixture.invalid/m"}]
    monkeypatch.setattr(fetch_news, "CONTENT_DIR", tmp_path / "content")
    monkeypatch.setattr(fetch_news, "SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(fetch_news, "load_config", lambda _: config)
    monkeypatch.setattr(fetch_news, "build_llm_client", lambda: None)
    monkeypatch.setattr(rss, "fetch_feed", lambda url: SimpleNamespace(
        entries=ai_entries if url.endswith("/ai") else market_entries))
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: None)
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: [])
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: [])
    today = datetime.now(common.CST).date().isoformat()
    ai_path = tmp_path / "content" / "ai" / f"{today}.md"
    market_path = tmp_path / "content" / "market" / f"{today}.md"
    fetch_news.main()
    assert "Original AI item" in ai_path.read_text()
    assert "Original market item" in market_path.read_text()
    home_first = (tmp_path / "content" / "_index.md").read_bytes()
    seen_first = (tmp_path / "seen.json").read_bytes()
    trend_first = (tmp_path / "data" / "trends" / "daily" / f"{today}.json").read_bytes()
    method_first = (tmp_path / "content" / "method.md").read_bytes()
    ai_entries.append({"title": "New AI item", "link": "https://fixture.invalid/b"})
    fetch_news.main()
    ai_second = ai_path.read_text()
    market_second = market_path.read_text()
    fetch_news.main()
    home_third = (tmp_path / "content" / "_index.md").read_text()
    seen_third = (tmp_path / "seen.json").read_bytes()
    trend_third = (tmp_path / "data" / "trends" / "daily" / f"{today}.json").read_bytes()
    method_third = (tmp_path / "content" / "method.md").read_bytes()
    return (ai_second, market_second, home_third, home_first, seen_first, seen_third,
            trend_first, trend_third, method_first, method_third)


def test_same_day_rerun_keeps_earlier_ai_articles(repeated_run):
    assert "Original AI item" in repeated_run[0]


def test_same_day_rerun_keeps_earlier_market_articles(repeated_run):
    assert "Original market item" in repeated_run[1]


def test_no_new_items_does_not_report_existing_ai_page_as_failed(repeated_run):
    ai_card = repeated_run[2].split('class="section-card section-ai', 1)[1].split("</a>", 1)[0]
    assert "今日生成异常" not in ai_card


def test_same_day_non_forced_rerun_is_byte_stable(repeated_run):
    assert repeated_run[2].encode() == repeated_run[3]
    assert repeated_run[4] == repeated_run[5]
    assert repeated_run[6] == repeated_run[7]
    assert repeated_run[8] == repeated_run[9]


@pytest.mark.parametrize("gen", [ai, world, market, deep])
def test_generators_forward_global_block_keywords(tmp_path, monkeypatch, gen):
    config = {"settings": {}, "ai_keywords": [], "block_keywords": ["Taiwan"], "feeds": []}
    observed = []

    def fetch(section_config, _seen):
        observed.extend(section_config.get("block_keywords", []))
        return []

    monkeypatch.setattr(rss, "fetch_candidates", fetch)
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: None)
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: [])
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: [])
    gen.generate(config, {}, None, "2026-09-05", posts_dir=tmp_path)
    assert observed == ["Taiwan"]


def test_deep_refresh_unescapes_published_link_before_seen_filter(tmp_path, monkeypatch):
    link = "https://fixture.invalid/story?a=1&b=2"
    item = dict(title="Deep story", link=link, summary="analysis", source="Magazine",
                category="经济学人", time=datetime.now(timezone.utc))
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_args, **_kwargs: [item.copy()])
    deep.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path)
    seen = {common.link_hash(link): "2026-09-05T00:00:00+00:00"}

    def refreshed(_config, fetch_seen, **_kwargs):
        assert common.link_hash(link) not in fetch_seen
        return [item.copy()], set()

    monkeypatch.setattr(rss, "fetch_candidates", refreshed)
    deep.generate({}, seen, None, "2026-09-05", posts_dir=tmp_path, force_refresh=True)


def test_filtered_entry_does_not_block_unfiltered_feed(monkeypatch):
    config = common.load_config()
    config["feeds"] = [f for f in config["feeds"] if f["name"].startswith("Hacker News")]
    monkeypatch.setattr(rss, "fetch_feed", lambda _: SimpleNamespace(entries=[
        {"title": "New database release", "link": "https://fixture.invalid/database"}]))
    items = rss.fetch_candidates(config, {})
    assert len(items) == 1
    assert items[0]["source"] == "Hacker News Best"


def test_cninfo_query_at_six_am_includes_today(monkeypatch):
    class Morning(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 5, 6, tzinfo=common.CST).astimezone(tz)

    requests = []
    monkeypatch.setattr(cninfo, "datetime", Morning)
    def response(**kwargs):
        requests.append(kwargs)
        return {"announcements": []}
    monkeypatch.setattr(cninfo, "fetch_announcements_json", response)
    cninfo.fetch_announcements()
    assert requests[0]["se_date"].endswith("~2026-09-05")


def test_cninfo_preserves_beijing_publication_date():
    ts = datetime(2026, 9, 5, 0, tzinfo=common.CST).timestamp() * 1000
    items = cninfo._parse_rows({"announcements": [{"announcementTime": ts}]}, 1)
    assert items[0]["pub_date"] == "2026-09-05"


def client_with(content):
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    return client


def test_llm_string_score_does_not_crash_page_render():
    now = datetime.now(timezone.utc)
    candidates = [dict(title=f"Item {i}", link=f"https://fixture.invalid/{i}",
                       summary="summary", source="S", category="AI 动态", time=now)
                  for i in range(2)]
    client = client_with('{"selected": [{"index": 0, "score": "9"}, {"index": 1, "score": 7}]}')
    selected = common.rank_and_select(client, candidates, {"settings": {"total_limit": 2}})
    markdown = common.render_sectioned(selected, "AI", "Summary")
    assert "Item 0" in markdown


def test_null_llm_summary_is_not_published_as_none():
    result = common.summarize(client_with('{"title_zh": null, "summary_zh": null}'),
                              {"title": "Title", "summary": "Summary"}, retries=0)
    assert result is None


def test_calendar_preserves_numeric_zero():
    items = jin10._parse_jin10([
        {"pub_time": "2026-09-05 06:00:00", "title": "Change",
         "current_actual": 0, "previous": 0, "consensus": 0},
    ], "2026-09-05")
    assert items[0]["actual"] == 0


def test_calendar_renders_numeric_zero():
    markdown = market._render("2026-09-05", None, [
        {"title": "Change", "actual": 0, "previous": 0, "consensus": 0}
    ], [], [], [])
    assert "| Change | 0 | 0 | 0 |" in markdown


def test_market_honors_source_limit(tmp_path, monkeypatch):
    candidates = [dict(title=f"Item {i}", link=f"https://fixture.invalid/{source}/{i}",
                       summary="summary", source=source, category="财经要闻",
                       time=datetime.now(timezone.utc))
                  for source in ("A", "B") for i in range(8)]
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_: candidates)
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: None)
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: [])
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: [])
    result = market.generate({"settings": {"per_source_limit": 4}}, {}, None,
                             "2026-09-05", posts_dir=tmp_path)
    assert sum(i["source"] == "A" for i in result["items"]) <= 4


def test_invalid_primary_calendar_payload_uses_backup(monkeypatch):
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: {"code": 401, "message": "error"})
    expected = [{"title": "Backup event"}]
    monkeypatch.setattr(jin10, "_fetch_forexfactory", lambda _: expected)
    assert jin10.fetch_calendar(date(2026, 9, 5)) == expected


@pytest.mark.parametrize("score", [None, "bad", True, [], {}, "NaN", "Infinity", -1, 11])
def test_invalid_scores_do_not_escape_llm_boundary(score):
    import json
    candidates = [dict(title="News", link="https://fixture.invalid/n", summary="s",
                       source="S", category="AI 动态", time=datetime.now(timezone.utc))]
    client = client_with(json.dumps({"selected": [{"index": 0, "score": score}]}))
    items = common.rank_and_select(client, candidates, {})
    assert items[0]["score"] == 5
    assert "News" in common.render_sectioned(items, "AI", "Summary")


@pytest.mark.parametrize("value", [None, 0, False, [], {}])
def test_invalid_summary_fields_are_rejected(value):
    import json
    payload = json.dumps({"title_zh": "标题", "summary_zh": value})
    assert common.summarize(client_with(payload), {"title": "T", "summary": "S"}, retries=0) is None


def test_zero_survives_forexfactory_parser():
    items = jin10._parse_ff_items([
        {"date": "2026-09-05T06:00:00+08:00", "impact": "High", "title": "Change",
         "actual": 0, "previous": 0, "forecast": 0}
    ], date(2026, 9, 5))
    assert items[0]["actual"] == items[0]["previous"] == items[0]["consensus"] == 0


@pytest.mark.parametrize("payload", [{}, "error", [None], [{"pub_time": 123}]])
def test_malformed_calendar_uses_backup(monkeypatch, payload):
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: payload)
    expected = [{"title": "Backup"}]
    monkeypatch.setattr(jin10, "_fetch_forexfactory", lambda _: expected)
    assert jin10.fetch_calendar(date(2026, 9, 5)) == expected


@pytest.mark.parametrize("gen", [ai, world, market, deep])
def test_repeated_generation_preserves_file_and_items(tmp_path, monkeypatch, gen):
    now = datetime.now(timezone.utc)
    candidates = [dict(title="Published news", link="https://fixture.invalid/news", summary="s",
                       source="S", category=("财经要闻" if gen is market else
                                              "经济学人" if gen is deep else "国际新闻"), time=now)]
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_: candidates)
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: None)
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: [])
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: [])
    first = gen.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path)
    original = first["path"].read_bytes()
    # 同日报纸已发布后，外部服务不可用也必须能够复用。
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_: (_ for _ in ()).throw(RuntimeError("offline")))
    second = gen.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path)
    assert second["path"].read_bytes() == original
    assert second["items"][0]["title"] == "Published news"
    assert second["items"][0]["link"] == "https://fixture.invalid/news"


def test_reused_market_keeps_research_and_quote_focus(tmp_path, monkeypatch):
    research = dict(title="Research", link="https://fixture.invalid/research", summary="s",
                    source="R", category="研报要点", time=datetime.now(timezone.utc))
    quotes = [{"name": "上证指数", "price": 3000.50, "change_pct": -1.25}]
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_: [research])
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: quotes)
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: [])
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: [])
    market.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path)
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_: [])
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: None)
    again = market.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path)
    assert again["items"] == []
    assert again["all_rss_items"][0]["link"] == research["link"]
    assert again["quotes"][0]["change_pct"] == -1.25


@pytest.mark.parametrize("gen", [ai, world, market, deep])
def test_forced_refresh_overwrites_today_and_reconsiders_its_links(tmp_path, monkeypatch, gen):
    now = datetime.now(timezone.utc)
    category = "财经要闻" if gen is market else "经济学人" if gen is deep else "国际新闻"
    old = dict(title="Old news", link="https://fixture.invalid/old", summary="old",
               source="S", category=category, time=now)
    latest = dict(title="Latest news", link="https://fixture.invalid/latest", summary="latest",
                  source="S", category=category, time=now)
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_: [old.copy()])
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: None)
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: [])
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: [])
    gen.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path)

    unrelated_link = "https://fixture.invalid/previous-day"
    seen = {
        common.link_hash(old["link"]): "2026-09-05T00:00:00+00:00",
        common.link_hash(unrelated_link): "2026-09-04T00:00:00+00:00",
    }

    def refreshed(_config, fetch_seen, return_failures=False, **_kwargs):
        assert return_failures
        assert common.link_hash(old["link"]) not in fetch_seen
        assert common.link_hash(unrelated_link) in fetch_seen
        return [latest.copy()], set()

    monkeypatch.setattr(rss, "fetch_candidates", refreshed)
    result = gen.generate({}, seen, None, "2026-09-05", posts_dir=tmp_path,
                          force_refresh=True)
    markdown = result["path"].read_text(encoding="utf-8")
    assert "Latest news" in markdown
    assert "Old news" not in markdown
    assert common.link_hash(old["link"]) in seen


@pytest.mark.parametrize("gen", [ai, world, market, deep])
def test_failed_forced_refresh_keeps_existing_daily_report(tmp_path, monkeypatch, gen):
    item = dict(title="Published news", link="https://fixture.invalid/news", summary="s",
                source="S", category=("财经要闻" if gen is market else
                                       "经济学人" if gen is deep else "国际新闻"),
                time=datetime.now(timezone.utc))
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_: [item.copy()])
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: None)
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: [])
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: [])
    first = gen.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path)
    before = first["path"].read_bytes()

    monkeypatch.setattr(rss, "fetch_candidates", lambda *_args, **_kwargs: ([], set()))
    second = gen.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path,
                          force_refresh=True)
    assert second["path"].read_bytes() == before
    assert second["items"][0]["link"] == item["link"]


@pytest.mark.parametrize("gen", [ai, world, market, deep])
def test_partial_feed_failure_preserves_failed_source_articles(tmp_path, monkeypatch, gen):
    now = datetime.now(timezone.utc)
    category = "财经要闻" if gen is market else "经济学人" if gen is deep else "国际新闻"
    old_a = dict(title="Old A", link="https://fixture.invalid/old-a", summary="a",
                 source="A", category=category, time=now)
    old_b = dict(title="Old B", link="https://fixture.invalid/old-b", summary="b",
                 source="B", category=category, time=now)
    latest_a = dict(title="Latest A", link="https://fixture.invalid/latest-a", summary="new",
                    source="A", category=category, time=now)
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_args, **_kwargs: [old_a.copy(), old_b.copy()])
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: None)
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: [])
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: [])
    gen.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path)

    def partial(_config, _seen, return_failures=False, **_kwargs):
        assert return_failures
        return [latest_a.copy()], {"B"}

    monkeypatch.setattr(rss, "fetch_candidates", partial)
    result = gen.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path,
                          force_refresh=True)
    links = {item["link"] for item in result["all_rss_items"]}
    assert latest_a["link"] in links
    assert old_b["link"] in links
    assert old_a["link"] not in links


def test_market_refresh_reuses_successful_old_subsections_when_apis_fail(tmp_path, monkeypatch):
    old = dict(title="Old news", link="https://fixture.invalid/old", summary="old",
               source="A", category="财经要闻", time=datetime.now(timezone.utc))
    latest = dict(title="Latest news", link="https://fixture.invalid/latest", summary="latest",
                  source="A", category="财经要闻", time=datetime.now(timezone.utc))
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_args, **_kwargs: [old.copy()])
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: [
        {"name": "上证指数", "price": 3210.5, "change_pct": 0.75},
    ])
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: [
        {"title": "中国 CPI", "consensus": 1.0, "previous": 0.8, "actual": 1.1},
    ])
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: [
        {"sec_name": "示例公司", "title": "年度报告", "url": "https://fixture.invalid/report"},
    ])
    market.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path)

    monkeypatch.setattr(rss, "fetch_candidates", lambda *_args, **_kwargs: ([latest.copy()], set()))
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: (_ for _ in ()).throw(RuntimeError("offline")))
    result = market.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path,
                             force_refresh=True)
    markdown = result["path"].read_text(encoding="utf-8")
    assert "上证指数" in markdown
    assert "中国 CPI" in markdown
    assert "示例公司" in markdown
    assert "Latest news" in markdown
    assert market.FAIL_BLOCK not in markdown


def test_partial_research_feed_failure_preserves_old_research(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    old_research = dict(
        title="Old research", link="https://fixture.invalid/old-research", summary="analysis",
        source="Research", category="研报要点", time=now,
    )
    latest_news = dict(
        title="Latest news", link="https://fixture.invalid/latest-news", summary="news",
        source="News", category="财经要闻", time=now,
    )
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_args, **_kwargs: [old_research.copy()])
    monkeypatch.setattr(market.eastmoney, "fetch_quotes", lambda: None)
    monkeypatch.setattr(jin10, "fetch_calendar", lambda _: [])
    monkeypatch.setattr(cninfo, "fetch_announcements", lambda **_: [])
    market.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path)

    def partial(_config, _seen, return_failures=False, **_kwargs):
        assert return_failures
        return [latest_news.copy()], {"Research"}

    monkeypatch.setattr(rss, "fetch_candidates", partial)
    result = market.generate({}, {}, None, "2026-09-05", posts_dir=tmp_path,
                             force_refresh=True)
    research = [
        item for item in result["all_rss_items"] if item["category"] == "研报要点"
    ]
    assert [item["link"] for item in research] == [old_research["link"]]


@pytest.mark.parametrize("gen", [ai, world, deep])
def test_total_summary_failure_is_not_reported_as_empty(tmp_path, monkeypatch, gen):
    candidates = [dict(title="News", link="https://fixture.invalid/n", summary="s", source="S",
                       category="经济学人" if gen is deep else "国际新闻",
                       time=datetime.now(timezone.utc))]
    monkeypatch.setattr(rss, "fetch_candidates", lambda *_: candidates)
    client = client_with('{"selected": [{"index": 0, "score": 9}]}')
    with pytest.raises(RuntimeError, match="LLM"):
        gen.generate({}, {}, client, "2026-09-05", posts_dir=tmp_path)
    assert not (tmp_path / "2026-09-05.md").exists()


def test_homepage_distinguishes_empty_from_failed():
    from homepage import build_homepage
    sections = {
        "ai": {"name": "AI 与科技社区", "url": "/ai/2026-09-05/",
               "status": "empty", "items": [], "count": 0},
        "world": None,
    }
    markdown = build_homepage(sections, "2026-09-05")
    ai_card = markdown.split('class="section-card section-ai', 1)[1].split("</a>", 1)[0]
    world_card = markdown.split('class="section-card section-world', 1)[1].split("</a>", 1)[0]
    assert "今日暂无新条目" in ai_card
    assert "查看全文" not in ai_card
    assert "今日生成异常" in world_card
