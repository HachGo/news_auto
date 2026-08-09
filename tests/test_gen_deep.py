from unittest.mock import patch
from datetime import datetime, timezone

from generators import deep


def test_generate_deep_magazine_layout(tmp_path):
    config = {
        "settings": {"deep_limit": 6, "deep_per_source_limit": 2, "hours_window": 240},
        "ai_keywords": [],
        "feeds": [],
    }
    now = datetime.now(timezone.utc)
    candidates = [
        {"title": "Deep A", "link": "https://e.com/a", "summary": "s", "source": "The Economist Latest",
         "category": "经济学人", "section": "deep", "time": now},
        {"title": "Deep B", "link": "https://s.com/b", "summary": "s", "source": "Scientific American",
         "category": "科学美国人", "section": "deep", "time": now},
    ]
    with patch("generators.deep.rss.fetch_candidates", return_value=candidates), \
         patch("generators.deep.summarize_deep",
               return_value={"title_zh": "中文标题", "summary_zh": "加长导读摘要说明为何值得读。"}):
        result = deep.generate(config, {}, None, date_str="2026-08-01", posts_dir=tmp_path)
    assert result["path"].exists()
    text = result["path"].read_text(encoding="utf-8")
    assert "深度阅读与学习" in text
    assert "deep-digest" in text
    assert "deep-item" in text
    assert "deep-dek" in text
    assert "今日精选" in text
    assert "按刊物" in text
    assert "经济学人" in text


def test_generate_deep_empty_skips(tmp_path):
    with patch("generators.deep.rss.fetch_candidates", return_value=[]):
        assert deep.generate({"settings": {}, "feeds": []}, {}, None, "2026-08-01", tmp_path) is None
