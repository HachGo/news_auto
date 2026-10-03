from method import build_rules, feed_link_cell, site_label, write_rules


def test_site_label_extracts_host_and_google_news_site():
    assert site_label("https://techcrunch.com/category/ai/feed/") == "techcrunch.com"
    assert site_label(
        "https://news.google.com/rss/search?q=site:yicai.com&hl=zh-CN"
    ) == "yicai.com"
    assert site_label("") == "—"


def test_feed_link_cell_links_site_home_not_rss_xml():
    assert feed_link_cell({"url": "https://techcrunch.com/category/ai/feed/"}) == (
        "[techcrunch.com](https://techcrunch.com/) · [RSS](https://techcrunch.com/category/ai/feed/)"
    )
    # Google News 定向站点：落到目标站首页
    assert feed_link_cell(
        {"url": "https://news.google.com/rss/search?q=site:yicai.com&hl=zh-CN"}
    ).startswith("[yicai.com](https://yicai.com/)")
    # Google News 关键词聚合：落到网页版搜索结果
    assert "(https://news.google.com/search?q=" in feed_link_cell(
        {"url": "https://news.google.com/rss/search?q=%E5%88%B8%E5%95%86&hl=zh-CN"}
    )
    # 纯 RSS 域名用 homepage 覆盖
    assert feed_link_cell(
        {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "homepage": "https://www.bbc.com/news/world"}
    ).startswith("[bbc.com](https://www.bbc.com/news/world) · [RSS](")


def test_rules_include_every_feed_and_public_values():
    import json
    from common import load_config, PRIVATE_RANK_RULES
    config = load_config()
    config["block_keywords"] = ["PRIVATE_BLOCK_SENTINEL", "隐藏过滤词"]
    result = build_rules(config)
    assert [s["key"] for s in result["sections"]] == ["fetch", "filter", "analyze", "publish"]
    assert len(result["sources"]) == len(config["feeds"]) + 3 + 5
    idea_sources = [source for source in result["sources"] if source["section"] == "ideas"]
    assert [source["name"]["en"] for source in idea_sources] == ["Show HN", "GitHub", "V2EX", "Hackaday", "SSPAI"]
    assert "Idea scoring" in json.dumps(result)
    for feed, source in zip(config["feeds"], result["sources"]):
        assert source["name"]["zh"] == feed["name"]
        assert source["name"]["en"]
        assert set(source["category"]) == {"zh", "en"}
        assert source["site"] == site_label(feed.get("homepage") or feed["url"])
        assert source["href"] == (feed.get("homepage") or __import__("method").site_home(feed["url"]))
    public = json.dumps(result, ensure_ascii=False)
    assert "block_keywords" not in public
    for private in config["block_keywords"] + PRIVATE_RANK_RULES:
        assert private not in public
    assert "9-10" in public
    assert "rules-v1" in public


def test_write_rules_is_stable(tmp_path):
    path = tmp_path / "rules.json"
    config = {"settings": {}, "ai_keywords": [], "feeds": []}
    write_rules(config, path)
    before = path.stat().st_mtime_ns
    write_rules(config, path)
    assert path.stat().st_mtime_ns == before
    assert '"sections"' in path.read_text()
