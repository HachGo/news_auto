"""国际与深度版面生成器。

国际新闻走 LLM 排序，深度精选走来源均衡（select_deep），二者合并渲染。
"""

import sys
from pathlib import Path

from common import rank_and_select, select_deep, summarize, render_sectioned, DEEP_CATEGORY
from sources import rss


def generate(config, seen, client, date_str, posts_dir=None):
    world_config = _filter_section(config, "world")
    candidates = rss.fetch_candidates(world_config, seen)
    if not candidates:
        print("[info] 国际版面无新条目，跳过")
        return None

    deep_candidates = [c for c in candidates if c["category"] == DEEP_CATEGORY]
    regular_candidates = [c for c in candidates if c["category"] != DEEP_CATEGORY]

    selected = rank_and_select(client, regular_candidates, config)
    deep_selected = select_deep(deep_candidates, config)
    selected.extend(deep_selected)

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
        render_sectioned(selected, f"国际与深度 {date_str}", f"今日 {len(selected)} 条国际新闻与深度报道。"),
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
