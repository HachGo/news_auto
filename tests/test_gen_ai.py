from unittest.mock import patch, MagicMock

from generators import ai


def _client_returning(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = resp
    return client


def test_generate_writes_sectioned_post(tmp_path):
    config = {
        "settings": {"total_limit": 5, "per_source_limit": 4, "hours_window": 240, "deep_limit": 6, "deep_per_source_limit": 2},
        "ai_keywords": ["ai"],
        "feeds": [{"name": "T", "url": "https://x", "section": "ai", "category": "AI 动态", "ai_filter": False, "max_items": 10}],
    }
    candidates = [
        {"title": "AI news", "link": "https://e/1", "summary": "s", "source": "T",
         "category": "AI 动态", "section": "ai", "time": None},
    ]
    client = _client_returning('{"selected": [{"index": 0, "score": 9}]}')

    with patch("generators.ai.rss.fetch_candidates", return_value=candidates), \
         patch("generators.ai.summarize", return_value={"title_zh": "中文", "summary_zh": "摘要"}):
        result = ai.generate(config, {}, client, date_str="2026-08-01", posts_dir=tmp_path)
    assert result["path"].exists()
    text = result["path"].read_text(encoding="utf-8")
    assert "title:" in text
    assert "今日焦点" in text


def test_generate_empty_candidates_skips(tmp_path):
    config = {"settings": {}, "ai_keywords": [], "feeds": []}
    with patch("generators.ai.rss.fetch_candidates", return_value=[]):
        path = ai.generate(config, {}, None, date_str="2026-08-01", posts_dir=tmp_path)
    assert path is None
