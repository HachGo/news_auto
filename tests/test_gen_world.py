from unittest.mock import patch, MagicMock

from generators import world
from common import DEEP_CATEGORY


def _client(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = resp
    return client


def test_generate_separates_deep_and_regular(tmp_path):
    config = {
        "settings": {"total_limit": 5, "per_source_limit": 4, "hours_window": 240,
                      "deep_limit": 6, "deep_per_source_limit": 2},
        "ai_keywords": [], "feeds": [],
    }
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    candidates = [
        {"title": "国际", "link": "l1", "summary": "s", "source": "BBC",
         "category": "国际新闻", "section": "world", "time": now},
        {"title": "深度", "link": "l2", "summary": "s", "source": "Economist",
         "category": DEEP_CATEGORY, "section": "world", "time": now},
    ]
    # patch rank_and_select 直接返回常规条目（不打分），让 render 走无-score 分支，
    # 这样「国际新闻」「深度精选」分类标题才会出现。
    with patch("generators.world.rss.fetch_candidates", return_value=candidates), \
         patch("generators.world.rank_and_select", side_effect=lambda c, cs, cfg: [x for x in cs]), \
         patch("generators.world.summarize", return_value={"title_zh": "中", "summary_zh": "摘"}):
        result = world.generate(config, {}, None, date_str="2026-08-01", posts_dir=tmp_path)
    assert result["path"].exists()
    text = result["path"].read_text(encoding="utf-8")
    assert "国际新闻" in text
    assert "深度精选" in text


def test_generate_empty_skips(tmp_path):
    with patch("generators.world.rss.fetch_candidates", return_value=[]):
        path = world.generate({"settings": {}, "ai_keywords": [], "feeds": []}, {}, None, "2026-08-01", tmp_path)
    assert path is None
