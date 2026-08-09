from method import build_method_page, site_label, write_method_page


def test_site_label_extracts_host_and_google_news_site():
    assert site_label("https://techcrunch.com/category/ai/feed/") == "techcrunch.com"
    assert site_label(
        "https://news.google.com/rss/search?q=site:yicai.com&hl=zh-CN"
    ) == "yicai.com"
    assert site_label("") == "—"


def test_build_method_page_includes_feeds_and_scores():
    config = {
        "settings": {
            "total_limit": 15,
            "per_source_limit": 4,
            "hours_window": 36,
            "deep_limit": 8,
            "deep_per_source_limit": 2,
        },
        "ai_keywords": ["AI", "LLM"],
        "block_keywords": ["Taiwan", "政治"],
        "feeds": [
            {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/ai/feed/",
             "section": "ai", "category": "AI 动态",
             "ai_filter": False, "max_items": 10},
            {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
             "section": "world", "category": "国际新闻",
             "ai_filter": False, "max_items": 10},
            {"name": "The Atlantic", "url": "https://www.theatlantic.com/feed/all/",
             "section": "deep", "category": "大西洋月刊",
             "ai_filter": False, "max_items": 8},
            {"name": "第一财经",
             "url": "https://news.google.com/rss/search?q=site:yicai.com&hl=zh-CN",
             "section": "market", "category": "财经要闻",
             "ai_filter": False, "max_items": 8},
        ],
    }
    out = build_method_page(config)
    assert "获取哪些网站" in out
    assert "筛选与排序规则" in out
    assert "流水线概览" in out
    assert "total_limit" in out
    assert "TechCrunch AI" in out
    assert "[techcrunch.com](https://techcrunch.com/category/ai/feed/)" in out
    assert "[yicai.com]" in out
    assert "The Atlantic" in out
    assert "9-10" in out
    assert "【重点】" in out
    assert "`AI`" in out
    assert "东方财富" in out
    # 屏蔽词仅后台配置，前台网站规则页不展示
    assert "屏蔽词" not in out
    assert "Taiwan" not in out
    assert "习近平" not in out


def test_write_method_page(tmp_path):
    path = write_method_page(
        {
            "settings": {"total_limit": 3},
            "ai_keywords": [],
            "feeds": [],
        },
        path=tmp_path / "method.md",
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "网站规则" in text
    assert "section-rules" in text
    assert 'url: "/rules/"' in text
    assert "ShowToc: true" in text
    assert "获取哪些网站" in text
