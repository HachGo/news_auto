"""金融市场与股市版面生成器。

四子板块：行情速览 / 宏观与政策 / 财经要闻 / 公告与研报。
各子板块独立 try/except，失败渲染占位块，不连坐。
行情/日历/公告不经 LLM；财经要闻/研报经 LLM 摘要。
"""

import sys
from datetime import date, datetime
from pathlib import Path

from common import atomic_write_text, select_items, summarize, CST
from published import load_published_post, retain_failed_source_items, seen_without_published
from sources import rss, eastmoney, jin10, cninfo

FAIL_BLOCK = "📊 数据获取失败，请稍后查看原文。"
EMPTY_CALENDAR = "今日无重要宏观数据公布。"
EMPTY_NEWS = "今日暂无新要闻。"
EMPTY_ANNOUNCE = "今日暂无新公告。"


def generate(config, seen, client, date_str, posts_dir=None, force_refresh=False):
    today = _parse_date(date_str)
    posts_dir = Path(posts_dir) if posts_dir else Path("content/market")
    path = posts_dir / f"{date_str}.md"
    existing = load_published_post(path, "market")
    if existing is not None and not force_refresh:
        print(f"[info] 复用已生成日报 {path}")
        return existing
    quotes = _safe(eastmoney.fetch_quotes, "行情速览")
    calendar = _safe(lambda: jin10.fetch_calendar(today), "宏观日历")
    announces = _safe(lambda: cninfo.fetch_announcements(limit=8), "公告")
    if existing is not None:
        quotes = existing.get("quotes", []) if quotes is None else quotes
        calendar = existing.get("calendar", []) if calendar is None else calendar
        announces = existing.get("announces", []) if announces is None else announces

    # 财经要闻 + 研报走 RSS
    market_config = _filter_section(config, "market")
    fetch_seen = seen_without_published(seen, existing) if force_refresh else seen
    if force_refresh:
        candidates, failed_sources = rss.fetch_candidates(
            market_config, fetch_seen, return_failures=True, empty_is_failure=existing is not None,
        )
    else:
        candidates = rss.fetch_candidates(market_config, fetch_seen)
        failed_sources = set()
    if not candidates and existing is not None:
        print("[warn] 市场版面强制刷新未获取到条目，保留已有日报")
        return existing
    news_items, research_items = [], []
    for c in candidates:
        if c.get("category") == "研报要点":
            research_items.append(c)
        else:
            news_items.append(c)
    # 概览即可：来源均衡选取财经要闻 8 条、研报 4 条（不做 LLM 排序，省 token）
    news_items = _select_balanced(news_items, config, 8)
    research_items = _select_balanced(research_items, config, 4)
    if existing and failed_sources:
        news_existing = {
            **existing,
            "all_rss_items": [
                item for item in existing["all_rss_items"] if item.get("category") != "研报要点"
            ],
        }
        research_existing = {
            **existing,
            "all_rss_items": [
                item for item in existing["all_rss_items"] if item.get("category") == "研报要点"
            ],
        }
        news_items = retain_failed_source_items(news_items, news_existing, failed_sources, 8)
        research_items = retain_failed_source_items(research_items, research_existing, failed_sources, 4)

    for item in news_items + research_items:
        result = summarize(client, item)
        if result:
            item.update(result)

    posts_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path, _render(date_str, quotes, calendar, announces, news_items, research_items),
    )
    print(f"[info] 市场版面已生成 {path}")
    return {"path": path, "items": news_items, "quotes": quotes,
            "calendar": calendar, "news_items": news_items,
            "announces": announces,
            "all_rss_items": news_items + research_items}  # 用于 seen 去重


def _safe(fn, label):
    try:
        return fn()
    except Exception as exc:
        print(f"[warn] {label} 生成异常: {exc}", file=sys.stderr)
        return None


def _render(date_str, quotes, calendar, announces, news_items, research_items):
    lines = [
        "---",
        f'title: "金融市场与股市 {date_str}"',
        f"date: {datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')}",
        'tags: ["每日简报"]',
        f'summary: "今日行情速览 + {len(news_items)} 条财经要闻。"',
        "---",
        "",
    ]
    # 行情速览
    lines.append("## 行情速览")
    lines.append("")
    if quotes:
        lines.append("| 指数 | 点位 | 涨跌幅 |")
        lines.append("|---|---|---|")
        for q in quotes:
            arrow = "▲" if q["change_pct"] >= 0 else "▼"
            lines.append(f"| {q['name']} | {q['price']:.2f} | {arrow}{abs(q['change_pct']):.2f}% |")
        sh = next((q for q in quotes if "上证" in q["name"]), None)
        if sh and sh.get("amount"):
            lines.append("")
            lines.append(f"沪市成交额：{sh['amount']/1e8:.0f} 亿元")
    else:
        lines.append(FAIL_BLOCK)
    lines.append("")

    # 宏观与政策：None=失败，[]=当日无数据
    lines.append("## 宏观与政策")
    lines.append("")
    if calendar is None:
        lines.append(FAIL_BLOCK)
    elif not calendar:
        lines.append(EMPTY_CALENDAR)
    else:
        lines.append("| 指标 | 预期 | 前值 | 公布值 |")
        lines.append("|---|---|---|---|")
        for c in calendar:
            lines.append(
                f"| {c['title']} | {_display(c.get('consensus'))} | "
                f"{_display(c.get('previous'))} | {_display(c.get('actual'))} |"
            )
    lines.append("")

    # 财经要闻
    lines.append("## 财经要闻")
    lines.append("")
    if news_items:
        for n, item in enumerate(news_items, 1):
            lines.extend(_render_item(item, n))
    else:
        lines.append(EMPTY_NEWS)
    lines.append("")

    # 公告与研报
    lines.append("## 公告与研报")
    lines.append("")
    if announces is None:
        lines.append("公告：")
        lines.append(FAIL_BLOCK)
        lines.append("")
    elif not announces:
        lines.append(EMPTY_ANNOUNCE)
        lines.append("")
    else:
        lines.append("**公司公告**（巨潮）")
        lines.append("")
        for a in announces:
            lines.append(f"- {a['sec_name']}：[{a['title']}]({a['url']})")
        lines.append("")
    if research_items:
        lines.append("**研报要点**")
        lines.append("")
        for n, item in enumerate(research_items, 1):
            lines.extend(_render_item(item, n))

    return "\n".join(lines)


def _render_item(item, num):
    block = []
    title_zh = item.get("title_zh") or item["title"]
    block.append(f"### {num}. {title_zh}")
    block.append("")
    summary_zh = item.get("summary_zh") or item.get("summary", "")[:200]
    if summary_zh:
        block.append(summary_zh)
        block.append("")
    block.append(f"来源：[{item['source']}]({item['link']})")
    block.append("")
    return block


def _filter_section(config, section):
    return {
        "settings": config.get("settings", {}),
        "ai_keywords": config.get("ai_keywords", []),
        "block_keywords": config.get("block_keywords", []),
        "feeds": [f for f in config.get("feeds", []) if f.get("section") == section],
    }


def _select_balanced(items, config, limit):
    settings = dict(config.get("settings", {}))
    settings["total_limit"] = limit
    return select_items(items, {"settings": settings})


def _display(value):
    return "—" if value is None or value == "" else value


def _parse_date(date_str):
    return date.fromisoformat(date_str)
