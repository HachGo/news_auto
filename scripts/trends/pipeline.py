"""趋势模块编排入口。"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .aggregate import aggregate, load_daily
from .config import PIPELINE_VERSION, SCHEMA_VERSION
from .deduplicate import cluster_news
from .features import compute_daily_features
from .forecast import generate_forecasts
from .forecast import evaluate_forecast
from .normalize import normalize_news, normalize_quote
from .schema import validate_daily, validate_forecast, validate_period


def run(date_str: str, sections: dict, data_dir: str | Path, export_dir: str | Path | None = None) -> dict:
    data_dir = Path(data_dir)
    daily_dir = data_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    snapshot = capture(date_str, sections)
    validate_daily(snapshot)
    _write_json(daily_dir / f"{date_str}.json", snapshot)

    end_date = date.fromisoformat(date_str)
    period_rows = {}
    for period_name in ("week", "month", "quarter", "year"):
        start_date = _period_start(period_name, end_date)
        rows = load_daily(daily_dir, start_date, end_date)
        period = aggregate(period_name, end_date, rows)
        period["series"] = _series(rows)
        validate_period(period)
        period_rows[period_name] = period
        _write_json(data_dir / f"{period_name}ly" / f"{date_str}.json", period)

    evaluations = _evaluate_due(data_dir, end_date, period_rows)
    forecasts = []
    for period_name, period in period_rows.items():
        forecasts.extend(generate_forecasts(period))
    for forecast in forecasts:
        validate_forecast(forecast)
    _write_json(data_dir / "forecasts" / f"{date_str}.json", {"date": date_str, "forecasts": forecasts})
    _write_json(data_dir / "evaluations" / f"{date_str}.json", {"date": date_str, "evaluations": evaluations})
    if export_dir:
        export_payload(period_rows, snapshot, forecasts, Path(export_dir), evaluations)
    return {"snapshot": snapshot, "periods": period_rows, "forecasts": forecasts, "evaluations": evaluations}


def capture(date_str: str, sections: dict) -> dict:
    as_of = datetime.now(timezone.utc).isoformat()
    news_items = []
    for section in ("ai", "market"):
        result = sections.get(section) or {}
        for item in result.get("items", []):
            news_items.append(normalize_news(item, section, as_of))
        for item in result.get("news_items", []):
            news_items.append(normalize_news(item, section, as_of))
    news_items = cluster_news(news_items)

    market_result = sections.get("market") or {}
    quotes = [normalize_quote(item, date_str) for item in (market_result.get("quotes") or [])]
    macro = list(market_result.get("calendar") or [])
    features = compute_daily_features(news_items, quotes, macro)
    statuses = {
        "news": "ok" if news_items else "unavailable",
        "market": "ok" if quotes else "unavailable",
        "macro": "ok" if "calendar" in market_result and market_result.get("calendar") is not None else "unavailable",
    }
    ratio = sum(value == "ok" for value in statuses.values()) / len(statuses)
    return {
        "schema_version": SCHEMA_VERSION,
        "date": date_str,
        "generated_at": as_of,
        "pipeline_version": PIPELINE_VERSION,
        "coverage": {**statuses, "overall_ratio": ratio},
        "news_signals": news_items,
        "market_quotes": quotes,
        "macro_events": macro,
        **features,
        "data_warnings": _warnings(statuses, quotes),
    }


def export_payload(periods, snapshot, forecasts, export_dir: Path, evaluations=None):
    export_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"as_of": snapshot["date"], "periods": list(periods), "forecast_count": len(forecasts), "schema_version": SCHEMA_VERSION}
    _write_json(export_dir / "manifest.json", manifest)
    _write_json(export_dir / "latest.json", {"snapshot": snapshot, "periods": periods, "forecasts": forecasts, "evaluations": evaluations or []})
    for key, value in periods.items():
        _write_json(export_dir / f"{key}.json", value)


def _warnings(statuses, quotes):
    warnings = [f"{key} data unavailable" for key, value in statuses.items() if value != "ok"]
    if any(quote.get("is_stale") for quote in quotes):
        warnings.append("one or more market quotes are stale")
    return warnings


def _series(rows):
    points = []
    for row in sorted(rows, key=lambda value: value.get("date", "")):
        topics = row.get("topic_metrics", {}).values()
        activities = [item.get("activity", 0) for item in topics]
        topic_total = sum(activities)
        market = row.get("market_metrics", {}).get("cross_asset_momentum")
        points.append({
            "date": row.get("date"),
            "technology": round(topic_total, 6),
            "market": market,
            "coverage": row.get("coverage", {}).get("overall_ratio", 0),
        })
    return points


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _period_start(period, end_date):
    days = {"week": 7, "month": 30, "quarter": 91, "year": 365}[period]
    from datetime import timedelta
    return end_date - timedelta(days=days - 1)


def _evaluate_due(data_dir: Path, end_date: date, periods: dict) -> list[dict]:
    """读取旧预测并写入独立评估结果，旧预测文件本身保持不可变。"""
    forecast_dir = data_dir / "forecasts"
    if not forecast_dir.exists():
        return []
    evaluated_ids = set()
    evaluation_dir = data_dir / "evaluations"
    if evaluation_dir.exists():
        for evaluation_path in evaluation_dir.glob("*.json"):
            try:
                old = json.loads(evaluation_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            evaluated_ids.update(item.get("forecast_id") for item in old.get("evaluations", []))
    results = []
    for path in sorted(forecast_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for forecast in payload.get("forecasts", []):
            if forecast.get("status") != "open":
                continue
            if forecast.get("forecast_id") in evaluated_ids:
                continue
            target_date = forecast.get("target_date")
            if not target_date or target_date > end_date.isoformat():
                continue
            period = periods.get(forecast.get("horizon"))
            evaluated = evaluate_forecast(forecast, period)
            results.append(evaluated)
    return results
