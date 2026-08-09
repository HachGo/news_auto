"""趋势新闻的事件去重和多源确认。"""

from __future__ import annotations

from collections import defaultdict


def cluster_news(items: list[dict]) -> list[dict]:
    clusters = defaultdict(list)
    for item in items:
        clusters[item.get("event_id") or item.get("id")].append(item)

    result = []
    for group in clusters.values():
        sources = {item.get("source") for item in group if item.get("source")}
        representative = max(group, key=lambda item: (item.get("importance", 0), item.get("source_quality", 0)))
        representative = dict(representative)
        representative["corroborating_sources"] = len(sources)
        representative["source_ids"] = [item.get("id") for item in group]
        result.append(representative)
    return sorted(result, key=lambda item: (item.get("published_at", ""), item.get("importance", 0)), reverse=True)
