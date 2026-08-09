"""每日科技与市场特征。"""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import median

from .config import MARKET_COMPONENT_WEIGHTS, METRIC_VERSION, TOPICS


def news_contribution(item: dict) -> float:
    corroboration = 1.0 + min(max(item.get("corroborating_sources", 1) - 1, 0), 2) * 0.15
    importance = max(0.0, min(1.0, item.get("importance", 5.0) / 10.0))
    novelty = max(0.0, min(1.0, item.get("novelty", 1.0)))
    quality = max(0.0, min(1.0, item.get("source_quality", 0.5)))
    return round(min(1.0, importance * novelty * quality * corroboration), 6)


def compute_topic_metrics(news_items: list[dict]) -> dict:
    totals = defaultdict(float)
    event_counts = defaultdict(int)
    source_sets = defaultdict(set)
    sentiment = defaultdict(float)
    for item in news_items:
        contribution = news_contribution(item)
        topics = [topic for topic in item.get("topics", []) if topic in TOPICS]
        if not topics:
            continue
        share = contribution / len(topics)
        for topic in topics:
            totals[topic] += share
            event_counts[topic] += 1
            source_sets[topic].add(item.get("source"))
            sentiment[topic] += share * item.get("sentiment", 0.0)
    return {
        key: {
            "name": spec["name"],
            "activity": round(totals.get(key, 0.0), 6),
            "event_count": event_counts.get(key, 0),
            "source_count": len(source_sets.get(key, set())),
            "sentiment": round(sentiment.get(key, 0.0), 6),
            "metric_version": METRIC_VERSION,
        }
        for key, spec in TOPICS.items()
    }


def compute_market_metrics(quotes: list[dict], macro_events: list[dict], news_items: list[dict]) -> dict:
    valid = [quote for quote in quotes if quote.get("change_pct") is not None and not quote.get("is_stale")]
    changes = [quote["change_pct"] for quote in valid]
    positive = sum(1 for change in changes if change > 0)
    breadth = positive / len(changes) if changes else None
    volatility = next((abs(q["change_pct"]) for q in valid if q["name"] == "VIX"), None)
    liquidity_values = [q["amount"] for q in valid if q.get("amount") is not None and q.get("market") == "CN"]
    macro_risk = sum(1 for event in macro_events if event.get("actual") is not None and event.get("consensus") is not None)
    risk_news = sum(news_contribution(item) for item in news_items if item.get("sentiment", 0) < 0)
    return {
        "cross_asset_momentum": _score_change(changes),
        "breadth": round(breadth, 6) if breadth is not None else None,
        "volatility": round(volatility, 6) if volatility is not None else None,
        "liquidity": round(median(liquidity_values), 2) if liquidity_values else None,
        "macro_event_count": macro_risk,
        "news_risk": round(risk_news, 6),
        "valid_quote_count": len(valid),
        "metric_version": METRIC_VERSION,
    }


def _score_change(changes):
    if not changes:
        return None
    return round(sum(math.tanh(change / 2.0) for change in changes) / len(changes), 6)


def compute_daily_features(news_items, quotes, macro_events):
    topic_metrics = compute_topic_metrics(news_items)
    market_metrics = compute_market_metrics(quotes, macro_events, news_items)
    return {"topic_metrics": topic_metrics, "market_metrics": market_metrics}
