"""把每日快照聚合成周、月、季度和年度数据。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from statistics import mean

from .config import PERIOD_REQUIREMENTS, TOPICS


def load_daily(directory: Path, start: date, end: date) -> list[dict]:
    rows = []
    cursor = start
    while cursor <= end:
        path = directory / f"{cursor.isoformat()}.json"
        if path.exists():
            try:
                import json
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        cursor += timedelta(days=1)
    return rows


def period_bounds(period: str, end_date: date) -> tuple[date, date]:
    days = PERIOD_REQUIREMENTS[period]["days"]
    return end_date - timedelta(days=days - 1), end_date


def aggregate(period: str, end_date: date, daily_rows: list[dict]) -> dict:
    if period not in PERIOD_REQUIREMENTS:
        raise ValueError(f"unknown period: {period}")
    start, end = period_bounds(period, end_date)
    expected_days = (end - start).days + 1
    news_days = sum(1 for row in daily_rows if row.get("news_signals"))
    market_sessions = len({quote.get("trading_date") for row in daily_rows for quote in row.get("market_quotes", []) if quote.get("trading_date")})
    ratio = min(1.0, len(daily_rows) / expected_days)
    requirement = PERIOD_REQUIREMENTS[period]
    warnings = []
    if news_days < requirement["min_news_days"]:
        warnings.append(f"news coverage {news_days}/{requirement['min_news_days']}")
    if market_sessions < requirement["min_market_sessions"]:
        warnings.append(f"market sessions {market_sessions}/{requirement['min_market_sessions']}")
    quality_ratio = min(ratio, news_days / max(requirement["min_news_days"], 1), market_sessions / max(requirement["min_market_sessions"], 1))
    quality = "ok" if not warnings else ("partial" if daily_rows else "unavailable")
    topics = _aggregate_topics(daily_rows)
    market = _aggregate_market(daily_rows)
    return {
        "schema_version": 1,
        "period": period,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "sample_days": len(daily_rows),
        "news_days": news_days,
        "market_sessions": market_sessions,
        "data_quality": {"status": quality, "ratio": round(max(0.0, min(1.0, quality_ratio)), 4), "warnings": warnings},
        "topics": topics,
        "market": market,
        "evidence": _evidence(daily_rows),
    }


def _aggregate_topics(rows):
    output = {}
    for key, spec in TOPICS.items():
        activities = [row.get("topic_metrics", {}).get(key, {}).get("activity", 0.0) for row in rows]
        counts = [row.get("topic_metrics", {}).get(key, {}).get("event_count", 0) for row in rows]
        source_counts = [row.get("topic_metrics", {}).get(key, {}).get("source_count", 0) for row in rows]
        output[key] = {
            "name": spec["name"],
            "activity": round(sum(activities), 6),
            "average_daily_activity": round(mean(activities), 6) if activities else 0,
            "peak_daily_activity": round(max(activities), 6) if activities else 0,
            "event_count": sum(counts),
            "source_count_peak": max(source_counts) if source_counts else 0,
            "momentum": _momentum(activities),
        }
    return output


def _aggregate_market(rows):
    values = [row.get("market_metrics", {}).get("cross_asset_momentum") for row in rows]
    values = [value for value in values if value is not None]
    breadth = [row.get("market_metrics", {}).get("breadth") for row in rows]
    breadth = [value for value in breadth if value is not None]
    risks = [row.get("market_metrics", {}).get("news_risk", 0) for row in rows]
    return {
        "momentum": round(mean(values), 6) if values else None,
        "latest_momentum": values[-1] if values else None,
        "average_breadth": round(mean(breadth), 6) if breadth else None,
        "news_risk": round(sum(risks), 6),
    }


def _momentum(values):
    if len(values) < 2:
        return None
    short = values[-min(7, len(values)):]
    long = values[-min(28, len(values)):]
    return round(mean(short) - mean(long), 6)


def _evidence(rows):
    evidence = []
    for row in rows:
        for item in row.get("news_signals", [])[:10]:
            evidence.append({"date": row.get("date"), "title": item.get("title"), "link": item.get("link"), "topics": item.get("topics", []), "importance": item.get("importance", 0)})
    return sorted(evidence, key=lambda item: (item.get("importance", 0), item.get("date", "")), reverse=True)[:20]
