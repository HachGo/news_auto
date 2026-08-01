"""金十宏观经济日历。走 flash-api JSON 接口。失败返回 None（降级占位）。"""

import sys
import time
from datetime import datetime

import requests


URL = "https://flash-api.jin10.com/get_econ_calendar"


def fetch_calendar_json(retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; news_auto/1.0)",
        "Referer": "https://www.jin10.com/",
        "x-app-id": "SO1EJGPM1L",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(URL, headers=headers, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[warn] jin10 fetch error ({exc}), attempt {attempt+1}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def fetch_calendar(today):
    """返回当日公布的数据项列表。无数据返回空列表，抓取失败返回 None。"""
    raw = fetch_calendar_json()
    if raw is None:
        return None
    today_str = today.isoformat()
    out = []
    for item in raw or []:
        pub = item.get("pub_time") or item.get("publication_time") or ""
        if not pub.startswith(today_str):
            continue
        out.append({
            "title": item.get("title") or item.get("event") or "",
            "actual": item.get("current_actual") or item.get("actual") or "",
            "previous": item.get("previous") or "",
            "consensus": item.get("consensus") or "",
            "country": item.get("country") or "",
        })
    return out
