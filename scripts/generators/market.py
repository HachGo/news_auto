"""金融市场与股市版面生成器。

四子板块：行情速览 / 宏观与政策 / 财经要闻 / 公告与研报。
各子板块独立 try/except，失败渲染占位块，不连坐。
行情/日历/公告不经 LLM；财经要闻/研报经 LLM 摘要。
"""

import sys
from datetime import date, datetime
from pathlib import Path

from common import (
    atomic_write_text, select_items, summarize, translate_lines, CST,
    item_id, title_en, summary_en,
)
from published import load_published_post, retain_failed_source_items, seen_without_published
from sources import rss, eastmoney, jin10, cninfo

FAIL_BLOCK = "📊 数据获取失败，请稍后查看原文。"
EMPTY_CALENDAR = "今日无重要宏观数据公布。"
EMPTY_NEWS = "今日暂无新要闻。"
EMPTY_ANNOUNCE = "今日暂无新公告。"

# 行情表英文名（东方财富返回中文名）；首页 / 英文版共用
QUOTE_NAMES_EN = {
    "上证指数": "SSE Composite",
    "深证成指": "SZSE Component",
    "创业板指": "ChiNext",
    "恒生指数": "Hang Seng",
    "恒生科技": "Hang Seng Tech",
    "标普500": "S&P 500",
    "纳斯达克": "Nasdaq",
    "道琼斯": "Dow Jones",
    "黄金": "Gold",
    "原油": "Crude oil",
    "VIX": "VIX",
}

# 英文版各段文案：键与中文版一一对应
LABELS = {
    "zh": {
        "title": "金融市场与股市 {date}", "tags": "每日简报",
        "summary": "今日行情速览 + {n} 条财经要闻。",
        "quotes": "行情速览", "quote_head": "| 指数 | 点位 | 涨跌幅 |", "turnover": "沪市成交额：{v:.0f} 亿元",
        "macro": "宏观与政策", "macro_head": "| 指标 | 预期 | 前值 | 公布值 |",
        "news": "财经要闻", "filings": "公告与研报", "filings_label": "公告：",
        "announces": "**公司公告**（巨潮）", "research": "**研报要点**",
        "fail": FAIL_BLOCK, "empty_calendar": EMPTY_CALENDAR, "empty_news": EMPTY_NEWS,
        "empty_announce": EMPTY_ANNOUNCE, "source": "来源",
    },
    "en": {
        "title": "Finance {date}", "tags": "Daily brief",
        "summary": "Market snapshot + {n} finance stories.",
        "quotes": "Market snapshot", "quote_head": "| Index | Level | Change |",
        "turnover": "Shanghai turnover: CNY {bn:.1f}bn",
        "macro": "Macro & policy", "macro_head": "| Indicator | Forecast | Previous | Actual |",
        "news": "Finance news", "filings": "Filings & research", "filings_label": "Filings:",
        "announces": "**Company filings** (CNINFO, titles in Chinese)", "research": "**Research notes**",
        "fail": "📊 Data unavailable; please check the original sources.",
        "empty_calendar": "No major macro releases today.", "empty_news": "No new finance stories today.",
        "empty_announce": "No new filings today.", "source": "Source",
    },
}


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
    calendar_en = None
    if calendar:
        titles = translate_lines(client, [c["title"] for c in calendar])
        if titles:
            calendar_en = [{**c, "title": t} for c, t in zip(calendar, titles)]
    atomic_write_text(
        path.with_name(f"{date_str}.en.md"),
        _render(
            date_str, quotes, calendar_en or calendar, announces, news_items, research_items,
            lang="en",
        ),
    )
    print(f"[info] 市场版面已生成 {path}")
    return {"path": path, "items": news_items, "quotes": quotes,
            "calendar": calendar, "news_items": news_items,
            "announces": announces,
            "all_rss_items": news_items + research_items, "candidates": candidates}  # 用于 seen 去重


def _safe(fn, label):
    try:
        return fn()
    except Exception as exc:
        print(f"[warn] {label} 生成异常: {exc}", file=sys.stderr)
        return None


def _render(date_str, quotes, calendar, announces, news_items, research_items, lang="zh"):
    t = LABELS[lang]
    lines = [
        "---",
        f'title: "{t["title"].format(date=date_str)}"',
        f"date: {datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f'tags: ["{t["tags"]}"]',
        f'summary: "{t["summary"].format(n=len(news_items))}"',
        "---",
        "",
    ]
    # 行情速览
    lines.append(f"## {t['quotes']}")
    lines.append("")
    if quotes:
        lines.append(t["quote_head"])
        lines.append("|---|---|---|")
        for q in quotes:
            arrow = "▲" if q["change_pct"] >= 0 else "▼"
            name = QUOTE_NAMES_EN.get(q["name"], q["name"]) if lang == "en" else q["name"]
            lines.append(f"| {name} | {q['price']:.2f} | {arrow}{abs(q['change_pct']):.2f}% |")
        sh = next((q for q in quotes if "上证" in q["name"]), None)
        if sh and sh.get("amount"):
            lines.append("")
            lines.append(t["turnover"].format(v=sh["amount"] / 1e8, bn=sh["amount"] / 1e9))
    else:
        lines.append(t["fail"])
    lines.append("")

    # 宏观与政策：None=失败，[]=当日无数据
    lines.append(f"## {t['macro']}")
    lines.append("")
    if calendar is None:
        lines.append(t["fail"])
    elif not calendar:
        lines.append(t["empty_calendar"])
    else:
        lines.append(t["macro_head"])
        lines.append("|---|---|---|---|")
        for c in calendar:
            lines.append(
                f"| {c['title']} | {_display(c.get('consensus'))} | "
                f"{_display(c.get('previous'))} | {_display(c.get('actual'))} |"
            )
    lines.append("")

    # 财经要闻
    lines.append(f"## {t['news']}")
    lines.append("")
    if news_items:
        for n, item in enumerate(news_items, 1):
            lines.extend(_render_item(item, n, lang))
    else:
        lines.append(t["empty_news"])
    lines.append("")

    # 公告与研报
    lines.append(f"## {t['filings']}")
    lines.append("")
    if announces is None:
        lines.append(t["filings_label"])
        lines.append(t["fail"])
        lines.append("")
    elif not announces:
        lines.append(t["empty_announce"])
        lines.append("")
    else:
        lines.append(t["announces"])
        lines.append("")
        for a in announces:
            lines.append(f"- {a['sec_name']}：[{a['title']}]({a['url']})")
        lines.append("")
    if research_items:
        lines.append(t["research"])
        lines.append("")
        for n, item in enumerate(research_items, 1):
            lines.extend(_render_item(item, n, lang))

    return "\n".join(lines)


def _render_item(item, num, lang="zh"):
    block = []
    anchor = f" {{#{item_id(item)}}}"
    if lang == "en":
        title, summary = title_en(item), summary_en(item)
    else:
        title = item.get("title_zh") or item["title"]
        summary = item.get("summary_zh") or item.get("summary", "")[:200]
    block.append(f"### {num}. {title}{anchor}")
    block.append("")
    if summary:
        block.append(summary)
        block.append("")
    separator = ": " if lang == "en" else "："
    block.append(f"{LABELS[lang]['source']}{separator}[{item['source']}]({item['link']})")
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
