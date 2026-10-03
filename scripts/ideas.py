"""创意板块：抓取 → 屏蔽词过滤 → 模型标注 → 存储 → 跨站合并与评分 → data/radar/ideas.json。

- 每日条目存 data/ideas/<日期>.json（保留 60 天），评分与时间范围都从这份历史计算。
- 评分（与设计稿一致）：各信号先换算为该来源近 30 天内的百分位，按权重加权平均；
  再乘时间衰减（半衰期 7 天），每多出现在一个站点加 3 分。没有信号的来源记 50。
- 模型只做标注（类型、为何巧妙、适合谁、上手难度、双语标题），并剔除非创意内容；
  没有 API Key 时按来源给默认类型，“为何巧妙”用摘要兜底，不编造。
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cluster import _text, cosine, tfidf_vectors
from common import (
    CST, DEEPSEEK_MODEL, PRIVATE_RANK_RULES, atomic_write_text, has_cjk, is_blocked,
)
from sources.ideas import github, hackaday, show_hn, sspai, v2ex

SOURCE_MODULES = {"show_hn": show_hn, "github": github, "v2ex": v2ex, "hackaday": hackaday, "sspai": sspai}
SOURCES = dict(SOURCE_MODULES)  # 本次运行要抓取的来源（测试可替换）；名称一律查 SOURCE_MODULES
TYPES = ("hack", "product", "method", "wish", "design")
TYPE_NAMES = {"hack": {"zh": "技术巧思", "en": "Tech hacks"}, "product": {"zh": "新产品", "en": "New products"},
              "method": {"zh": "好方法", "en": "Clever methods"}, "wish": {"zh": "许愿", "en": "Wished-for"},
              "design": {"zh": "设计", "en": "Design"}}
DEFAULT_TYPE = {"show_hn": "hack", "github": "hack", "hackaday": "hack", "v2ex": "product", "sspai": "method"}
# 信号权重：金额与支持者 > 收藏与星标 > 点赞 > 评论（当前来源没有金额信号，保留权重备用）
WEIGHTS = {"money": 1.0, "stars": 0.8, "upvotes": 0.6, "comments": 0.4}
HALF_LIFE_DAYS = 7
SITE_BOOST = 3
NEUTRAL_PERCENTILE = 50
KEEP_DAYS = 60
PERCENTILE_DAYS = 30
RANGE_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}
EXPORT_LIMIT = 120
FETCH_LIMIT = 30
MERGE_SIMILARITY = 0.5
ENRICH_BATCH = 30

ENRICH_PROMPT = """你是创意编辑，为一个收集“好点子、好方法、好作品”的双语网站标注条目。
对下面每一条返回一个对象，只返回 JSON：
{{"ideas": [{{"index": 0, "keep": true, "type": "hack|product|method|wish|design",
"title_zh": "简洁中文标题", "title_en": "concise English title",
"why_zh": "一句话说明巧妙之处（40 字内，只依据给出的内容）", "why_en": "one line on why it is clever (under 20 words, only from the text given)",
"who_zh": "适合谁（10 字内）", "who_en": "who it is for (a few words)", "effort": 1}}]}}

type：hack=技术或硬件巧思，product=新产品/工具，method=好方法/技巧，wish=希望有人做的东西，design=设计与创意作品。
effort：1=易上手，2=中等投入，3=投入较大（指自己尝试或做出来的成本）。
keep=false：不是创意、方法或作品（如影评、片单、新闻、招聘、纯提问、广告软文）。
{private}

条目：
{lines}
"""


def run(date_str, config, client, data_dir, out_path, force_refresh=False, now=None):
    """抓取并存储当日创意，再导出评分结果。返回导出数据。"""
    data_dir = Path(data_dir)
    day_path = data_dir / f"{date_str}.json"
    previous = _load(day_path)
    if previous is not None and not force_refresh:
        print("[info] 复用已抓取的创意")
    else:
        day = collect(config, client, previous=previous, now=now)
        day["date"] = date_str
        _write_if_changed(day_path, day)
        print(f"[info] 创意已抓取 {len(day['items'])} 条")
    prune(data_dir, date_str)
    export = build_export(data_dir, date_str)
    _write_if_changed(Path(out_path), export)
    return export


def collect(config, client, previous=None, now=None, sources=None, limit=FETCH_LIMIT):
    """逐个来源抓取；单个来源失败只标记 failed，不影响其他来源。"""
    sources = sources or SOURCES
    block = config.get("block_keywords") or []
    statuses, items, seen_urls = {}, [], set()
    for key, module in sources.items():
        try:
            fetched = module.fetch(limit=limit, now=now)
        except Exception as exc:
            print(f"[error] 创意来源 {key} 抓取失败: {exc}", file=sys.stderr)
            statuses[key] = {"status": "failed", "count": 0}
            continue
        kept = 0
        for item in fetched:
            url = _canonical(item["url"])
            if url in seen_urls or is_blocked(item, block):
                continue
            seen_urls.add(url)
            items.append(item)
            kept += 1
        statuses[key] = {"status": "ok" if kept else "empty", "count": kept}
    old = {item["id"]: item for item in (previous or {}).get("items") or []}
    # 已由模型标注的条目沿用旧标注；无 Key 时的兜底标注在有 Key 的重跑中重新标注
    reusable = lambda before: before and "type" in before and (before.get("enriched") or client is None)
    fresh = [item for item in items if not reusable(old.get(item["id"]))]
    notes = enrich(client, fresh)
    output = []
    for item in items:
        before = old.get(item["id"])
        if reusable(before):
            note = {key: before[key] for key in ("type", "title", "why", "who", "effort", "enriched") if key in before}
        else:
            note = notes.get(item["id"]) or fallback(item)
        if note.get("keep") is False:
            continue
        note.pop("keep", None)
        output.append({**item, **note})
    for key, status in statuses.items():
        status["count"] = sum(item["source"] == key for item in output)
        if status["status"] == "ok" and not status["count"]:
            status["status"] = "empty"
    return {"sources": statuses, "items": output}


def fallback(item):
    """无模型时的标注：来源默认类型，摘要作“为何巧妙”，标题保留原文。"""
    title = item["title"]
    return {"type": DEFAULT_TYPE.get(item["source"], "product"),
            "title": {"zh": title, "en": title},
            "why": {"zh": item["summary"][:120] if has_cjk(item["summary"]) else "",
                    "en": "" if has_cjk(item["summary"]) else item["summary"][:160]},
            "who": None, "effort": None, "enriched": False}


def enrich(client, items):
    """批量调用模型标注；失败的批次返回空，由 fallback 兜底。"""
    if client is None or not items:
        return {}
    notes = {}
    for start in range(0, len(items), ENRICH_BATCH):
        batch = items[start:start + ENRICH_BATCH]
        lines = "\n".join(
            f"{index}. [{item['source']}] {item['title']} — {item['summary'][:200]}"
            for index, item in enumerate(batch))
        private = "\n".join(f"另外：{rule}（这类条目 keep=false）" for rule in PRIVATE_RANK_RULES)
        prompt = ENRICH_PROMPT.format(lines=lines, private=private)
        data = _chat_json(client, prompt)
        for entry in (data or {}).get("ideas") or []:
            note = _note(entry, batch)
            if note:
                notes[note.pop("id")] = note
    return notes


def _note(entry, batch):
    if not isinstance(entry, dict) or type(entry.get("index")) is not int:
        return None
    if not 0 <= entry["index"] < len(batch):
        return None
    item = batch[entry["index"]]
    if entry.get("keep") is False:
        return {"id": item["id"], "keep": False}
    text = lambda key: entry.get(key).strip() if isinstance(entry.get(key), str) else ""
    kind = entry.get("type") if entry.get("type") in TYPES else DEFAULT_TYPE.get(item["source"], "product")
    effort = entry.get("effort") if entry.get("effort") in (1, 2, 3) else None
    who = {"zh": text("who_zh"), "en": text("who_en")}
    return {"id": item["id"], "type": kind,
            "title": {"zh": text("title_zh") or item["title"], "en": text("title_en") or item["title"]},
            "why": {"zh": text("why_zh"), "en": text("why_en")},
            "who": who if who["zh"] or who["en"] else None, "effort": effort, "enriched": True}


def _chat_json(client, prompt, retries=1):
    for attempt in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}, max_tokens=8000, timeout=180,
            )
            data = json.loads(response.choices[0].message.content)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            print(f"[warn] 创意标注失败 (attempt {attempt + 1}): {exc}", file=sys.stderr)
            time.sleep(3)
    return None


# ---- 评分与导出 ----

def build_export(data_dir, date_str):
    days = load_days(Path(data_dir), date_str, PERCENTILE_DAYS)
    today = days[-1] if days and days[-1]["date"] == date_str else {"date": date_str, "sources": {}, "items": []}
    history = _history(days)
    as_of = _as_of(today, history, date_str)
    ideas = score(history, as_of)
    within = lambda idea, hours: idea["age_h"] <= hours
    return {
        "as_of": date_str,
        "ideas": ideas[:EXPORT_LIMIT],
        "stats": {"today": len(today["items"]),
                  "sources": sum(status["status"] == "ok" for status in today["sources"].values()),
                  "multi": sum(idea["n_sites"] > 1 for idea in ideas if within(idea, RANGE_HOURS["7d"]))},
        "types": {name: {kind: sum(idea["type"] == kind for idea in ideas if within(idea, hours)) for kind in TYPES}
                  for name, hours in RANGE_HOURS.items()},
        "counts": {name: sum(within(idea, hours) for idea in ideas) for name, hours in RANGE_HOURS.items()},
        "sources": [{"id": key, "name": {"zh": module.NAME, "en": getattr(module, "NAME_EN", module.NAME)},
                     "access": module.ACCESS, **today["sources"].get(key, {"status": "failed", "count": 0})}
                    for key, module in SOURCES.items()],
        "scoring": {"weights": [{"key": key, "w": weight} for key, weight in WEIGHTS.items()],
                    "half_life_days": HALF_LIFE_DAYS, "boost": SITE_BOOST},
    }


def score(history, as_of):
    """按来源百分位加权、时间衰减、跨站加分；返回按最终分降序的创意列表。"""
    pools = {}
    for item in history:
        for key, value in item["signals"].items():
            pools.setdefault((item["source"], key), []).append(value)
    for item in history:
        parts = {key: percentile(value, pools[(item["source"], key)]) for key, value in item["signals"].items()}
        weight = sum(WEIGHTS.get(key, 0) for key in parts)
        item["percentile"] = round(sum(WEIGHTS.get(key, 0) * value for key, value in parts.items()) / weight) if weight else NEUTRAL_PERCENTILE
    ideas = []
    for group in merge_groups(history):
        members = sorted(group, key=lambda item: (-item["percentile"], item["id"]))
        lead = members[0]
        published = min(_parse(item.get("published_at")) or as_of for item in members)
        age_h = max(0, round((as_of - published).total_seconds() / 3600))
        weighted = round(sum(item["percentile"] for item in members) / len(members))
        decay = round(0.5 ** (age_h / (24 * HALF_LIFE_DAYS)), 3)
        sites = sorted({item["source"] for item in members})
        boost = SITE_BOOST * (len(sites) - 1)
        ideas.append({
            "id": lead["id"], "type": lead["type"], "title": lead["title"], "why": lead["why"],
            "who": lead.get("who"), "effort": lead.get("effort"), "url": lead["url"],
            "published_at": published.isoformat(), "age_h": age_h,
            "srcs": [{"source": item["source"], "name": SOURCE_MODULES[item["source"]].NAME, "url": item["url"],
                      "signal": _main_signal(item), "p": item["percentile"]} for item in members],
            "n_sites": len(sites), "weighted": weighted, "decay": decay, "boost": boost,
            "final": round(weighted * decay + boost),
        })
    return sorted(ideas, key=lambda idea: (-idea["final"], idea["age_h"], idea["id"]))


def percentile(value, values):
    """中位秩百分位：严格小于的个数 + 相等个数的一半；单一样本为 50。"""
    if not values:
        return NEUTRAL_PERCENTILE
    below = sum(other < value for other in values)
    equal = sum(other == value for other in values)
    return round(100 * (below + equal / 2) / len(values))


def merge_groups(items):
    """跨站重复：规范化链接相同，或不同来源的英文“标题 + 摘要”相似度 ≥ 阈值。"""
    parent = list(range(len(items)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    urls = {}
    for index, item in enumerate(items):
        url = _canonical(item["url"])
        if url in urls:
            parent[find(index)] = find(urls[url])
        else:
            urls[url] = index
    vectors = tfidf_vectors([_text(item["title"]["en"], item["summary"]) for item in items])
    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            if items[left]["source"] != items[right]["source"] and cosine(vectors[left], vectors[right]) >= MERGE_SIMILARITY:
                parent[find(right)] = find(left)
    groups = {}
    for index in range(len(items)):
        groups.setdefault(find(index), []).append(items[index])
    return list(groups.values())


def load_days(folder, date_str, days):
    start = (date.fromisoformat(date_str) - timedelta(days=days - 1)).isoformat()
    output = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        if start <= path.stem <= date_str:
            payload = _load(path)
            if payload:
                output.append({"date": path.stem, "sources": payload.get("sources") or {}, "items": payload.get("items") or []})
    return output


def prune(folder, date_str, keep_days=KEEP_DAYS):
    cutoff = (date.fromisoformat(date_str) - timedelta(days=keep_days)).isoformat()
    for path in Path(folder).glob("*.json"):
        if path.stem < cutoff:
            path.unlink()


def _history(days):
    """同一条目多日出现时取最新信号，保留首次出现日期。"""
    merged = {}
    for day in days:
        for item in day["items"]:
            first = merged.get(item["id"], {}).get("first_seen", day["date"])
            merged[item["id"]] = {**item, "first_seen": first}
    return list(merged.values())


def _as_of(today, history, date_str):
    """计算年龄的参考时刻：当日最新条目的发布时间（可复现，重跑不改写导出）。"""
    times = [_parse(item.get("published_at")) for item in today["items"]]
    times = [value for value in times if value]
    if times:
        return max(times)
    return datetime.combine(date.fromisoformat(date_str), datetime.max.time(), CST).astimezone(timezone.utc)


def _main_signal(item):
    for key in ("money", "stars", "upvotes", "comments"):
        if key in item["signals"]:
            return {"kind": key, "value": item["signals"][key]}
    return None


def _canonical(url):
    url = re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower())
    return url.split("#")[0].rstrip("/")


def _parse(value):
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_if_changed(path, payload):
    text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    atomic_write_text(path, text)
    return True
