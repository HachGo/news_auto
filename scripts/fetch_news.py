#!/usr/bin/env python3
"""每日资讯抓取脚本。

流程：读取 feeds.yaml -> 抓取 RSS -> 关键词过滤 -> seen.json 去重
     -> DeepSeek 翻译+摘要 -> 生成 content/posts/YYYY-MM-DD.md -> 更新 seen.json
"""

import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml
from dateutil import parser as dtparser

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = Path(__file__).resolve().parent / "feeds.yaml"
SEEN_FILE = ROOT / "data" / "seen.json"
POSTS_DIR = ROOT / "content" / "posts"

CST = timezone(timedelta(hours=8))  # 北京时间

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")


def load_config():
    with open(FEEDS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_seen():
    if SEEN_FILE.exists():
        with open(SEEN_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(seen):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # 只保留最近 30 天的指纹，防止文件无限增长
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=0, sort_keys=True)


def link_hash(link: str) -> str:
    return hashlib.sha1(link.encode("utf-8")).hexdigest()


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def entry_time(entry):
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            try:
                dt = dtparser.parse(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, OverflowError):
                continue
    return None


def matches_keywords(entry, keywords):
    text = " ".join(
        [entry.get("title", ""), strip_html(entry.get("summary", ""))]
    ).lower()
    for kw in keywords:
        kw_l = kw.lower()
        # 短关键词（如 AI）用单词边界匹配，避免误伤 (e.g. "aid")
        if len(kw_l) <= 4:
            if re.search(r"\b" + re.escape(kw_l) + r"\b", text):
                return True
        elif kw_l in text:
            return True
    return False


def fetch_candidates(config, seen):
    settings = config.get("settings", {})
    hours_window = settings.get("hours_window", 36)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_window)
    keywords = config.get("ai_keywords", [])

    candidates = []
    for feed_cfg in config.get("feeds", []):
        name = feed_cfg["name"]
        print(f"[fetch] {name} ...", flush=True)
        try:
            parsed = feedparser.parse(
                feed_cfg["url"],
                request_headers={"User-Agent": "Mozilla/5.0 (news_auto bot)"},
            )
        except Exception as exc:  # 网络异常不应中断整体流程
            print(f"[warn] {name} fetch failed: {exc}", file=sys.stderr)
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
            if link_hash(link) in seen:
                continue
            if feed_cfg.get("ai_filter") and not matches_keywords(entry, keywords):
                continue
            candidates.append(
                {
                    "title": title,
                    "link": link,
                    "summary": strip_html(entry.get("summary", ""))[:600],
                    "source": name,
                    "category": feed_cfg.get("category", "资讯"),
                    "time": ts or datetime.now(timezone.utc),
                }
            )
            count += 1
        print(f"[fetch] {name}: {count} new items", flush=True)
    return candidates


def select_items(candidates, config):
    """按来源均衡挑选，最多 total_limit 条。"""
    settings = config.get("settings", {})
    total_limit = settings.get("total_limit", 15)
    per_source_limit = settings.get("per_source_limit", 4)

    candidates.sort(key=lambda x: x["time"], reverse=True)

    selected, per_source = [], {}
    # 轮询各来源，保证来源多样性
    by_source = {}
    for item in candidates:
        by_source.setdefault(item["source"], []).append(item)

    sources = list(by_source.keys())
    idx = 0
    while len(selected) < total_limit and sources:
        src = sources[idx % len(sources)]
        pool = by_source[src]
        if pool and per_source.get(src, 0) < per_source_limit:
            item = pool.pop(0)
            selected.append(item)
            per_source[src] = per_source.get(src, 0) + 1
            idx += 1
        else:
            sources.remove(src)
            if sources:
                idx %= len(sources)
    selected.sort(key=lambda x: (x["category"], x["time"]), reverse=False)
    return selected


def build_llm_client():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("[warn] DEEPSEEK_API_KEY 未设置，跳过 LLM，使用 RSS 原始摘要", file=sys.stderr)
        return None
    try:
        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    except Exception as exc:
        print(f"[warn] 初始化 LLM 客户端失败: {exc}", file=sys.stderr)
        return None


PROMPT_TMPL = """你是新闻编辑。请将下面这条英文新闻翻译并总结，返回 JSON（不要包含其他文字）：
{{"title_zh": "中文标题", "summary_zh": "中文摘要，2-3句话，120字以内，客观精炼"}}

英文标题: {title}
英文内容: {summary}
"""


def summarize(client, item, retries=2):
    """调用 DeepSeek 生成中文标题与摘要；失败时降级为原始内容。"""
    if client is None:
        return None
    prompt = PROMPT_TMPL.format(title=item["title"], summary=item["summary"][:500])
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=400,
                timeout=60,
                # V4 默认开启 thinking 模式，翻译摘要任务无需推理，关闭以省时省钱
                extra_body={"thinking": {"type": "disabled"}},
            )
            data = json.loads(resp.choices[0].message.content)
            title_zh = str(data.get("title_zh", "")).strip()
            summary_zh = str(data.get("summary_zh", "")).strip()
            if title_zh and summary_zh:
                return {"title_zh": title_zh, "summary_zh": summary_zh}
        except Exception as exc:
            print(f"[warn] LLM 调用失败 (attempt {attempt + 1}): {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def render_post(items, date_cst):
    date_str = date_cst.strftime("%Y-%m-%d")
    lines = [
        "---",
        f'title: "每日资讯 {date_str}"',
        f"date: {date_cst.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        'tags: ["每日简报"]',
        f'summary: "今日精选 {len(items)} 条国际新闻与 AI 动态。"',
        "---",
        "",
    ]

    by_category = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item)

    # AI 动态放前面
    order = sorted(by_category.keys(), key=lambda c: (c != "AI 动态", c))
    for category in order:
        lines.append(f"## {category}")
        lines.append("")
        for i, item in enumerate(by_category[category], 1):
            title_zh = item.get("title_zh") or item["title"]
            lines.append(f"### {i}. {title_zh}")
            lines.append("")
            if item.get("title_zh"):
                lines.append(f"> {item['title']}")
                lines.append("")
            summary_zh = item.get("summary_zh") or item["summary"][:200]
            if summary_zh:
                lines.append(summary_zh)
                lines.append("")
            lines.append(f"来源：[{item['source']}]({item['link']})")
            lines.append("")
    return "\n".join(lines)


def main():
    config = load_config()
    seen = load_seen()

    candidates = fetch_candidates(config, seen)
    print(f"[info] 候选条目: {len(candidates)}")
    if not candidates:
        print("[info] 没有新条目，跳过生成")
        return

    selected = select_items(candidates, config)
    print(f"[info] 精选条目: {len(selected)}")

    client = build_llm_client()
    for item in selected:
        result = summarize(client, item)
        if result:
            item.update(result)
        time.sleep(0.5)

    now_cst = datetime.now(CST)
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    post_path = POSTS_DIR / f"{now_cst.strftime('%Y-%m-%d')}.md"
    post_path.write_text(render_post(selected, now_cst), encoding="utf-8")
    print(f"[info] 已生成 {post_path}")

    now_iso = datetime.now(timezone.utc).isoformat()
    for item in selected:
        seen[link_hash(item["link"])] = now_iso
    save_seen(seen)
    print("[info] seen.json 已更新")


if __name__ == "__main__":
    main()
