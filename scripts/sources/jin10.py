"""宏观经济日历。

优先金十 flash-api；不可用时回退到 Forex Factory 本周日历 JSON
（https://nfs.faireconomy.media/ff_calendar_thisweek.json）。

无当日数据返回空列表；抓取全部失败返回 None（降级占位）。
"""

import sys
import time
from datetime import datetime, timedelta, timezone

import requests

URL = "https://flash-api.jin10.com/get_econ_calendar"
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

CST = timezone(timedelta(hours=8))

_JIN10_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://rili.jin10.com/",
    "Origin": "https://rili.jin10.com",
    "x-app-id": "SO1EJGPM1L",
    "x-version": "1.0.0",
    "Accept": "application/json, text/plain, */*",
}


def fetch_calendar_json(retries=2):
    for attempt in range(retries):
        try:
            resp = requests.get(URL, headers=_JIN10_HEADERS, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[warn] jin10 fetch error ({exc}), attempt {attempt+1}", file=sys.stderr)
            if attempt + 1 < retries:
                time.sleep(1 * (attempt + 1))
    return None


def _parse_jin10(raw, today_str):
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


def _parse_ff_items(raw, today):
    """将 Forex Factory JSON 过滤为当日 Medium/High 条目（北京时间）。"""
    today_str = today.isoformat()
    out = []
    for item in raw or []:
        ds = item.get("date") or ""
        try:
            local_date = datetime.fromisoformat(ds).astimezone(CST).date().isoformat()
        except ValueError:
            local_date = ds[:10]
        if local_date != today_str:
            continue
        if item.get("impact") not in ("High", "Medium"):
            continue
        title = item.get("title") or ""
        country = item.get("country") or ""
        if country:
            title = f"{country} {title}".strip()
        out.append({
            "title": title,
            "actual": item.get("actual") or "",
            "previous": item.get("previous") or "",
            "consensus": item.get("forecast") or "",
            "country": country,
        })
    return out


def _fetch_forexfactory(today):
    """Forex Factory 本周日历，按北京时间日期过滤，只保留 Medium/High。"""
    headers = {"User-Agent": _JIN10_HEADERS["User-Agent"]}
    try:
        resp = requests.get(FF_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        print(f"[warn] forexfactory calendar fetch error: {exc}", file=sys.stderr)
        return None
    return _parse_ff_items(raw, today)


def fetch_calendar(today):
    """返回当日公布的数据项列表。无数据返回空列表，抓取失败返回 None。"""
    today_str = today.isoformat()
    raw = fetch_calendar_json()
    if raw is not None:
        return _parse_jin10(raw, today_str)

    print("[info] jin10 不可用，回退 Forex Factory 日历", file=sys.stderr)
    return _fetch_forexfactory(today)
