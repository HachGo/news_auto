from unittest.mock import patch
from datetime import datetime, timezone, timedelta

import fetch_news

CST = timezone(timedelta(hours=8))
FIXED = datetime(2026, 8, 1, 8, 0, 0, tzinfo=CST)


class FakeDateTime:
    @classmethod
    def now(cls, tz=None):
        return FIXED


def test_main_writes_all_sections_and_home(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_news, "datetime", FakeDateTime)
    monkeypatch.setattr(fetch_news, "CONTENT_DIR", tmp_path)
    monkeypatch.setattr(fetch_news, "SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(fetch_news, "load_config", lambda *a, **k: {"settings": {}, "ai_keywords": [], "feeds": []})
    monkeypatch.setattr(fetch_news, "load_seen", lambda *a, **k: {})
    monkeypatch.setattr(fetch_news, "save_seen", lambda *a, **k: None)
    monkeypatch.setattr(fetch_news, "build_llm_client", lambda: None)

    force_refresh_values = []

    def fake_gen(config, seen, client, date_str, posts_dir, force_refresh=False):
        force_refresh_values.append(force_refresh)
        posts_dir.mkdir(parents=True, exist_ok=True)
        path = posts_dir / f"{date_str}.md"
        path.write_text("---\ntitle: x\n---\nbody", encoding="utf-8")
        return {"path": path, "items": [{"title_zh": "焦点", "score": 9, "link": "l", "source": "S"}]}

    with patch.object(fetch_news.ai, "generate", side_effect=fake_gen), \
         patch.object(fetch_news.world, "generate", side_effect=fake_gen), \
         patch.object(fetch_news.market, "generate", side_effect=fake_gen), \
         patch.object(fetch_news.deep, "generate", side_effect=fake_gen):
        fetch_news.main()

    assert (tmp_path / "ai" / "2026-08-01.md").exists()
    assert (tmp_path / "world" / "2026-08-01.md").exists()
    assert (tmp_path / "market" / "2026-08-01.md").exists()
    assert (tmp_path / "deep" / "2026-08-01.md").exists()
    assert (tmp_path / "_index.md").exists()
    assert "今日焦点" in (tmp_path / "_index.md").read_text(encoding="utf-8")
    assert "home-overview" in (tmp_path / "_index.md").read_text(encoding="utf-8")
    assert force_refresh_values == [False, False, False, False]


def test_main_enables_force_refresh_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_FORCE_REFRESH", "1")
    monkeypatch.setattr(fetch_news, "datetime", FakeDateTime)
    monkeypatch.setattr(fetch_news, "CONTENT_DIR", tmp_path)
    monkeypatch.setattr(fetch_news, "SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(fetch_news, "load_config", lambda *a, **k: {"settings": {}, "feeds": []})
    monkeypatch.setattr(fetch_news, "load_seen", lambda *a, **k: {})
    monkeypatch.setattr(fetch_news, "save_seen", lambda *a, **k: None)
    monkeypatch.setattr(fetch_news, "build_llm_client", lambda: None)
    values = []

    def fake_gen(config, seen, client, date_str, posts_dir, force_refresh=False):
        values.append(force_refresh)
        return {"items": []}

    with patch.object(fetch_news.ai, "generate", side_effect=fake_gen), \
         patch.object(fetch_news.world, "generate", side_effect=fake_gen), \
         patch.object(fetch_news.market, "generate", side_effect=fake_gen), \
         patch.object(fetch_news.deep, "generate", side_effect=fake_gen):
        fetch_news.main()

    assert values == [True, True, True, True]


def test_main_continues_on_section_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_news, "datetime", FakeDateTime)
    monkeypatch.setattr(fetch_news, "CONTENT_DIR", tmp_path)
    monkeypatch.setattr(fetch_news, "SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(fetch_news, "load_config", lambda *a, **k: {"settings": {}, "feeds": []})
    monkeypatch.setattr(fetch_news, "load_seen", lambda *a, **k: {})
    monkeypatch.setattr(fetch_news, "save_seen", lambda *a, **k: None)
    monkeypatch.setattr(fetch_news, "build_llm_client", lambda: None)

    def boom(*a, **k):
        raise RuntimeError("boom")

    def ok(config, seen, client, date_str, posts_dir, force_refresh=False):
        posts_dir.mkdir(parents=True, exist_ok=True)
        (posts_dir / f"{date_str}.md").write_text("---\ntitle: x\n---\nbody", encoding="utf-8")
        return {"path": posts_dir / f"{date_str}.md", "items": [{"title_zh": "x", "score": 9, "link": "l", "source": "S"}]}

    with patch.object(fetch_news.ai, "generate", side_effect=boom), \
         patch.object(fetch_news.world, "generate", side_effect=ok), \
         patch.object(fetch_news.market, "generate", side_effect=ok), \
         patch.object(fetch_news.deep, "generate", side_effect=ok):
        fetch_news.main()
    assert (tmp_path / "_index.md").exists()
