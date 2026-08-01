"""AI 与科技社区版面生成器。

从 feeds.yaml 拉取 section=ai 的 RSS 候选，LLM 排序 + 摘要，渲染为
content/ai/YYYY-MM-DD.md。
"""

import sys
from pathlib import Path

from common import rank_and_select, summarize, render_sectioned
from sources import rss


def generate(config, seen, client, date_str, posts_dir=None):
    """生成 AI 版面文章。无候选时返回 None。"""
    ai_config = _filter_section(config, "ai")
    candidates = rss.fetch_candidates(ai_config, seen)
    if not candidates:
        print("[info] AI 版面无新条目，跳过")
        return None

    selected = rank_and_select(client, candidates, config)

    ok = 0
    for item in selected:
        result = summarize(client, item)
        if result:
            item.update(result)
            ok += 1

    if client is not None and ok == 0 and selected:
        print("[error] AI 版面 LLM 全失败，跳过发布", file=sys.stderr)
        return None

    posts_dir = Path(posts_dir) if posts_dir else Path("content/ai")
    posts_dir.mkdir(parents=True, exist_ok=True)
    path = posts_dir / f"{date_str}.md"
    path.write_text(
        render_sectioned(selected, f"AI 与科技社区 {date_str}", f"今日 {len(selected)} 条 AI 动态与社区热点。"),
        encoding="utf-8",
    )
    print(f"[info] AI 版面已生成 {path}")
    return {"path": path, "items": selected}


def _filter_section(config, section):
    """返回只含指定 section feeds 的 config 副本。"""
    return {
        "settings": config.get("settings", {}),
        "ai_keywords": config.get("ai_keywords", []),
        "feeds": [f for f in config.get("feeds", []) if f.get("section") == section],
    }
