"""首页今日总览生成。

跨版面取今日焦点（AI/国际/市场/深度各一），下方 2×2 版面入口。
市场焦点：优先财经要闻最高分；无要闻取行情首条指数。
"""

from datetime import datetime
from html import escape

from common import CST

SECTION_NAMES = {
    "ai": "AI与科技",
    "world": "国际资讯",
    "market": "金融市场与股市",
    "deep": "深度阅读与学习",
}

SECTION_ORDER = ("ai", "world", "market", "deep")


def build_homepage(sections, date_str):
    lines = [
        "---",
        'title: "首页"',
        'layout: "home"',
        f"date: {datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')}",
        'summary: "今日四版面总览。"',
        "---",
        "",
        '<div class="home-overview">',
        "",
        '<section class="home-focus">',
        "",
        "## 今日焦点",
        "",
        '<ul class="focus-track">',
        "",
    ]

    focus_items = []
    for key in SECTION_ORDER:
        sec = sections.get(key)
        if not sec:
            continue
        item = _pick_focus(sec, key)
        if item:
            focus_items.append((key, sec, item))

    if focus_items:
        for key, sec, item in focus_items:
            title = item.get("title_zh") or item.get("title", "")
            url = sec.get("url") or f"/{key}/"
            name = SECTION_NAMES[key]
            lines.append(f'<li class="focus-item focus-{key}">')
            lines.append(f'<span class="focus-label">{escape(name)}</span>')
            lines.append(
                f'<a class="focus-title" href="{escape(url, quote=True)}">'
                f"{escape(title)}</a>"
            )
            lines.append("</li>")
            lines.append("")
    else:
        lines.append('<li class="focus-item focus-empty">今日暂无焦点条目</li>')
        lines.append("")

    lines.extend([
        "</ul>",
        "",
        "</section>",
        "",
        '<section class="home-sections">',
        "",
        "## 各版面",
        "",
        '<div class="section-grid">',
        "",
    ])

    for key in SECTION_ORDER:
        sec = sections.get(key)
        name = SECTION_NAMES[key]
        if sec:
            url = sec.get("url") or f"/{key}/"
            blurb = _section_blurb(sec, key)
            extra_class = " section-card-deep" if key == "deep" else ""
            lines.append(
                f'<a class="section-card section-{key}{extra_class}" '
                f'href="{escape(url, quote=True)}">'
            )
            lines.append(f"<h3>{escape(name)}</h3>")
            if key == "market":
                quote_line = _quote_summary(sec)
                if quote_line:
                    lines.append(f'<p class="section-quotes">{escape(quote_line)}</p>')
            lines.append(f'<p class="section-blurb">{escape(blurb)}</p>')
            lines.append('<span class="section-more">查看全文</span>')
            lines.append("</a>")
            lines.append("")
        else:
            lines.append(f'<a class="section-card section-{key} is-empty" href="/{key}/">')
            lines.append(f"<h3>{escape(name)}</h3>")
            lines.append('<p class="section-blurb">今日生成异常，查看历史</p>')
            lines.append('<span class="section-more">查看历史</span>')
            lines.append("</a>")
            lines.append("")

    lines.extend([
        "</div>",
        "",
        "</section>",
        "",
        "</div>",
        "",
    ])
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


def _section_blurb(sec, key):
    items = sec.get("items") or []
    if not items:
        if key == "market":
            quotes = sec.get("quotes") or []
            if quotes:
                return f"行情速览 · {quotes[0]['name']} {quotes[0]['change_pct']:+.2f}%"
        return "今日无要闻"
    titles = [i.get("title_zh") or i.get("title", "") for i in items[:2]]
    prefix = "精选" if key == "deep" else "焦点"
    joined = "、".join(t for t in titles if t)
    if key == "deep" and items:
        # 深度入口用略长导语
        first = items[0]
        summary = (first.get("summary_zh") or "")[:80]
        if summary:
            return summary + ("…" if len(first.get("summary_zh") or "") > 80 else "")
    return f"今日 {sec.get('count', len(items))} 条 · {prefix}：{joined}…"


def _quote_summary(sec):
    quotes = sec.get("quotes") or []
    if not quotes:
        return ""
    preferred = ("上证", "纳斯达克", "恒生")
    picked = []
    for needle in preferred:
        for q in quotes:
            if needle in q["name"] and q not in picked:
                picked.append(q)
                break
        if len(picked) >= 2:
            break
    if not picked:
        picked = quotes[:2]
    parts = []
    for q in picked:
        arrow = "▲" if q["change_pct"] >= 0 else "▼"
        short = q["name"].replace("指数", "")
        parts.append(f"{short} {arrow}{abs(q['change_pct']):.2f}%")
    return " · ".join(parts)
