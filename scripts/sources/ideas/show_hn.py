"""Show HN：HN 官方 Algolia 搜索 API，取近 48 小时内获得关注的作品帖。信号：points、评论数。"""

from datetime import datetime, timedelta, timezone

from sources.ideas import cli, get, make_item

NAME = "Show HN"
ACCESS = "API"
URL = "https://hn.algolia.com/api/v1/search"


def parse(payload):
    items = []
    for hit in payload.get("hits") or []:
        object_id, title = hit.get("objectID"), hit.get("title")
        if not object_id or not title:
            continue
        discussion = f"https://news.ycombinator.com/item?id={object_id}"
        items.append(make_item(
            "show_hn", object_id, hit.get("url") or discussion,
            title.removeprefix("Show HN:").strip(), hit.get("story_text") or "",
            hit.get("created_at"), {"upvotes": hit.get("points"), "comments": hit.get("num_comments")},
        ) | {"discussion": discussion})
    return items


def fetch(limit=30, now=None):
    since = int(((now or datetime.now(timezone.utc)) - timedelta(hours=48)).timestamp())
    params = f"?tags=show_hn&numericFilters=created_at_i>{since},points>=5&hitsPerPage={limit}"
    return parse(get(URL + params).json())[:limit]


if __name__ == "__main__":
    cli(fetch, __doc__)
