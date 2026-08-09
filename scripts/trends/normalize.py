"""把现有版面结果转换为趋势层的稳定结构。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from .config import SOURCE_QUALITY, TAXONOMY_VERSION, TOPICS


def canonical_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = "" if not parts.query else parts.query
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def parse_dt(value, fallback=None):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            dt = fallback
    else:
        dt = fallback
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_optional_dt(value):
    """行情源未提供时间时返回 None，绝不伪造观察时间。"""
    if not value:
        return None
    return parse_dt(value)


def clean_text(value) -> str:
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def _source_type(item):
    category = str(item.get("category", ""))
    source = str(item.get("source", ""))
    if "公告" in category or "公告" in source:
        return "official"
    if "研报" in category or "研究" in source:
        return "research"
    if "Reddit" in source or "Hacker News" in source or "社区" in category:
        return "community"
    if "Google News" in source or "聚合" in source:
        return "aggregator"
    return "media"


def source_quality(item):
    kind = _source_type(item)
    return {"official": SOURCE_QUALITY["官方"], "research": SOURCE_QUALITY["研究机构"], "media": SOURCE_QUALITY["主流媒体"], "community": SOURCE_QUALITY["社区"], "aggregator": SOURCE_QUALITY["聚合"]}[kind]


def classify_topics(text: str) -> list[str]:
    text = clean_text(text).lower()
    hits = []
    for key, spec in TOPICS.items():
        if any(str(keyword).lower() in text for keyword in spec["keywords"]):
            hits.append(key)
    return hits or ["unclassified"]


def event_cluster_id(title: str) -> str:
    words = re.findall(r"[\w\u4e00-\u9fff]+", clean_text(title).lower())
    # 保留前几个有信息量的词，足以把明显重复转载归到一起。
    signature = " ".join(words[:18])
    return stable_id(signature or title)


def normalize_news(item: dict, section: str, as_of: str) -> dict:
    title = clean_text(item.get("title_zh") or item.get("title") or "未命名条目")
    summary = clean_text(item.get("summary_zh") or item.get("summary") or "")
    link = canonical_url(item.get("link") or "")
    raw_score = item.get("score", 5)
    try:
        importance = max(0.0, min(10.0, float(raw_score)))
    except (TypeError, ValueError):
        importance = 5.0
    sentiment = item.get("sentiment")
    try:
        sentiment = max(-1.0, min(1.0, float(sentiment))) if sentiment is not None else 0.0
    except (TypeError, ValueError):
        sentiment = 0.0
    text = f"{title} {summary}"
    novelty = _number_or_none(item.get("novelty", 1.0))
    novelty = 1.0 if novelty is None else max(0.0, min(1.0, novelty))
    return {
        "id": stable_id(link or title),
        "event_id": event_cluster_id(title),
        "title": title,
        "summary": summary[:800],
        "link": link,
        "source": clean_text(item.get("source") or "未知来源"),
        "source_type": _source_type(item),
        "published_at": parse_dt(item.get("published_at") or item.get("time")),
        "section": section,
        "topics": classify_topics(text),
        "entities": list(item.get("entities") or [])[:20],
        "importance": round(importance, 3),
        "sentiment": round(sentiment, 3),
        "novelty": round(novelty, 3),
        "source_quality": round(source_quality(item), 3),
        "corroborating_sources": 1,
        "classification_method": "rules",
        "classification_version": TAXONOMY_VERSION,
        "as_of": as_of,
    }


def normalize_quote(item: dict, date_str: str) -> dict:
    name = clean_text(item.get("name") or "未知资产")
    symbol = clean_text(item.get("symbol") or item.get("code") or name)
    market = clean_text(item.get("market") or _guess_market(name))
    trading_date = clean_text(item.get("trading_date") or date_str)
    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "currency": item.get("currency") or ("CNY" if market == "CN" else "USD"),
        "price": _number_or_none(item.get("price")),
        "change_pct": _number_or_none(item.get("change_pct")),
        "amount": _number_or_none(item.get("amount")),
        "observed_at": parse_optional_dt(item.get("observed_at") or item.get("timestamp")),
        "trading_date": trading_date,
        "session_status": item.get("session_status") or "unknown",
        "source": item.get("source") or "unknown",
        "is_stale": bool(item.get("is_stale", False)) or item.get("session_status") == "stale",
    }


def _number_or_none(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _guess_market(name):
    if any(word in name for word in ("上证", "深证", "创业板")):
        return "CN"
    if any(word in name for word in ("恒生",)):
        return "HK"
    if name in {"黄金", "原油", "VIX"}:
        return "GLOBAL"
    return "US"
