"""巨潮资讯网公告列表。

走 POST hisAnnouncement/query：按日期窗口拉取半年报 / 业绩预告 / 年报等，
合并去重后按时间倒序截取。失败返回 None。
"""

import sys
import time
from datetime import datetime, timedelta, timezone

import requests

URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"

# 关注近期更有信息量的类别（年报更正往往是陈旧补丁）
CATEGORIES = [
    ("category_bndbg_szsh", "半年报"),
    ("category_yjygjxz_szsh", "业绩预告"),
    ("category_ndbg_szsh", "年报"),
]


def fetch_announcements_json(limit=10, category="category_ndbg_szsh",
                             se_date=None, retries=3):
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
    if se_date:
        data["seDate"] = se_date
    for attempt in range(retries):
        try:
            resp = requests.post(URL, headers=headers, data=data, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[warn] cninfo fetch error ({exc}), attempt {attempt+1}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def _parse_rows(raw, limit):
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
            "_ts": ts or 0,
        })
    return out


def fetch_announcements(limit=10, days=14):
    """返回公告摘要列表。抓取失败返回 None。"""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    se_date = f"{start.isoformat()}~{end.isoformat()}"

    merged = []
    seen_titles = set()
    any_ok = False
    per_cat = max(limit, 8)
    for category, label in CATEGORIES:
        raw = fetch_announcements_json(limit=per_cat, category=category, se_date=se_date)
        if raw is None:
            print(f"[warn] cninfo {label} 抓取失败", file=sys.stderr)
            continue
        any_ok = True
        for item in _parse_rows(raw, per_cat):
            key = (item["sec_code"], item["title"])
            if key in seen_titles:
                continue
            seen_titles.add(key)
            merged.append(item)

    if not any_ok:
        return None

    merged.sort(key=lambda x: x.get("_ts") or 0, reverse=True)
    out = []
    for item in merged[:limit]:
        item.pop("_ts", None)
        out.append(item)
    return out
