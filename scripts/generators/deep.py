"""深度阅读与学习版面生成器。

刊物级长读：来源均衡（select_deep），加长摘要，刊物式排版。
"""

import sys
from pathlib import Path

from common import select_deep, summarize_deep, render_deep
from sources import rss


def generate(config, seen, client, date_str, posts_dir=None):
    deep_config = _filter_section(config, "deep")
    candidates = rss.fetch_candidates(deep_config, seen)
    if not candidates:
        print("[info] 深度版面无新条目，跳过")
        return None

    selected = select_deep(candidates, config)

    ok = 0
    for item in selected:
        result = summarize_deep(client, item)
        if result:
            item.update(result)
            ok += 1

    if client is not None and ok == 0 and selected:
        print("[error] 深度版面 LLM 全失败，跳过发布", file=sys.stderr)
        return None

    posts_dir = Path(posts_dir) if posts_dir else Path("content/deep")
    posts_dir.mkdir(parents=True, exist_ok=True)
    path = posts_dir / f"{date_str}.md"
    path.write_text(
        render_deep(
            selected,
            f"深度阅读与学习 {date_str}",
            f"今日 {len(selected)} 条深度精选。",
        ),
        encoding="utf-8",
    )
    print(f"[info] 深度版面已生成 {path}")
    return {"path": path, "items": selected}


def _filter_section(config, section):
    return {
        "settings": config.get("settings", {}),
        "ai_keywords": config.get("ai_keywords", []),
        "feeds": [f for f in config.get("feeds", []) if f.get("section") == section],
    }
