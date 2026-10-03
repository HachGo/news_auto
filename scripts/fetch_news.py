#!/usr/bin/env python3
"""每日资讯抓取主入口。

编排四版面生成（ai/world/market/deep，中英文各一份）+ 创意抓取与评分 + 趋势快照 +
今日简报数据（首页）+ 雷达页面数据 + 网站规则，更新 seen.json。任一版面异常被捕获，不阻塞其他版面。
"""

import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from common import load_config, load_seen, save_seen, build_llm_client, link_hash
from generators import ai, world, market, deep
import ideas
from brief import build_brief, load_brief, write_brief
from method import write_rules
from radar import write_radar
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
    statuses = {}

    for key, gen in (("ai", ai), ("world", world), ("market", market), ("deep", deep)):
        try:
            result = gen.generate(config, seen, client, date_str,
                                  posts_dir=CONTENT_DIR / key,
                                  force_refresh=force_refresh)
            if result:
                raw_results[key] = result
            sections[key] = _to_section_summary(key, result or {}, date_str)
            statuses[key] = "empty" if result is None else "ready"
        except Exception as exc:
            print(f"[error] {key} 版面生成失败: {exc}", file=sys.stderr)
            sections[key] = None
            statuses[key] = "failed"

    # 趋势层使用结构化结果，不解析 Markdown。失败不连坐日报和首页。
    trend_data_dir = CONTENT_DIR.parent / "data" / "trends"
    try:
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

    # 今日简报数据（首页）：在趋势之后，上升信号与预测依赖当日快照
    try:
        brief_path = CONTENT_DIR.parent / "data" / "brief" / f"{date_str}.json"
        previous = load_brief(brief_path)
        brief = build_brief(
            raw_results, date_str, datetime.now(CST).isoformat(timespec="seconds"),
            trend_dir=trend_data_dir, previous=previous, statuses=statuses,
        )
        if write_brief(brief_path, brief, previous):
            print("[info] 今日简报数据已生成")
        else:
            print("[info] 今日简报无变化，保留已有数据")
    except Exception as exc:
        print(f"[error] 今日简报数据生成失败: {exc}", file=sys.stderr)

    # 创意板块：独立抓取与评分，失败只影响创意页。
    try:
        ideas.run(date_str, config, client, CONTENT_DIR.parent / "data" / "ideas",
                  CONTENT_DIR.parent / "data" / "radar" / "ideas.json", force_refresh=force_refresh)
    except Exception as exc:
        print(f"[error] 创意数据生成失败: {exc}", file=sys.stderr)

    # 雷达页面数据，失败不影响日报和首页。
    try:
        write_radar(trend_data_dir, date_str, CONTENT_DIR.parent / "data" / "radar")
    except Exception as exc:
        print(f"[error] 雷达数据生成失败: {exc}", file=sys.stderr)

    # 网站规则每次同步，内容未变时不写入。
    try:
        write_rules(config, CONTENT_DIR.parent / "data" / "radar" / "rules.json")
    except Exception as exc:
        print(f"[error] 网站规则数据生成失败: {exc}", file=sys.stderr)

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
    """生成器返回值里用于 seen 去重的部分（market 含财经要闻+研报，都需去重）。"""
    items = result.get("items") or []
    return {
        "name": SECTION_NAMES[key],
        "_raw_items": result.get("all_rss_items") or items,
    }


if __name__ == "__main__":
    main()
