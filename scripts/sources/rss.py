"""RSS 抓取：fetch_feed / fetch_candidates / matches_keywords。

从原 fetch_news.py 抽出，四版面共用。支持 feeds 项里的 section 字段。
"""

import re
import sys
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from common import link_hash, strip_html, entry_time, matches_keywords, is_blocked


def fetch_feed(url, retries=3):
    """抓取并解析 RSS，对 429 限流做指数退避重试。失败返回 None。"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"[warn] 429 rate limited, retry in {wait}s: {url}", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return feedparser.parse(resp.content)
        except Exception as exc:
            print(f"[warn] fetch error ({exc}), attempt {attempt + 1}: {url}", file=sys.stderr)
            time.sleep(5)
    return None


def fetch_candidates(config, seen):
    """按 feeds.yaml 配置抓取所有源，返回候选条目列表（已去重+过滤）。"""
    settings = config.get("settings", {})
    hours_window = settings.get("hours_window", 36)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_window)
    keywords = config.get("ai_keywords", [])
    block_keywords = config.get("block_keywords", [])

    candidates = []
    run_seen = set()  # 本次运行内去重
    blocked = 0
    for feed_idx, feed_cfg in enumerate(config.get("feeds", [])):
        name = feed_cfg["name"]
        if feed_idx > 0:
            time.sleep(2)  # 部分站点对连续请求限流
        print(f"[fetch] {name} ...", flush=True)
        parsed = fetch_feed(feed_cfg["url"])
        if parsed is None:
            print(f"[warn] {name} fetch failed, skipped", file=sys.stderr)
            continue

        count = 0
        for entry in parsed.entries:
            if count >= feed_cfg.get("max_items", 10):
                break
            link = entry.get("link")
            title = (entry.get("title") or "").strip()
            if not link or not title:
                continue
            ts = entry_time(entry)
            if ts and ts < cutoff:
                continue
            h = link_hash(link)
            if h in seen or h in run_seen:
                continue
            if is_blocked(entry, block_keywords):
                blocked += 1
                continue
            run_seen.add(h)
            if feed_cfg.get("ai_filter") and not matches_keywords(entry, keywords):
                continue
            candidates.append(
                {
                    "title": title,
                    "link": link,
                    "summary": strip_html(entry.get("summary", ""))[:600],
                    "source": name,
                    "category": feed_cfg.get("category", "资讯"),
                    "section": feed_cfg.get("section", "ai"),
                    "time": ts or datetime.now(timezone.utc),
                }
            )
            count += 1
        print(f"[fetch] {name}: {count} new items", flush=True)
    if blocked:
        print(f"[info] 屏蔽词过滤 {blocked} 条（政治/台湾等）", flush=True)
    return candidates
