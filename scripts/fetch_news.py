#!/usr/bin/env python3
"""每日资讯抓取主入口。

编排四版面生成（ai/world/market/deep）+ 首页今日总览 + 趋势快照 + 网站规则页，更新 seen.json。
任一版面异常被捕获，不阻塞其他版面。
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from common import atomic_write_text, load_config, load_seen, save_seen, build_llm_client, link_hash
from generators import ai, world, market, deep
from homepage import build_homepage
from method import write_method_page
from trends import pipeline as trend_pipeline

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = Path(__file__).resolve().parent / "feeds.yaml"
SEEN_FILE = ROOT / "data" / "seen.json"
CONTENT_DIR = ROOT / "content"
CST = timezone(timedelta(hours=8))

SECTION_NAMES = {
    "ai": "AI与科技",
    "world": "国际资讯",
    "market": "金融市场与股市",
    "deep": "深度阅读与学习",
}


def main(force_refresh=None):
    if force_refresh is None:
        force_refresh = os.getenv("NEWS_FORCE_REFRESH", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
    config = load_config(FEEDS_FILE)
    seen = load_seen(SEEN_FILE)
    client = build_llm_client()

    date_str = datetime.now(CST).strftime("%Y-%m-%d")
    sections = {}
    raw_results = {}

    for key, gen in (("ai", ai), ("world", world), ("market", market), ("deep", deep)):
        try:
            result = gen.generate(config, seen, client, date_str,
                                  posts_dir=CONTENT_DIR / key,
                                  force_refresh=force_refresh)
            if result:
                raw_results[key] = result
            sections[key] = _to_section_summary(key, result or {}, date_str)
            sections[key]["status"] = "empty" if result is None else "ready"
        except Exception as exc:
            print(f"[error] {key} 版面生成失败: {exc}", file=sys.stderr)
            sections[key] = None

    # 首页
    try:
        homepage_md = build_homepage(sections, date_str)
        atomic_write_text(CONTENT_DIR / "_index.md", homepage_md)
        print("[info] 首页已生成")
    except Exception as exc:
        print(f"[error] 首页生成失败: {exc}", file=sys.stderr)

    # 趋势层使用结构化结果，不解析 Markdown。失败不连坐日报和首页。
    try:
        trend_data_dir = CONTENT_DIR.parent / "data" / "trends"
        trend_export_dir = CONTENT_DIR.parent / "static" / "data" / "trends"
        trend_exists = (
            (trend_data_dir / "daily" / f"{date_str}.json").exists()
            and (trend_export_dir / "latest.json").exists()
        )
        if trend_exists and not force_refresh:
            print("[info] 复用已生成趋势数据")
        else:
            trend_pipeline.run(
                date_str=date_str,
                sections=raw_results,
                data_dir=trend_data_dir,
                export_dir=trend_export_dir,
            )
            print("[info] 趋势数据已生成")
    except Exception as exc:
        print(f"[warn] 趋势数据生成失败，不影响日报发布: {exc}", file=sys.stderr)

    # 网站规则页（与 feeds / 评分规则同步）
    try:
        method_path = CONTENT_DIR / "method.md"
        if method_path.exists() and not force_refresh:
            print("[info] 复用已生成网站规则页")
        else:
            write_method_page(config, path=method_path)
    except Exception as exc:
        print(f"[error] 网站规则页生成失败: {exc}", file=sys.stderr)

    # 更新 seen
    now_iso = datetime.now(timezone.utc).isoformat()
    for key in sections:
        sec = sections.get(key)
        if not sec:
            continue
        for item in sec.get("_raw_items", []):
            seen.setdefault(link_hash(item["link"]), now_iso)
    save_seen(SEEN_FILE, seen)
    print("[info] seen.json 已更新")


def _to_section_summary(key, result, date_str):
    """把生成器返回值转成首页摘要用的字典。

    items: 用于首页焦点选取（market 只含财经要闻，带 score）。
    _raw_items: 用于 seen 去重（market 含财经要闻+研报，都需去重）。
    """
    items = result.get("items") or []
    raw = result.get("all_rss_items") or items
    return {
        "name": SECTION_NAMES[key],
        "url": f"/{key}/{date_str}/",
        "items": items,
        "count": len(items),
        "quotes": result.get("quotes") if key == "market" else None,
        "_raw_items": raw,
    }


if __name__ == "__main__":
    main()
