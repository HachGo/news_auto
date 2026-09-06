"""复用已生成的日报，从现有 Markdown 恢复首页和去重所需的信息。

正文是唯一持久化来源；兼容已有日报，无需新增状态文件或重新调用模型。
"""

import re
from html import unescape
from pathlib import Path

import yaml

from common import link_hash, strip_html


def load_published_post(path, section):
    path = Path(path)
    if not path.exists():
        return None

    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n(.*)", text, re.S)
    if not match:
        raise ValueError(f"已有日报缺少完整 front matter，保留文件待检查: {path}")
    metadata = yaml.safe_load(match[1])
    body = match[2]
    if not isinstance(metadata, dict) or not metadata.get("title") or not body.strip():
        raise ValueError(f"已有日报内容不完整，保留文件待检查: {path}")

    items = []
    category = "资讯"
    quotes = []
    calendar = []
    announces = []
    for block in re.split(r"(?=^#{2,3} )", body, flags=re.M):
        if block.startswith("## "):
            category = block.split("\n", 1)[0][3:].strip()
            if section == "market" and category == "行情速览":
                quotes = _read_quotes(block)
            elif section == "market" and category == "宏观与政策":
                calendar = _read_calendar(block)
            elif section == "market" and category == "公告与研报":
                announces = _read_announces(block)
            continue
        heading = re.match(r"### \d+\. ([^\n]+)", block)
        source = re.search(r"^来源：\[([^\n]*)\]\(([^\n]+)\)[ \t]*$", block, re.M)
        if source is None and section == "deep":
            source = re.search(
                r'<p class="deep-source"><a href="([^"]+)">([^<]+)</a></p>', block,
            )
        if not heading or not source:
            continue
        title = heading[1].strip()
        source_name, source_link = (
            (source[2], source[1]) if section == "deep" else (source[1], source[2])
        )
        source_name = unescape(source_name)
        source_link = unescape(source_link)
        summary_lines = [
            strip_html(line.strip()) for line in block[heading.end():source.start()].splitlines()
            if line.strip()
            and not line.lstrip().startswith(">")
            and "deep-dek" not in line
            and "<article" not in line
        ]
        item_category = category
        if category == "今日焦点":
            item_category = "AI 动态" if section == "ai" else "国际新闻"
        elif section == "market" and category == "公告与研报":
            item_category = "研报要点"
        elif section == "deep" and category == "今日精选":
            item_category = "深度精选"
        item = {
            "title": title.removeprefix("【重点】"),
            "source": source_name,
            "link": source_link,
            "category": item_category,
            "summary": "\n".join(summary_lines),
        }
        if title.startswith("【重点】"):
            item["score"] = 9
        items.append(item)

    news = [i for i in items if i["category"] == "财经要闻"] if section == "market" else items
    return {
        "path": path,
        "items": news,
        "all_rss_items": items,
        "quotes": quotes,
        "calendar": calendar,
        "announces": announces,
    }


def seen_without_published(seen, published):
    """返回 seen 副本，并允许本次刷新重新获取当天已发布的链接。"""
    filtered = dict(seen)
    if not published:
        return filtered
    for item in published.get("all_rss_items", []):
        link = item.get("link")
        if link:
            filtered.pop(link_hash(link), None)
    return filtered


def retain_failed_source_items(selected, published, failed_sources, limit):
    """在条数上限内保留抓取失败来源的已发布条目。"""
    if not published or not failed_sources:
        return selected
    selected_links = {item.get("link") for item in selected}
    retained = [
        item.copy() for item in published.get("all_rss_items", [])
        if item.get("source") in failed_sources and item.get("link") not in selected_links
    ]
    if not retained:
        return selected
    retained = retained[:limit]
    return selected[:max(0, limit - len(retained))] + retained


def _read_quotes(block):
    """读取生成器的行情表，仅恢复首页焦点所需的点位与涨跌幅。"""
    quotes = []
    for name, price, direction, pct in re.findall(
        r"^\|\s*([^|]+?)\s*\|\s*(\d+(?:\.\d+)?)\s*\|\s*([▲▼])(\d+(?:\.\d+)?)%\s*\|",
        block, re.M,
    ):
        quotes.append({
            "name": name.strip(),
            "price": float(price),
            "change_pct": float(pct) * (-1 if direction == "▼" else 1),
        })
    amount = re.search(r"^沪市成交额：([\d.]+) 亿元[ \t]*$", block, re.M)
    if amount:
        sh = next((quote for quote in quotes if "上证" in quote["name"]), None)
        if sh is not None:
            sh["amount"] = float(amount[1]) * 1e8
    return quotes


def _read_calendar(block):
    rows = []
    for line in block.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or cells[0] == "指标" or set(cells[0]) <= {"-", ":"}:
            continue
        rows.append({
            "title": cells[0],
            "consensus": _table_value(cells[1]),
            "previous": _table_value(cells[2]),
            "actual": _table_value(cells[3]),
        })
    return rows


def _read_announces(block):
    return [
        {"sec_name": name.strip(), "title": title.strip(), "url": url.strip()}
        for name, title, url in re.findall(r"^- (.+?)：\[(.+?)\]\((.+?)\)[ \t]*$", block, re.M)
    ]


def _table_value(value):
    return "" if value == "—" else value
