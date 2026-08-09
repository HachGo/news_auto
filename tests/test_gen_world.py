from unittest.mock import patch, MagicMock

from generators import world


def _client(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = resp
    return client


def test_generate_regular_only(tmp_path):
    config = {
        "settings": {"total_limit": 5, "per_source_limit": 4, "hours_window": 240},
        "ai_keywords": [], "feeds": [],
    }
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    candidates = [
        {"title": "国际", "link": "l1", "summary": "s", "source": "BBC",
         "category": "国际新闻", "section": "world", "time": now},
    ]
    with patch("generators.world.rss.fetch_candidates", return_value=candidates), \
         patch("generators.world.rank_and_select", side_effect=lambda c, cs, cfg: list(cs)), \
         patch("generators.world.summarize", return_value={"title_zh": "中", "summary_zh": "摘"}):
        result = world.generate(config, {}, None, date_str="2026-08-01", posts_dir=tmp_path)
    assert result["path"].exists()
    text = result["path"].read_text(encoding="utf-8")
    assert "国际资讯" in text
    assert "国际新闻" in text
    assert "深度精选" not in text


def test_generate_empty_skips(tmp_path):
    with patch("generators.world.rss.fetch_candidates", return_value=[]):
        path = world.generate({"settings": {}, "ai_keywords": [], "feeds": []}, {}, None, "2026-08-01", tmp_path)
    assert path is None
