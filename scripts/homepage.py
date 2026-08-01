"""首页今日总览生成。

跨版面取今日焦点 3 条（AI/国际/市场各一），下方各版面摘要卡片。
市场焦点：优先财经要闻最高分；无要闻取行情首条指数。
"""

from datetime import datetime
from pathlib import Path

from common import CST

SECTION_NAMES = {
    "ai": "AI 与科技社区",
    "world": "国际与深度",
    "market": "市场与宏观",
}


def build_homepage(sections, date_str):
    lines = [
        "---",
        'title: "首页"',
        'layout: "home"',
        f"date: {datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')}",
        'summary: "今日三大版面总览。"',
        "---",
        "",
        "## 今日焦点",
        "",
    ]
    focus_items = []
    for key in ("ai", "world", "market"):
        sec = sections.get(key)
        if not sec:
            continue
        item = _pick_focus(sec, key)
        if item:
            focus_items.append((sec["name"], item))

    if focus_items:
        for name, item in focus_items:
            title = item.get("title_zh") or item.get("title", "")
            lines.append(f"- **{title}** 〔{name}〕")
    else:
        lines.append("- 今日暂无焦点条目")
    lines.append("")

    lines.append("## 各版面")
    lines.append("")
    for key in ("ai", "world", "market"):
        sec = sections.get(key)
        name = SECTION_NAMES[key]
        if sec:
            lines.append(f"### {name}")
            lines.append("")
            lines.append(f"今日 {sec.get('count', 0)} 条 · {_one_liner(sec, key)}")
            lines.append(f"[查看全文 →]({sec['url']})")
            lines.append("")
        else:
            lines.append(f"### {name}")
            lines.append("")
            lines.append(f"今日生成异常，[查看历史 →](/{key}/)")
            lines.append("")

    return "\n".join(lines)


def _pick_focus(sec, key):
    items = sec.get("items") or []
    if key == "market" and not items:
        quotes = sec.get("quotes") or []
        if quotes:
            q = quotes[0]
            return {"title": f"{q['name']} {q['price']:.2f} ({q['change_pct']:+.2f}%)"}
        return None
    if not items:
        return None
    ranked = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    return ranked[0]


def _one_liner(sec, key):
    items = sec.get("items") or []
    if not items:
        if key == "market":
            quotes = sec.get("quotes") or []
            if quotes:
                return f"焦点：{quotes[0]['name']} {quotes[0]['change_pct']:+.2f}%"
        return "今日无要闻"
    titles = [i.get("title_zh") or i.get("title", "") for i in items[:2]]
    return "焦点：" + "、".join(titles) + "…"
