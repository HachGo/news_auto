"""国际大事回归：使用实际配置验证 RSS 过滤、版面发布和公开规则。"""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from common import RANK_RULES, build_rank_prompt, load_config
from generators import world
from method import build_method_page
from sources import rss


FEEDS_FILE = Path(__file__).resolve().parent.parent / "scripts" / "feeds.yaml"


@pytest.mark.parametrize(("title", "summary"), [
    ("APEC leaders agree on regional trade cooperation",
     "President Xi Jinping and Trump attend the diplomatic summit."),
    ("亚太经合组织会议公布经贸合作成果", "习近平与多国总统出席，讨论外交与贸易政策。"),
    ("G20 summit agrees on global debt relief", "The White House announces a new policy."),
    ("联合国气候大会达成减排协议", "多国首相与内阁代表达成协议。"),
    ("Taiwan chip exports grow", "Taipei reports stronger semiconductor demand."),
    ("NATO announces new security agreement", "Geopolitical developments affect energy trade."),
    ("New sanctions affect international trade", "Congress approves the measures."),
])
def test_default_world_rules_publish_factual_international_news(
        tmp_path, monkeypatch, title, summary):
    config = load_config(FEEDS_FILE)
    entry = {"title": title, "summary": summary, "link": "https://example.test/news",
             "published": datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(rss, "fetch_feed", lambda _: SimpleNamespace(entries=[entry]))
    config["settings"]["per_host_interval"] = 0

    # 同时验证无 LLM 时的降级发布，不靠模型或关键词白名单绕过硬过滤。
    result = world.generate(config, {}, None, "2026-11-21", posts_dir=tmp_path)

    assert result is not None
    assert [item["title"] for item in result["items"]] == [title]
    text = result["path"].read_text(encoding="utf-8")
    assert title in text
    assert summary in text


def test_apec_reaches_llm_ranking_and_can_be_highlighted(tmp_path, monkeypatch, fake_summaries):
    config = load_config(FEEDS_FILE)
    config["settings"]["per_host_interval"] = 0
    entry = {"title": "APEC summit agrees on trade framework",
             "summary": "Xi Jinping and Trump discuss diplomacy and sanctions.",
             "link": "https://example.test/apec"}
    monkeypatch.setattr(rss, "fetch_feed", lambda _: SimpleNamespace(entries=[entry]))
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(
            content='{"selected": [{"index": 0, "score": 9}]}')),
    ])
    monkeypatch.setattr(world, "apply_summaries", fake_summaries)

    result = world.generate(config, {}, client, "2026-11-21", posts_dir=tmp_path)

    assert result["items"][0]["score"] == 9
    assert "【重点】" in result["path"].read_text(encoding="utf-8")
    prompt = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert entry["title"] in prompt
    assert "分数给 1 分并跳过" not in prompt


def test_public_rules_and_rank_prompt_share_all_editorial_rules():
    config = load_config(FEEDS_FILE)
    prompt = build_rank_prompt(15, "0. [国际新闻/示例来源] APEC summit")
    page = build_method_page(config)

    for rule in RANK_RULES:
        assert rule in prompt
        assert rule in page
    assert "APEC" in page
    assert "G20" in page
    assert "纯党争" in prompt
    assert "默认不设置关键词硬过滤" in page
    assert "分数给 1 分并跳过" not in prompt


def test_explicit_block_keywords_still_apply_to_major_events(monkeypatch):
    config = load_config(FEEDS_FILE)
    config["feeds"] = [feed for feed in config["feeds"] if feed["section"] == "world"][:1]
    config["block_keywords"] = ["示例排除词"]
    entry = {"title": "APEC 峰会取得经贸成果", "summary": "示例排除词",
             "link": "https://example.test/blocked"}
    monkeypatch.setattr(rss, "fetch_feed", lambda _: SimpleNamespace(entries=[entry]))

    assert rss.fetch_candidates(config, {}) == []
    assert "`示例排除词`" in build_method_page(config)
