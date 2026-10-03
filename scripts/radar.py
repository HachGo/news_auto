"""话题趋势与规则预测的公共统计和展示数据。

趋势条目三类：AI 话题（趋势快照热度）、行情（日涨跌幅）、创意类别（data/ideas 每日新增条数，
满 8 天历史后出现）。z ≥ 2 且有相关条目的项附“为何上升”模型解释（explain.py，无 Key 时不出现）。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from statistics import mean, pstdev

from common import atomic_write_text
from generators.market import QUOTE_NAMES_EN
from trends.config import TOPICS
from trends.forecast import SCENARIO_EN, INVALIDATION_EN, REASON_EN

MIN_BASELINE_DAYS = 7
HORIZONS = ("week", "month", "quarter", "year")


def baseline_spread(history, floor):
    """基线离散范围，与 z 值使用同一尺度。"""
    return max(pstdev(history), abs(mean(history)) * 0.25, floor)


def load_daily(folder, date_str, days=31):
    folder = Path(folder)
    rows = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        if path.stem > date_str:
            continue
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return rows[-days:]


def topic_activity(row, key):
    value = (row.get("topic_metrics") or {}).get(key, {}).get("activity")
    return float(value) if isinstance(value, (int, float)) else 0.0


def quote_field(row, name, field):
    for quote in row.get("market_quotes") or []:
        if quote.get("name") == name and isinstance(quote.get(field), (int, float)):
            return float(quote[field])
    return None


def zscore(value, history, floor):
    """value 相对 history 的 z 值；样本不足返回 None。标准差设下限，避免平稳序列被放大。"""
    if value is None or len(history) < MIN_BASELINE_DAYS:
        return None
    spread = baseline_spread(history, floor)
    return round(max(-9.9, min(9.9, (value - mean(history)) / spread)), 1)


def bars(values, relative=False):
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



def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _latest_forecasts(trend_dir, date_str):
    paths = sorted(path for path in (Path(trend_dir) / "forecasts").glob("*.json") if path.stem <= date_str)
    forecasts = _read_json(paths[-1]).get("forecasts") or [] if paths else []
    return sorted(forecasts, key=lambda item: HORIZONS.index(item.get("horizon")) if item.get("horizon") in HORIZONS else len(HORIZONS))


def forecast_entry(f):
    """预测展示字段统一补齐中英文。"""
    created = f.get("data_snapshot") or (f.get("created_at") or "")[:10]
    return {
        "horizon": f.get("horizon"), "direction": f.get("direction"), "confidence": f.get("confidence"),
        "created": created, "target_date": f.get("target_date"),
        "drivers": [{"topic": d.get("topic"), "name": {"zh": d.get("name") or "", "en": d.get("name_en") or TOPICS.get(d.get("topic"), {}).get("name_en", d.get("name") or "")}, "momentum": d.get("momentum")} for d in f.get("drivers") or []],
        "scenarios": [{"name": {"zh": s.get("name", ""), "en": s.get("name_en") or SCENARIO_EN.get(s.get("name"), s.get("name", ""))},
                       "direction": s.get("direction"), "description": {"zh": s.get("description", ""), "en": s.get("description_en") or SCENARIO_EN.get(s.get("description"), s.get("description", ""))}} for s in f.get("scenarios") or []],
        "invalidation": [{"zh": text, "en": INVALIDATION_EN.get(text, text)} for text in f.get("invalidation_conditions") or []],
        "reason": {"zh": f.get("reason") or "", "en": REASON_EN.get(f.get("reason"), f.get("reason") or "")},
    }


def _rate(items):
    correct = sum(item["correct"] for item in items)
    return {"resolved": len(items), "correct": correct, "rate": round(100 * correct / len(items)) if items else None}


def build_forecasts(trend_dir, date_str):
    """整理最新预测和全部已评估记录，不引入运行时间。"""
    opened = []
    for forecast in _latest_forecasts(trend_dir, date_str):
        entry = forecast_entry(forecast)
        entry["days_left"] = (date.fromisoformat(entry["target_date"]) - date.fromisoformat(date_str)).days if entry["target_date"] else None
        opened.append(entry)
    unique = {}
    for path in sorted((Path(trend_dir) / "evaluations").glob("*.json")):
        for f in _read_json(path).get("evaluations") or []:
            if f.get("status") not in ("correct", "incorrect"):
                continue
            unique[f["forecast_id"]] = {
                "id": f["forecast_id"], "horizon": f.get("horizon"),
                "created": f.get("data_snapshot") or (f.get("created_at") or "")[:10],
                "target_date": f.get("target_date"), "direction": f.get("direction"),
                "confidence": f.get("confidence"), "observed": (f.get("realized_result") or {}).get("direction"),
                "correct": f["status"] == "correct",
            }
    resolved = sorted(unique.values(), key=lambda item: item["target_date"] or "", reverse=True)
    record = {**_rate(resolved), "open": len(opened), "by_horizon": []}
    for horizon in HORIZONS:
        items = [item for item in resolved if item["horizon"] == horizon]
        if items:
            record["by_horizon"].append({"horizon": horizon, **_rate(items)})
    calibration = []
    for confidence in ("low", "medium", "high"):
        stats = _rate([item for item in resolved if item["confidence"] == confidence])
        calibration.append({"confidence": confidence, "n": stats.pop("resolved"), **stats})
    return {"as_of": date_str, "open": opened, "resolved": resolved[:50], "record": record, "calibration": calibration}


def _chart(rows, series, history, floor, rising):
    """预计算正负柱、零线和基线带的百分比位置。"""
    center, spread = mean(history), baseline_spread(history, floor)
    values = series[-30:]
    low = min([0, center - spread] + [value for value in values if value is not None])
    high = max([center + spread] + [value for value in values if value is not None])
    position = lambda value: (value - low) / (high - low) * 100
    zero = position(0)
    chart_bars = []
    for i, (row, value) in enumerate(zip(rows[-30:], values)):
        endpoint = zero if value is None else position(value)
        chart_bars.append({"d": row["date"], "v": value, "b": min(zero, endpoint), "h": abs(endpoint - zero), "recent": rising and i >= len(values) - 3})
    dates = [row["date"] for row in rows[-30:]]
    return {"bars": chart_bars, "band": {"b": position(center - spread), "h": 2 * spread / (high - low) * 100},
            "zero": zero, "dates": [dates[0], dates[len(dates) // 2], dates[-1]]}


def _related(rows, key):
    unique = {}
    for row in rows[-7:]:
        for signal in row.get("news_signals") or []:
            if key not in (signal.get("topics") or []):
                continue
            candidate = {"title": {"zh": signal.get("title") or "", "en": signal.get("title_en") or signal.get("title") or ""},
                         "link": signal.get("link") or "", "source": signal.get("source") or "", "date": row["date"]}
            rank = (signal.get("importance") or 0, row["date"])
            identity = signal.get("id") or signal.get("link") or signal.get("title")
            if identity not in unique or rank > unique[identity][0]:
                unique[identity] = (rank, candidate)
    return [candidate for _, candidate in sorted(unique.values(), key=lambda item: item[0], reverse=True)[:5]]


def build_trends(trend_dir, date_str):
    """将近月真实快照转换为话题和行情探查数据。"""
    rows = load_daily(Path(trend_dir) / "daily", date_str, 31)
    output = {"as_of": date_str, "window": 30, "rising_z": 2.0, "entries": []}
    if len(rows) < 8:
        return output
    forecasts = _latest_forecasts(trend_dir, date_str)
    for key, spec in TOPICS.items():
        series = [topic_activity(row, key) for row in rows]
        history = series[-31:-1]
        z = zscore(series[-1], history, .1)
        if z is None:
            continue
        earlier = sum(series[-14:-7])
        metrics = (rows[-1].get("topic_metrics") or {}).get(key) or {}
        output["entries"].append({
            "id": key, "kind": "topic", "field": "ai_tech", "name": {"zh": spec["name"], "en": spec.get("name_en", spec["name"])},
            "z": z, "rising": z >= 2, "spark": bars(series[-14:]),
            "stats": [{"k": "heat", "v": f"{series[-1]:.2f}"}, {"k": "mean", "v": f"{mean(history):.2f}"},
                      {"k": "change_7d", "v": f"{(sum(series[-7:]) / earlier - 1) * 100:+.0f}%" if earlier else "—"},
                      {"k": "mentions", "v": f"{metrics.get('event_count', 0)} · {metrics.get('source_count', 0)}"}],
            "chart": _chart(rows, series, history, .1, z >= 2), "related": _related(rows, key),
            "forecasts": list(dict.fromkeys(f.get("horizon") for f in forecasts if any(d.get("topic") == key for d in f.get("drivers") or []))),
        })
    for quote in rows[-1].get("market_quotes") or []:
        name = quote.get("name")
        changes = [quote_field(row, name, "change_pct") for row in rows]
        history = [value for value in changes[-31:-1] if value is not None]
        z = zscore(changes[-1], history, .25)
        if z is None:
            continue
        prices = [quote_field(row, name, "price") for row in rows]
        earlier = prices[-8] if len(prices) >= 8 else None
        current = prices[-1]
        output["entries"].append({
            "id": f"quote-{name}", "kind": "market", "field": "finance", "name": {"zh": name, "en": QUOTE_NAMES_EN.get(name, name)},
            "z": z, "rising": z >= 2, "spark": bars(prices[-14:], relative=True),
            "stats": [{"k": "change", "v": f"{changes[-1]:+.2f}%"}, {"k": "mean", "v": f"{mean(history):+.2f}%"},
                      {"k": "change_7d", "v": f"{(current / earlier - 1) * 100:+.0f}%" if earlier and current is not None else "—"},
                      {"k": "price", "v": f"{current:.2f}" if current is not None else "—"}],
            "chart": _chart(rows, changes, history, .25, z >= 2), "related": [], "forecasts": [],
        })
    output["entries"].sort(key=lambda entry: -entry["z"])
    return output


IDEA_FLOOR = 1.0  # 创意条数的离散下限：一条之差不应被放大成显著上升


def build_idea_trends(ideas_dir, date_str):
    """创意类别：每日新抓条数相对近 30 日基线的 z 值；历史不足 8 天时为空。"""
    from ideas import SOURCE_MODULES, TYPE_NAMES, TYPES
    days = []
    for path in sorted(Path(ideas_dir).glob("*.json")) if ideas_dir and Path(ideas_dir).exists() else []:
        if path.stem <= date_str:
            payload = _read_json(path)
            days.append({"date": path.stem, "items": payload.get("items") or []})
    days = days[-31:]
    if len(days) < 8:
        return []
    entries = []
    for kind in TYPES:
        series = [float(sum(item.get("type") == kind for item in day["items"])) for day in days]
        history = series[-31:-1]
        z = zscore(series[-1], history, IDEA_FLOOR)
        if z is None or not any(series):
            continue
        earlier = sum(series[-14:-7])
        today = [item for item in days[-1]["items"] if item.get("type") == kind]
        related = []
        for day in reversed(days[-7:]):
            for item in day["items"]:
                if item.get("type") == kind and item["url"] not in {entry["link"] for entry in related}:
                    title = item.get("title") if isinstance(item.get("title"), dict) else {"zh": item.get("title", ""), "en": item.get("title", "")}
                    related.append({"title": title, "link": item["url"], "date": day["date"],
                                    "source": SOURCE_MODULES[item["source"]].NAME if item.get("source") in SOURCE_MODULES else item.get("source", "")})
        entries.append({
            "id": f"idea-{kind}", "kind": "idea", "field": "ai_tech", "name": TYPE_NAMES[kind],
            "z": z, "rising": z >= 2, "spark": bars(series[-14:]),
            "stats": [{"k": "ideas_today", "v": str(int(series[-1]))}, {"k": "mean", "v": f"{mean(history):.1f}"},
                      {"k": "change_7d", "v": f"{(sum(series[-7:]) / earlier - 1) * 100:+.0f}%" if earlier else "—"},
                      {"k": "sources_today", "v": str(len({item.get("source") for item in today}))}],
            "chart": _chart(days, series, history, IDEA_FLOOR, z >= 2), "related": related[:5], "forecasts": [],
        })
    return entries


def write_radar(trend_dir, date_str, out_dir, ideas_dir=None, client=None):
    """仅在内容变化时原子写入两份展示数据。"""
    from explain import attach_explanations
    trends = build_trends(trend_dir, date_str)
    trends["entries"] = sorted(trends["entries"] + build_idea_trends(ideas_dir, date_str), key=lambda entry: -entry["z"])
    attach_explanations(trends["entries"], client, Path(out_dir) / "explanations" / f"{date_str}.json")
    changed = {}
    for name, payload in (("trends", trends), ("forecasts", build_forecasts(trend_dir, date_str))):
        path = Path(out_dir) / f"{name}.json"
        text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
        changed[name] = not path.exists() or path.read_text(encoding="utf-8") != text
        if changed[name]:
            atomic_write_text(path, text)
    return changed
