"""RSS 抓取：fetch_feed / fetch_candidates / matches_keywords。

从原 fetch_news.py 抽出，四版面共用。支持 feeds 项里的 section 字段。
"""

import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser
import requests

from common import link_hash, strip_html, entry_time, matches_keywords, is_blocked

DEFAULT_WORKERS = 4          # 并发抓取的站点数
DEFAULT_HOST_INTERVAL = 2.0  # 同一域名两次请求的最小间隔（秒），避免被限流
_slot_lock = threading.Lock()


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


def _reserve_host_slot(slots, url, interval):
    """同域名排队取号：不同站点并行，同站点保持最小间隔，避免触发限流。

    先占坑再睡（锁内只做记账），否则所有站点会被一把锁串起来。
    """
    if interval <= 0:
        return
    host = urlparse(url).netloc or url
    with _slot_lock:
        start = max(time.monotonic(), slots.get(host, 0.0))
        slots[host] = start + interval
    delay = start - time.monotonic()
    if delay > 0:
        time.sleep(delay)


def _fetch_one(feed_cfg, slots, host_interval):
    """并发单元：给源排队取号后抓取。"""
    _reserve_host_slot(slots, feed_cfg["url"], host_interval)
    print(f"[fetch] {feed_cfg['name']} ...", flush=True)
    return fetch_feed(feed_cfg["url"])


def _safe_fetch(feed_cfg, slots, host_interval):
    """单个源出任何意外都只算这一个源失败，不能拖垮整轮抓取。"""
    try:
        return _fetch_one(feed_cfg, slots, host_interval)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] {feed_cfg.get('name')} fetch crashed: {exc}", file=sys.stderr)
        return None


def fetch_candidates(config, seen, return_failures=False, empty_is_failure=False):
    """抓取所有源；可同时返回失败来源，供强制刷新保留旧条目。

    各源并发抓取（默认 4 个），同域名之间仍按 host_interval 间隔；
    结果按 feeds 顺序回收，保证候选顺序与串行时一致。
    """
    settings = config.get("settings", {})
    hours_window = settings.get("hours_window", 36)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_window)
    keywords = config.get("ai_keywords", [])
    block_keywords = config.get("block_keywords", [])

    feeds = list(config.get("feeds", []))
    workers = max(1, int(settings.get("fetch_workers", DEFAULT_WORKERS)))
    host_interval = float(settings.get("per_host_interval", DEFAULT_HOST_INTERVAL))
    slots = {}  # 每次运行重置，只约束同一轮里的同源请求
    if feeds:
        with ThreadPoolExecutor(max_workers=min(workers, len(feeds))) as pool:
            parsed_feeds = list(pool.map(lambda cfg: _safe_fetch(cfg, slots, host_interval), feeds))
    else:
        parsed_feeds = []

    candidates = []
    failed_sources = set()
    run_seen = set()  # 本次运行内去重
    blocked = 0
    for feed_cfg, parsed in zip(feeds, parsed_feeds):
        name = feed_cfg["name"]
        entries = list(getattr(parsed, "entries", []) or []) if parsed is not None else []
        malformed_empty = not entries and bool(getattr(parsed, "bozo", False))
        if parsed is None or malformed_empty or (empty_is_failure and not entries):
            print(f"[warn] {name} fetch failed, skipped", file=sys.stderr)
            failed_sources.add(name)
            continue

        count = 0
        for entry in entries:
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
            if feed_cfg.get("ai_filter") and not matches_keywords(entry, keywords):
                continue
            run_seen.add(h)
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
        print(f"[info] 配置的排除关键词过滤 {blocked} 条", flush=True)
    if return_failures:
        return candidates, failed_sources
    return candidates
