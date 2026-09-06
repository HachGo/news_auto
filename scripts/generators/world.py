"""国际资讯版面生成器。

国际硬新闻走 LLM 排序 + 摘要，渲染为 content/world/YYYY-MM-DD.md。
"""

from pathlib import Path

from common import atomic_write_text, rank_and_select, summarize, render_sectioned
from published import load_published_post, retain_failed_source_items, seen_without_published
from sources import rss


def generate(config, seen, client, date_str, posts_dir=None, force_refresh=False):
    """生成或复用国际日报。无候选返回 None；生成失败抛出异常。"""
    posts_dir = Path(posts_dir) if posts_dir else Path("content/world")
    path = posts_dir / f"{date_str}.md"
    existing = load_published_post(path, "world")
    if existing is not None and not force_refresh:
        print(f"[info] 复用已生成日报 {path}")
        return existing
    world_config = _filter_section(config, "world")
    fetch_seen = seen_without_published(seen, existing) if force_refresh else seen
    if force_refresh:
        candidates, failed_sources = rss.fetch_candidates(
            world_config, fetch_seen, return_failures=True, empty_is_failure=existing is not None,
        )
    else:
        candidates = rss.fetch_candidates(world_config, fetch_seen)
        failed_sources = set()
    if not candidates:
        if existing is not None:
            print("[warn] 国际版面强制刷新未获取到条目，保留已有日报")
            return existing
        print("[info] 国际版面无新条目，跳过")
        return None

    selected = rank_and_select(client, candidates, config)
    selected = retain_failed_source_items(
        selected, existing, failed_sources, config.get("settings", {}).get("total_limit", 15),
    )

    ok = 0
    for item in selected:
        result = summarize(client, item)
        if result:
            item.update(result)
            ok += 1

    if client is not None and ok == 0 and selected:
        if existing is not None:
            print("[warn] 国际版面强制刷新 LLM 全失败，保留已有日报")
            return existing
        raise RuntimeError("国际版面 LLM 全失败，跳过发布")

    posts_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        render_sectioned(selected, f"国际资讯 {date_str}", f"今日 {len(selected)} 条国际资讯。"),
    )
    print(f"[info] 国际版面已生成 {path}")
    return {"path": path, "items": selected, "all_rss_items": selected}


def _filter_section(config, section):
    return {
        "settings": config.get("settings", {}),
        "ai_keywords": config.get("ai_keywords", []),
        "block_keywords": config.get("block_keywords", []),
        "feeds": [f for f in config.get("feeds", []) if f.get("section") == section],
    }
