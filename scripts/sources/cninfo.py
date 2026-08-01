"""巨潮资讯网公告列表。走 POST hisAnnouncement/query 接口，取年报/重大事项。失败返回 None。"""

import sys
import time
from datetime import datetime, timezone

import requests

URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"

# category_ndbg_szsh = 年报；可按需扩展 category 为重大事项/停复牌


def fetch_announcements_json(limit=10, category="category_ndbg_szsh", retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; news_auto/1.0)",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "stock": "",
        "tabName": "fulltext",
        "pageSize": str(limit),
        "pageNum": "1",
        "column": "szse",
        "category": category,
    }
    for attempt in range(retries):
        try:
            resp = requests.post(URL, headers=headers, data=data, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[warn] cninfo fetch error ({exc}), attempt {attempt+1}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def fetch_announcements(limit=10):
    """返回公告摘要列表。抓取失败返回 None。"""
    raw = fetch_announcements_json(limit=limit)
    if raw is None:
        return None
    out = []
    for a in (raw.get("announcements") or [])[:limit]:
        ts = a.get("announcementTime")
        pub = ""
        if isinstance(ts, (int, float)):
            pub = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append({
            "sec_code": a.get("secCode") or "",
            "sec_name": a.get("secName") or "",
            "title": a.get("announcementTitle") or "",
            "url": "http://www.cninfo.com.cn/" + (a.get("adjunctUrl") or ""),
            "pub_date": pub,
        })
    return out
