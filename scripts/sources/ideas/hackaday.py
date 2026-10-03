"""Hackaday：官方 RSS，硬件与技术巧思。信号：评论数（slash:comments）。"""

import feedparser

from common import entry_time
from sources.ideas import cli, get, make_item

NAME = "Hackaday"
ACCESS = "RSS"
URL = "https://hackaday.com/blog/feed/"


def parse(content):
    items = []
    for entry in feedparser.parse(content).entries:
        if not entry.get("link") or not entry.get("title"):
            continue
        published = entry_time(entry)
        comments = entry.get("slash_comments")
        items.append(make_item(
            "hackaday", entry.get("post-id") or entry["link"], entry["link"], entry["title"],
            entry.get("summary") or "", published.isoformat() if published else None,
            {"comments": int(comments) if str(comments or "").isdigit() else None},
        ))
    return items


def fetch(limit=30, now=None):
    return parse(get(URL).content)[:limit]


if __name__ == "__main__":
    cli(fetch, __doc__)
