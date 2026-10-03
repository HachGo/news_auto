"""今日简报数据（首页 World Radar）。

把各版面结果整理成一份结构化 JSON：data/brief/YYYY-MM-DD.json，由 Hugo 首页模板
（site.Data.brief）渲染，中英文共用。

- events：AI / 国际 / 市场三版面条目，按重要性排序。暂未做跨来源事件合并，每条一个来源。
- deep：深度阅读精选。
- rising：话题热度、行情涨幅相对近 30 日基线的 z 值（纯统计，不经模型）。
- forecasts / track_record：趋势模块的规则预测与历史命中情况。
- sections：各版面当日状态（ready / empty / failed），首页据此区分“暂无”和“异常”。

同日重跑复用已发布日报时，条目由 Markdown 回读，缺少分数、时间和英文；此时按条目 ID
沿用同日旧简报中的记录，保证排序与英文内容不退化，内容不变时也不改写文件。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev

from common import atomic_write_text, category_en, has_cjk, item_id, strip_html, summary_en, title_en
from generators.market import QUOTE_NAMES_EN
from trends.config import TOPICS
from trends.forecast import SCENARIO_EN

SCHEMA_VERSION = 1
FIELD_BY_SECTION = {"ai": "ai_tech", "world": "world", "market": "finance"}
BASELINE_DAYS = 30
MIN_BASELINE_DAYS = 7
SPARK_DAYS = 14
RISING_LIMIT = 5


def build_brief(results, date_str, generated_at, trend_dir=None, previous=None, statuses=None):
    """results 为各版面生成器返回值（ai/world/market/deep）；previous 为同日旧简报。"""
    old = _previous_entries(previous)
    events = []
    for section in ("ai", "world", "market"):
        for item in (results.get(section) or {}).get("items") or []:
            events.append(_merge(_event(item, section), item, old))
    deep = [_merge(_deep(item), item, old) for item in (results.get("deep") or {}).get("items") or []]
    events.sort(key=lambda event: (-event["score"], -_timestamp(event["published_at"])))

    trend_dir = Path(trend_dir) if trend_dir else None
    rows = _load_daily(trend_dir / "daily", date_str) if trend_dir else []
    return {
        "schema": SCHEMA_VERSION,
        "date": date_str,
        "generated_at": generated_at,
        "events": events,
        "deep": deep,
        "quotes": [_quote(quote) for quote in (results.get("market") or {}).get("quotes") or []],
        "rising": rising(rows),
        "forecasts": _forecasts(trend_dir, date_str) if trend_dir else [],
        "track_record": _track_record(trend_dir) if trend_dir else {"resolved": 0, "correct": 0},
        "stats": _stats(events, deep),
        "sections": dict(statuses or {}),
    }


def write_brief(path, brief, previous=None):
    """内容未变时保留旧文件（含原更新时间），同日无变化的重跑不产生提交。"""
    if previous and _without_time(previous) == _without_time(brief):
        return False
    atomic_write_text(Path(path), json.dumps(brief, ensure_ascii=False, indent=1) + "\n")
    return True


def load_brief(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def importance_dots(score):
    """1–10 分映射为 1–5 个重要性圆点。"""
    return max(1, min(5, round(score / 2)))


def rising(rows, limit=RISING_LIMIT):
    """当日相对近 30 日基线明显走高的信号：AI 话题热度与行情涨幅，按 z 值降序。"""
    if len(rows) < MIN_BASELINE_DAYS + 1:
        return []
    signals = []
    for key, spec in TOPICS.items():
        series = [_topic_activity(row, key) for row in rows]
        z = _zscore(series[-1], series[-(BASELINE_DAYS + 1):-1], floor=0.1)
        if z is not None:
            signals.append({
                "id": key,
                "kind": "topic",
                "field": "ai_tech",
                "name": {"zh": spec["name"], "en": spec.get("name_en", spec["name"])},
                "z": z,
                "value": round(series[-1], 2),
                "bars": _bars(series[-SPARK_DAYS:]),
            })
    for quote in rows[-1].get("market_quotes") or []:
        name = quote.get("name")
        changes = [_quote_field(row, name, "change_pct") for row in rows]
        history = [value for value in changes[-(BASELINE_DAYS + 1):-1] if value is not None]
        z = _zscore(changes[-1], history, floor=0.25)
        if z is not None:
            prices = [_quote_field(row, name, "price") for row in rows][-SPARK_DAYS:]
            signals.append({
                "id": f"quote-{name}",
                "kind": "market",
                "field": "finance",
                "name": {"zh": name, "en": QUOTE_NAMES_EN.get(name, name)},
                "z": z,
                "value": round(changes[-1], 2),
                "bars": _bars(prices, relative=True),
            })
    rising_only = [signal for signal in signals if signal["z"] > 0]
    return sorted(rising_only, key=lambda signal: -signal["z"])[:limit]


def _event(item, section):
    original = strip_html(item.get("title") or "")
    summary = item.get("summary") or ""
    return {
        "id": item_id(item),
        "field": FIELD_BY_SECTION[section],
        "section": section,
        "category": {"zh": item.get("category") or "", "en": category_en(item.get("category") or "")},
        "score": float(_score(item)),
        "importance": importance_dots(_score(item)),
        "title": {"zh": item.get("title_zh") or original, "en": title_en(item)},
        "summary": {"zh": item.get("summary_zh") or summary[:200], "en": summary_en(item)},
        "source": item.get("source") or "",
        "lang": "zh" if has_cjk(original) else "en",
        "link": item.get("link") or "",
        "published_at": _iso(item.get("time") or item.get("published_at")),
    }


def _deep(item):
    return {
        "id": item_id(item),
        "category": {"zh": item.get("category") or "", "en": category_en(item.get("category") or "")},
        "title": {"zh": item.get("title_zh") or item.get("title") or "", "en": title_en(item)},
        "summary": {
            "zh": item.get("summary_zh") or (item.get("summary") or "")[:280],
            "en": summary_en(item, 280),
        },
        "source": item.get("source") or "",
        "link": item.get("link") or "",
    }


def _previous_entries(previous):
    if not previous:
        return {}
    return {entry["id"]: entry for entry in (previous.get("events") or []) + (previous.get("deep") or [])}


def _merge(entry, item, old):
    """回读条目（无抓取时间）整条沿用旧记录；新抓条目只在缺英文时补回英文。"""
    before = old.get(entry["id"])
    if not before:
        return entry
    if not isinstance(item.get("time"), datetime):
        return before
    if not entry["summary"]["en"] and before.get("summary", {}).get("en"):
        entry["summary"]["en"] = before["summary"]["en"]
    if entry["title"]["en"] == entry["title"]["zh"] and before.get("title", {}).get("en"):
        entry["title"]["en"] = before["title"]["en"]
    return entry


def _score(item):
    for key in ("score", "importance"):
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 1 <= value <= 10:
            return value
    return 5


def _quote(quote):
    return {
        "name": {"zh": quote.get("name"), "en": QUOTE_NAMES_EN.get(quote.get("name"), quote.get("name"))},
        "price": quote.get("price"),
        "change_pct": quote.get("change_pct"),
    }


def _stats(events, deep):
    fields = {field: 0 for field in FIELD_BY_SECTION.values()}
    for event in events:
        fields[event["field"]] += 1
    sources = {entry["source"] for entry in events + deep if entry["source"]}
    return {"events": len(events), "deep": len(deep), "sources": len(sources), "fields": fields}


def _forecasts(trend_dir, date_str):
    folder = trend_dir / "forecasts"
    candidates = sorted(path for path in folder.glob("*.json") if path.stem <= date_str) if folder.exists() else []
    if not candidates:
        return []
    try:
        payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    output = []
    for forecast in payload.get("forecasts") or []:
        scenarios = [
            {
                "name": {"zh": s.get("name", ""), "en": s.get("name_en") or SCENARIO_EN.get(s.get("name"), s.get("name", ""))},
                "direction": s.get("direction"),
                "description": {
                    "zh": s.get("description", ""),
                    "en": s.get("description_en") or SCENARIO_EN.get(s.get("description"), s.get("description", "")),
                },
            }
            for s in forecast.get("scenarios") or []
        ]
        drivers = [
            {"zh": d.get("name", ""), "en": d.get("name_en") or TOPICS.get(d.get("topic"), {}).get("name_en", d.get("name", ""))}
            for d in forecast.get("drivers") or []
        ]
        output.append({
            "horizon": forecast.get("horizon"),
            "direction": forecast.get("direction"),
            "confidence": forecast.get("confidence"),
            "target_date": forecast.get("target_date"),
            "scenarios": scenarios,
            "drivers": drivers,
        })
    return output


def _track_record(trend_dir):
    counts = {"correct": 0, "incorrect": 0}
    folder = trend_dir / "evaluations"
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for evaluation in payload.get("evaluations") or []:
            if evaluation.get("status") in counts:
                counts[evaluation["status"]] += 1
    return {"resolved": counts["correct"] + counts["incorrect"], "correct": counts["correct"]}


def _load_daily(folder, date_str):
    rows = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        if path.stem > date_str:
            continue
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return rows[-(BASELINE_DAYS + 1):]


def _topic_activity(row, key):
    value = (row.get("topic_metrics") or {}).get(key, {}).get("activity")
    return float(value) if isinstance(value, (int, float)) else 0.0


def _quote_field(row, name, field):
    for quote in row.get("market_quotes") or []:
        if quote.get("name") == name and isinstance(quote.get(field), (int, float)):
            return float(quote[field])
    return None


def _zscore(value, history, floor):
    """value 相对 history 的 z 值；样本不足返回 None。标准差设下限，避免平稳序列被放大。"""
    if value is None or len(history) < MIN_BASELINE_DAYS:
        return None
    spread = max(pstdev(history), abs(mean(history)) * 0.25, floor)
    return round(max(-9.9, min(9.9, (value - mean(history)) / spread)), 1)


def _bars(values, relative=False):
    """迷你柱高（0–100）：热度按最大值缩放；价格按区间缩放并留底，便于看出起伏。"""
    known = [value for value in values if value is not None]
    if not known:
        return []
    high, low = max(known), min(known)
    bars = []
    for value in values:
        if value is None:
            bars.append(0)
        elif relative:
            bars.append(round(20 + 80 * (value - low) / (high - low)) if high > low else 60)
        else:
            bars.append(round(100 * value / high) if high > 0 else 0)
    return bars


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value if isinstance(value, str) and value else None


def _timestamp(value):
    try:
        return datetime.fromisoformat(value).timestamp() if value else 0
    except ValueError:
        return 0


def _without_time(brief):
    return {key: value for key, value in brief.items() if key != "generated_at"}
