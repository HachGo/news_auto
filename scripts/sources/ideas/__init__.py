"""创意来源适配器：每个来源一个模块，暴露 fetch(limit) -> 标准化条目列表。

只用官方 API 或 RSS（不抓网页、无需账号）；只保存链接与短摘要。
条目结构：{id, source, url, title, summary, lang, published_at, signals}，
signals 只含该来源真实提供的信号（upvotes / comments / stars）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import requests

from common import has_cjk, strip_html

SUMMARY_CHARS = 300
USER_AGENT = "news_auto/1.0 (+https://github.com/HachGo/news_auto)"


def get(url, headers=None, retries=2, timeout=20):
    """GET 并返回 Response；失败时记录来源 URL 与错误后抛出，由调用方标记来源失败。"""
    merged = {"User-Agent": USER_AGENT, **(headers or {})}
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=merged, timeout=timeout)
            if response.status_code == 429 and attempt < retries:
                print(f"[warn] 429 rate limited, retry: {url}", file=sys.stderr)
                time.sleep(10 * (attempt + 1))
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            print(f"[warn] idea fetch error ({exc}), attempt {attempt + 1}: {url}", file=sys.stderr)
            if attempt == retries:
                raise
            time.sleep(3)
    raise RuntimeError(f"unreachable: {url}")


def make_item(source, native_id, url, title, summary, published_at, signals):
    title = strip_html(title)
    summary = strip_html(summary)[:SUMMARY_CHARS]
    return {
        "id": f"{source}:{native_id}",
        "source": source,
        "url": url,
        "title": title,
        "summary": summary,
        "lang": "zh" if has_cjk(title) else "en",
        "published_at": published_at,
        "signals": {key: int(value) for key, value in signals.items() if value is not None},
    }


def cli(fetch, description):
    """各适配器的命令行入口：--limit N 限制条数，--dry-run 只打印不写盘（适配器本身从不写盘）。"""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", help="只打印结果（适配器不写文件）")
    args = parser.parse_args()
    for item in fetch(limit=args.limit):
        print(json.dumps(item, ensure_ascii=False))
