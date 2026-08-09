"""国际资讯版面生成器。

国际硬新闻走 LLM 排序 + 摘要，渲染为 content/world/YYYY-MM-DD.md。
"""

import sys
from pathlib import Path

from common import rank_and_select, summarize, render_sectioned
from sources import rss


def generate(config, seen, client, date_str, posts_dir=None):
    world_config = _filter_section(config, "world")
    candidates = rss.fetch_candidates(world_config, seen)
    if not candidates:
        print("[info] 国际版面无新条目，跳过")
        return None

    selected = rank_and_select(client, candidates, config)

    ok = 0
    for item in selected:
        result = summarize(client, item)
        if result:
            item.update(result)
            ok += 1

    if client is not None and ok == 0 and selected:
        print("[error] 国际版面 LLM 全失败，跳过发布", file=sys.stderr)
        return None

    posts_dir = Path(posts_dir) if posts_dir else Path("content/world")
    posts_dir.mkdir(parents=True, exist_ok=True)
    path = posts_dir / f"{date_str}.md"
    path.write_text(
        render_sectioned(selected, f"国际资讯 {date_str}", f"今日 {len(selected)} 条国际资讯。"),
        encoding="utf-8",
    )
    print(f"[info] 国际版面已生成 {path}")
    return {"path": path, "items": selected}


def _filter_section(config, section):
    return {
        "settings": config.get("settings", {}),
        "ai_keywords": config.get("ai_keywords", []),
        "feeds": [f for f in config.get("feeds", []) if f.get("section") == section],
    }
