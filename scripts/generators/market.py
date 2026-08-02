"""市场与宏观版面生成器。

四子板块：行情速览 / 宏观与政策 / 财经要闻 / 公告与研报。
各子板块独立 try/except，失败渲染占位块，不连坐。
行情/日历/公告不经 LLM；财经要闻/研报经 LLM 摘要。
"""

import sys
from datetime import date, datetime
from pathlib import Path

from common import summarize, CST
from sources import rss, eastmoney, jin10, cninfo

FAIL_BLOCK = "📊 数据获取失败，请稍后查看原文。"
EMPTY_CALENDAR = "今日无重要宏观数据公布。"
EMPTY_NEWS = "今日暂无新要闻。"
EMPTY_ANNOUNCE = "今日暂无新公告。"


def generate(config, seen, client, date_str, posts_dir=None):
    today = _parse_date(date_str)
    quotes = _safe(eastmoney.fetch_quotes, "行情速览")
    calendar = _safe(lambda: jin10.fetch_calendar(today), "宏观日历")
    announces = _safe(lambda: cninfo.fetch_announcements(limit=8), "公告")

    # 财经要闻 + 研报走 RSS
    market_config = _filter_section(config, "market")
    candidates = rss.fetch_candidates(market_config, seen)
    news_items, research_items = [], []
    for c in candidates:
        if c.get("category") == "研报要点":
            research_items.append(c)
        else:
            news_items.append(c)
    # 概览即可：财经要闻取前 8 条、研报取前 4 条（不做 LLM 重要性排序，省 token）
    news_items = news_items[:8]
    research_items = research_items[:4]

    for item in news_items + research_items:
        result = summarize(client, item)
        if result:
            item.update(result)

    posts_dir = Path(posts_dir) if posts_dir else Path("content/market")
    posts_dir.mkdir(parents=True, exist_ok=True)
    path = posts_dir / f"{date_str}.md"
    path.write_text(_render(date_str, quotes, calendar, announces, news_items, research_items),
                    encoding="utf-8")
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
        f'title: "市场与宏观 {date_str}"',
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
            lines.append(f"| {c['title']} | {c.get('consensus') or '—'} | {c.get('previous') or '—'} | {c.get('actual') or '—'} |")
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
        "feeds": [f for f in config.get("feeds", []) if f.get("section") == section],
    }


def _parse_date(date_str):
    return date.fromisoformat(date_str)
