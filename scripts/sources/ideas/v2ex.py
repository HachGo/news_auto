"""V2EX「分享创造」节点：官方 v1 API，开发者分享自己做的东西。信号：回复数。"""

from datetime import datetime, timezone

from sources.ideas import cli, get, make_item

NAME = "V2EX"
ACCESS = "API"
URL = "https://www.v2ex.com/api/topics/show.json?node_name=create"


def parse(payload):
    items = []
    for topic in payload or []:
        if not topic.get("id") or not topic.get("title"):
            continue
        created = topic.get("created")
        published = datetime.fromtimestamp(created, timezone.utc).isoformat() if created else None
        items.append(make_item(
            "v2ex", topic["id"], topic.get("url") or f"https://www.v2ex.com/t/{topic['id']}",
            topic["title"], topic.get("content") or "", published, {"comments": topic.get("replies")},
        ))
    return items


def fetch(limit=30, now=None):
    return parse(get(URL).json())[:limit]


if __name__ == "__main__":
    cli(fetch, __doc__)
