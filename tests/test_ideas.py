import json
from datetime import datetime, timezone

import pytest

import ideas
from sources.ideas import github, hackaday, show_hn, sspai, v2ex

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def raw(source, native, title, signals, url=None, summary="", published="2026-10-03T00:00:00+00:00"):
    return {"id": f"{source}:{native}", "source": source, "url": url or f"https://{source}.test/{native}",
            "title": title, "summary": summary, "lang": "en", "published_at": published, "signals": signals}


class Stub:
    NAME = "Stub"
    ACCESS = "API"

    def __init__(self, items=None, error=None):
        self.items, self.error = items or [], error

    def fetch(self, limit=30, now=None):
        if self.error:
            raise self.error
        return self.items[:limit]


# ---- 适配器解析（固定样本，不联网） ----

def test_show_hn_parser_strips_prefix_and_keeps_signals():
    item = show_hn.parse({"hits": [{"objectID": "1", "title": "Show HN: Tiny radio", "url": "https://r.test",
                                    "points": 120, "num_comments": 30, "created_at": "2026-10-03T01:00:00Z"}]})[0]
    assert item["id"] == "show_hn:1" and item["title"] == "Tiny radio"
    assert item["signals"] == {"upvotes": 120, "comments": 30}
    assert item["discussion"] == "https://news.ycombinator.com/item?id=1"


def test_github_parser_skips_forks_and_uses_stars():
    payload = {"items": [
        {"id": 1, "full_name": "a/tool", "html_url": "https://github.com/a/tool", "description": "Does X",
         "stargazers_count": 2100, "created_at": "2026-10-01T00:00:00Z"},
        {"id": 2, "full_name": "b/fork", "html_url": "https://github.com/b/fork", "fork": True},
    ]}
    items = github.parse(payload)
    assert [item["id"] for item in items] == ["github:1"]
    assert items[0]["signals"] == {"stars": 2100}


def test_v2ex_parser_converts_unix_time_and_replies():
    item = v2ex.parse([{"id": 9, "title": "做了个小工具", "url": "https://www.v2ex.com/t/9",
                        "content": "介绍", "replies": 18, "created": 1791013036}])[0]
    assert item["lang"] == "zh" and item["signals"] == {"comments": 18}
    assert item["published_at"].startswith("2026-")


RSS = b"""<?xml version="1.0"?><rss version="2.0" xmlns:slash="http://purl.org/rss/1.0/modules/slash/">
<channel><title>t</title><item><title>Tiny lathe</title><link>https://h.test/1</link>
<pubDate>Fri, 02 Oct 2026 10:00:00 +0000</pubDate><description>&lt;p&gt;A lathe&lt;/p&gt;</description>
<slash:comments>34</slash:comments></item></channel></rss>"""


def test_hackaday_parser_reads_comment_count():
    item = hackaday.parse(RSS)[0]
    assert item["signals"] == {"comments": 34} and item["summary"] == "A lathe"


def test_sspai_parser_has_no_signals():
    assert sspai.parse(RSS)[0]["signals"] == {}


# ---- 评分 ----

def test_percentile_uses_mid_rank_and_neutral_single_sample():
    assert ideas.percentile(5, [5]) == 50
    assert ideas.percentile(30, [10, 20, 30, 40]) == 62  # 62.5 按 Python 四舍六入五成双
    assert ideas.percentile(1, []) == 50


def enriched(item, kind="hack"):
    return {**item, "type": kind, "title": {"zh": item["title"], "en": item["title"]},
            "why": {"zh": "", "en": ""}, "who": None, "effort": None, "enriched": True}


def test_score_matches_v2_formula_with_decay_and_cross_site_boost():
    hn = enriched(raw("show_hn", 1, "Bluetooth spreadsheet", {"upvotes": 400}, url="https://github.com/x/sheet",
                      published="2026-10-02T12:00:00+00:00"))
    gh = enriched(raw("github", 1, "x/sheet", {"stars": 2000}, url="https://github.com/x/sheet/",
                      published="2026-10-02T18:00:00+00:00"))
    low = enriched(raw("show_hn", 2, "Other thing", {"upvotes": 10}, published="2026-10-03T12:00:00+00:00"))
    result = {idea["id"]: idea for idea in ideas.score([hn, gh, low], NOW)}
    merged = result["show_hn:1"]
    # 同一 GitHub 链接合并：HN 百分位 75、GitHub 单样本 50 → 加权 63；年龄 24h；两站 +3
    assert merged["n_sites"] == 2 and merged["boost"] == 3
    assert merged["weighted"] == round((75 + 50) / 2)
    assert merged["age_h"] == 24
    assert merged["final"] == round(merged["weighted"] * 0.5 ** (24 / 168) + 3)
    assert result["show_hn:2"]["final"] == round(25 * 1.0)


def test_text_merge_requires_different_sources():
    a = enriched(raw("show_hn", 1, "Offline first spreadsheet syncing over bluetooth mesh", {"upvotes": 5}))
    b = enriched(raw("v2ex", 1, "Offline first spreadsheet syncing over bluetooth mesh", {"comments": 2}))
    c = enriched(raw("v2ex", 2, "Offline first spreadsheet syncing over bluetooth mesh", {"comments": 3}))
    groups = ideas.merge_groups([a, b, c])
    assert sorted(len(group) for group in groups) == [3]
    unrelated = enriched(raw("github", 3, "Kitchen timer firmware", {"stars": 1}))
    assert len(ideas.merge_groups([a, unrelated])) == 2


# ---- 抓取、标注与存储 ----

def test_collect_marks_failed_sources_and_drops_blocked_items():
    good = Stub([raw("show_hn", 1, "Tiny radio", {"upvotes": 5}), raw("show_hn", 2, "Election tracker", {"upvotes": 9})])
    data = ideas.collect({"block_keywords": ["Election"]}, None,
                         sources={"show_hn": good, "github": Stub(error=RuntimeError("boom"))})
    assert [item["id"] for item in data["items"]] == ["show_hn:1"]
    assert data["sources"]["github"] == {"status": "failed", "count": 0}
    assert data["sources"]["show_hn"] == {"status": "ok", "count": 1}


def test_no_key_fallback_uses_source_type_and_summary():
    item = ideas.collect({}, None, sources={"v2ex": Stub([raw("v2ex", 1, "做了个工具", {}, summary="一个工具")])})["items"][0]
    assert item["type"] == "product" and item["enriched"] is False
    assert item["why"] == {"zh": "一个工具", "en": ""}


class FakeClient:
    def __init__(self, reply):
        self.calls = 0
        self.reply = reply
        self.chat = self
        self.completions = self

    def create(self, **_):
        self.calls += 1
        message = type("M", (), {"content": json.dumps(self.reply)})
        return type("R", (), {"choices": [type("C", (), {"message": message})]})


def test_model_labels_drop_non_ideas_and_are_reused_on_rerun():
    source = Stub([raw("sspai", 1, "Film list", {}), raw("sspai", 2, "Keyboard trick", {})])
    client = FakeClient({"ideas": [{"index": 0, "keep": False},
                                   {"index": 1, "type": "method", "title_zh": "键盘技巧", "title_en": "Keyboard trick",
                                    "why_zh": "省时", "why_en": "Saves time", "who_zh": "打字的人", "who_en": "typists", "effort": 1}]})
    first = ideas.collect({}, client, sources={"sspai": source})
    assert [item["id"] for item in first["items"]] == ["sspai:2"]
    assert first["items"][0]["who"] == {"zh": "打字的人", "en": "typists"}
    again = ideas.collect({}, client, previous=first, sources={"sspai": Stub([raw("sspai", 2, "Keyboard trick", {})])})
    assert client.calls == 1 and again["items"][0]["title"]["zh"] == "键盘技巧"


def test_fallback_labels_are_redone_when_a_key_is_available():
    source = Stub([raw("sspai", 2, "Keyboard trick", {})])
    first = ideas.collect({}, None, sources={"sspai": source})
    client = FakeClient({"ideas": [{"index": 0, "type": "method", "title_zh": "键盘技巧", "title_en": "Keyboard trick"}]})
    again = ideas.collect({}, client, previous=first, sources={"sspai": source})
    assert client.calls == 1 and again["items"][0]["enriched"] is True


def test_run_exports_ranges_and_reuses_same_day_file(tmp_path, monkeypatch):
    items = [raw("show_hn", 1, "Tiny radio", {"upvotes": 5}, published="2026-10-03T08:00:00+00:00"),
             raw("show_hn", 2, "Old lathe", {"upvotes": 50}, published="2026-09-20T08:00:00+00:00")]
    monkeypatch.setattr(ideas, "SOURCES", {"show_hn": show_hn})
    monkeypatch.setattr(show_hn, "fetch", lambda limit=30, now=None: items)
    out = tmp_path / "radar" / "ideas.json"
    export = ideas.run("2026-10-03", {}, None, tmp_path / "ideas", out)
    assert export["counts"] == {"24h": 1, "7d": 1, "30d": 2}
    assert export["types"]["30d"]["hack"] == 2
    assert export["sources"][0]["status"] == "ok"
    before = out.stat().st_mtime_ns
    monkeypatch.setattr(show_hn, "fetch", lambda limit=30, now=None: pytest.fail("same-day rerun must reuse"))
    ideas.run("2026-10-03", {}, None, tmp_path / "ideas", out)
    assert out.stat().st_mtime_ns == before


def test_prune_keeps_sixty_days(tmp_path):
    for day in ("2026-08-03", "2026-08-04", "2026-10-03"):
        (tmp_path / f"{day}.json").write_text("{}")
    ideas.prune(tmp_path, "2026-10-03")
    assert sorted(path.stem for path in tmp_path.glob("*.json")) == ["2026-08-04", "2026-10-03"]
