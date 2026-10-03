"""实验室（Lab）：按 scripts/trackers.yaml 的关键词长期跟踪人物、公司与领域。

语料是本站已存储的全部新闻：content/{ai,world,market}/<日期>.md（中文日报，含原文标题与来源；
英文标题取自同日 .en.md 的同一锚点），以及 data/brief/<日期>.json 中合并进事件的其他来源报道。
同一链接只计一次。跟踪器 since 之前的数据是从存档回填的，导出时标注 backfilled。

不做的部分（没有数据源）：即将发生的事件、发射计划表、各国发射占比。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import yaml

from common import atomic_write_text, has_cjk, item_id
from published import load_published_post

SECTIONS = {"ai": "ai_tech", "world": "world", "market": "finance"}
WINDOW_DAYS = 30
TIMELINE_LIMIT = 30
EN_HEADING = re.compile(r"^###\s+\d+\.\s+(.+?)\s+\{#(i-[0-9a-f]+)\}\s*$", re.M)


def matches(text, aliases):
    """英文别名按单词边界（不区分大小写，“SpaceX”不会命中“SpaceXAI”），中文别名按子串。"""
    for alias in aliases:
        alias = str(alias).strip()
        if not alias:
            continue
        if has_cjk(alias):
            if alias in text:
                return True
        elif re.search(r"(?<![\w])" + re.escape(alias) + r"(?![\w])", text, re.I):
            return True
    return False


def load_trackers(path):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data.get("trackers") or []


def corpus(root, date_str, days=WINDOW_DAYS * 2):
    """近 days 天已存储的新闻条目：{date, section, field, title{zh,en}, text, link, source, lang, reports}。"""
    root = Path(root)
    end = date.fromisoformat(date_str)
    items, seen, by_link = [], set(), {}
    for offset in range(days - 1, -1, -1):
        day = (end - timedelta(days=offset)).isoformat()
        brief = _read(root / "data" / "brief" / f"{day}.json")
        reports = {event.get("id"): event.get("reports") or [] for event in brief.get("events") or []}
        for section, field in SECTIONS.items():
            path = root / "content" / section / f"{day}.md"
            try:
                post = load_published_post(path, section)
            except ValueError:
                post = None
            if not post:
                continue
            english = _english_titles(path.with_name(f"{day}.en.md"))
            for item in post.get("items") or []:
                link = item.get("link") or ""
                anchor = item_id(item)
                if link in by_link and anchor in english and has_cjk(by_link[link]["title"]["en"]):
                    by_link[link]["title"]["en"] = english[anchor]  # 同一报道出现在多个版面时补上英文标题
                    by_link[link]["text"] += " " + english[anchor]
                if not link or link in seen:
                    continue
                seen.add(link)
                original = item.get("title") or ""
                zh = item.get("title_zh") or original
                en = english.get(anchor) or (original if not has_cjk(original) else zh)
                extra = [r for r in reports.get(anchor, []) if r.get("link") and r["link"] != link]
                items.append({
                    "date": day, "section": section, "field": field, "link": link,
                    "source": item.get("source") or "", "lang": "zh" if has_cjk(original) else "en",
                    "title": {"zh": zh, "en": en},
                    # 只比对标题：摘要里“发布在 X 上”这类顺带提及会带来大量误报
                    "text": " ".join([original, zh, en] + [r.get("title") or "" for r in extra]),
                    "reports": 1 + len(extra),
                })
                by_link[link] = items[-1]
                seen.update(r["link"] for r in extra)
    return items


def build_lab(trackers, items, date_str, trend_entries=()):
    end = date.fromisoformat(date_str)
    days = [(end - timedelta(days=offset)).isoformat() for offset in range(WINDOW_DAYS - 1, -1, -1)]
    week = days[-7:]
    previous_week = [(end - timedelta(days=offset)).isoformat() for offset in range(13, 6, -1)]
    output = []
    for tracker in trackers:
        since = str(tracker.get("since") or date_str)
        if tracker.get("type") == "entities":
            groups = {entity["id"]: entity for entity in tracker.get("entities") or []}
        else:
            groups = {tracker["id"]: {"id": tracker["id"], "name": tracker["name"], "aliases": tracker.get("keywords") or []}}
        matched = []
        for item in items:
            hits = [key for key, group in groups.items() if matches(item["text"], group.get("aliases") or [])]
            if hits:
                matched.append({**item, "hits": hits})
        recent = [item for item in matched if item["date"] in days]
        langs = Counter(item["lang"] for item in recent)
        entry = {
            "id": tracker["id"], "type": tracker.get("type"), "name": tracker["name"], "since": since,
            "keywords": [alias for group in groups.values() for alias in group.get("aliases") or []],
            "stats": {"m7": sum(item["date"] in week for item in matched), "m30": len(recent),
                      "sources": len({item["source"] for item in recent if item["source"]}),
                      "en": langs.get("en", 0), "zh": langs.get("zh", 0)},
            "backfilled": since > days[0],
            "timeline": [{
                "date": item["date"], "entities": [{"id": key, "name": groups[key]["name"]} for key in item["hits"]] if tracker.get("type") == "entities" else [],
                "title": item["title"], "link": item["link"], "source": item["source"], "field": item["field"],
                "reports": item["reports"], "backfilled": item["date"] < since,
            } for item in sorted(recent, key=lambda item: (item["date"], item["link"]), reverse=True)[:TIMELINE_LIMIT]],
        }
        if tracker.get("type") == "entities":
            entry["entities"] = []
            for key, group in groups.items():
                own = [item for item in matched if key in item["hits"]]
                series = [sum(item["date"] == day for item in own) for day in days]
                m7, before = sum(item["date"] in week for item in own), sum(item["date"] in previous_week for item in own)
                latest = max((item for item in own if item["date"] in days), key=lambda item: (item["date"], item["link"]), default=None)
                peak = max(series) or 1
                entry["entities"].append({
                    "id": key, "name": group["name"], "m7": m7, "m30": sum(series),
                    "change": round((m7 / before - 1) * 100) if before else None,
                    "spark": [round(100 * value / peak) for value in series],
                    "latest": {"title": latest["title"], "link": latest["link"], "date": latest["date"]} if latest else None,
                })
            entry["entities"].sort(key=lambda item: (-item["m30"], item["id"]))
        else:
            aliases = groups[tracker["id"]]["aliases"]
            entry["rising"] = [{"id": trend["id"], "name": trend["name"], "z": trend["z"], "field": trend["field"]}
                               for trend in trend_entries
                               if trend.get("z", 0) > 0 and any(matches(" ".join(r["title"].values()), aliases) for r in trend.get("related") or [])]
        output.append(entry)
    return {"as_of": date_str, "trackers": output}


def write_lab(root, date_str, config_path, out_path):
    root = Path(root)
    trends = _read(root / "data" / "radar" / "trends.json").get("entries") or []
    payload = build_lab(load_trackers(config_path), corpus(root, date_str), date_str, trends)
    text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    out_path = Path(out_path)
    if not out_path.exists() or out_path.read_text(encoding="utf-8") != text:
        atomic_write_text(out_path, text)
    return payload


def _english_titles(path):
    try:
        return {anchor: title for title, anchor in EN_HEADING.findall(Path(path).read_text(encoding="utf-8"))}
    except OSError:
        return {}


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
