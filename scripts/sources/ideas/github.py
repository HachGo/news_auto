"""GitHub：REST 搜索近 7 天新建、星标最多的仓库。信号：stars。

设置 GITHUB_TOKEN 时带上令牌以放宽限流（GitHub Actions 自带，无需额外账号）。
"""

import os
from datetime import datetime, timedelta, timezone

from sources.ideas import cli, get, make_item

NAME = "GitHub"
ACCESS = "API"
URL = "https://api.github.com/search/repositories"


def parse(payload):
    items = []
    for repo in payload.get("items") or []:
        if repo.get("fork") or repo.get("archived") or not repo.get("html_url"):
            continue
        items.append(make_item(
            "github", repo.get("id"), repo["html_url"], repo.get("full_name") or repo.get("name") or "",
            repo.get("description") or "", repo.get("created_at"), {"stars": repo.get("stargazers_count")},
        ))
    return items


def fetch(limit=30, now=None):
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=7)).date().isoformat()
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{URL}?q=created:>{since}&sort=stars&order=desc&per_page={limit}"
    return parse(get(url, headers=headers).json())[:limit]


if __name__ == "__main__":
    cli(fetch, __doc__)
