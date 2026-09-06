"""深度阅读与学习版面生成器。

刊物级长读：来源均衡（select_deep），加长摘要，刊物式排版。
"""

from pathlib import Path

from common import atomic_write_text, select_deep, summarize_deep, render_deep
from published import load_published_post, retain_failed_source_items, seen_without_published
from sources import rss


def generate(config, seen, client, date_str, posts_dir=None, force_refresh=False):
    posts_dir = Path(posts_dir) if posts_dir else Path("content/deep")
    path = posts_dir / f"{date_str}.md"
    existing = load_published_post(path, "deep")
    if existing is not None and not force_refresh:
        print(f"[info] 复用已生成日报 {path}")
        return existing
    deep_config = _filter_section(config, "deep")
    fetch_seen = seen_without_published(seen, existing) if force_refresh else seen
    if force_refresh:
        candidates, failed_sources = rss.fetch_candidates(
            deep_config, fetch_seen, return_failures=True,
            empty_is_failure=existing is not None,
        )
    else:
        candidates = rss.fetch_candidates(deep_config, fetch_seen)
        failed_sources = set()
    if not candidates:
        if existing is not None:
            print("[warn] 深度版面强制刷新未获取到条目，保留已有日报")
            return existing
        print("[info] 深度版面无新条目，跳过")
        return None

    selected = select_deep(candidates, config)
    selected = retain_failed_source_items(
        selected, existing, failed_sources,
        config.get("settings", {}).get("deep_limit", 8),
    )

    ok = 0
    for item in selected:
        result = summarize_deep(client, item)
        if result:
            item.update(result)
            ok += 1

    if client is not None and ok == 0 and selected:
        if existing is not None:
            print("[warn] 深度版面强制刷新 LLM 全失败，保留已有日报")
            return existing
        raise RuntimeError("深度版面 LLM 全失败，跳过发布")

    posts_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        render_deep(
            selected,
            f"深度阅读与学习 {date_str}",
            f"今日 {len(selected)} 条深度精选。",
        ),
    )
    print(f"[info] 深度版面已生成 {path}")
    return {"path": path, "items": selected, "all_rss_items": selected}


def _filter_section(config, section):
    return {
        "settings": config.get("settings", {}),
        "ai_keywords": config.get("ai_keywords", []),
        "block_keywords": config.get("block_keywords", []),
        "feeds": [f for f in config.get("feeds", []) if f.get("section") == section],
    }
