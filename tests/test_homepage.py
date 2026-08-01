from pathlib import Path

from homepage import build_homepage


def test_build_homepage_with_all_sections(tmp_path):
    sections = {
        "ai": {
            "name": "AI 与科技社区",
            "url": "/ai/2026-08-01/",
            "items": [{"title_zh": "DeepSeek 发布", "score": 9, "link": "l1", "source": "S"}],
            "count": 8,
        },
        "world": {
            "name": "国际与深度",
            "url": "/world/2026-08-01/",
            "items": [{"title_zh": "休达越境", "score": 8, "link": "l2", "source": "S"}],
            "count": 7,
        },
        "market": {
            "name": "市场与宏观",
            "url": "/market/2026-08-01/",
            "items": [{"title_zh": "PMI 49.4", "score": 7, "link": "l3", "source": "S"}],
            "count": 12,
            "quotes": [{"name": "上证", "price": 3225, "change_pct": 0.82, "amount": 8e11}],
        },
    }
    out = build_homepage(sections, date_str="2026-08-01")
    assert "今日焦点" in out
    assert "DeepSeek 发布" in out
    assert "休达越境" in out
    assert "PMI 49.4" in out
    assert "/ai/2026-08-01/" in out
    assert "AI 与科技社区" in out


def test_build_homepage_degraded_section(tmp_path):
    sections = {
        "ai": {"name": "AI 与科技社区", "url": "/ai/", "items": [{"title_zh": "X", "score": 9, "link": "l", "source": "S"}], "count": 1},
        "world": None,  # 失败
        "market": None,  # 失败
    }
    out = build_homepage(sections, date_str="2026-08-01")
    assert "今日生成异常" in out
    assert "AI 与科技社区" in out


def test_market_focus_falls_back_to_quote(tmp_path):
    sections = {
        "market": {
            "name": "市场与宏观",
            "url": "/market/2026-08-01/",
            "items": [],  # 无财经要闻
            "count": 0,
            "quotes": [{"name": "上证指数", "price": 3225, "change_pct": 0.82, "amount": 8e11}],
        }
    }
    out = build_homepage(sections, date_str="2026-08-01")
    assert "上证指数" in out
