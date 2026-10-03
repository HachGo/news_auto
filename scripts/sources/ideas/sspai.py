"""少数派：官方 RSS，数字工具与好方法。RSS 不含热度信号，评分时按中位数处理。"""

import feedparser

from common import entry_time
from sources.ideas import cli, get, make_item

NAME = "少数派"
NAME_EN = "SSPAI"
ACCESS = "RSS"
URL = "https://sspai.com/feed"


def parse(content):
    items = []
    for entry in feedparser.parse(content).entries:
        if not entry.get("link") or not entry.get("title"):
            continue
        published = entry_time(entry)
        items.append(make_item(
            "sspai", entry.get("id") or entry["link"], entry["link"], entry["title"],
            entry.get("summary") or "", published.isoformat() if published else None, {},
        ))
    return items


def fetch(limit=30, now=None):
    return parse(get(URL).content)[:limit]


if __name__ == "__main__":
    cli(fetch, __doc__)
