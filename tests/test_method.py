from method import build_method_page, write_method_page


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
        "feeds": [
            {"name": "TechCrunch AI", "section": "ai", "category": "AI 动态",
             "ai_filter": False, "max_items": 10},
            {"name": "BBC World", "section": "world", "category": "国际新闻",
             "ai_filter": False, "max_items": 10},
            {"name": "The Atlantic", "section": "deep", "category": "大西洋月刊",
             "ai_filter": False, "max_items": 8},
            {"name": "第一财经", "section": "market", "category": "财经要闻",
             "ai_filter": False, "max_items": 8},
        ],
    }
    out = build_method_page(config)
    assert "流水线概览" in out
    assert "total_limit" in out
    assert "TechCrunch AI" in out
    assert "The Atlantic" in out
    assert "9-10" in out
    assert "【重点】" in out
    assert "`AI`" in out
    assert "东方财富" in out


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
    assert "方法" in text
    assert "section-method" in text
    assert "ShowToc: true" in text
