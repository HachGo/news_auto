"""东方财富 push2 行情接口。

字段：f43=最新价(*100), f44=最高, f45=最低, f46=今开, f47=成交量, f48=成交额, f170=涨跌幅(*100), f58=名称。

A股已验证 secid：1.000001(上证) 0.399001(深证) 0.399006(创业板)
海外指数 secid 待 fixture 确认；若某 secid 返回 data:null 则跳过（降级）。
"""

import sys
import time

import requests

# 行情清单：name -> secid
QUOTES = [
    ("上证指数", "1.000001"),
    ("深证成指", "0.399001"),
    ("创业板指", "0.399006"),
    ("恒生指数", "100.HSI"),
    ("恒生科技", "100.HSTECH"),
    ("标普500", "100.SPX"),
    ("纳斯达克", "100.NDX"),
    ("道琼斯", "100.DJIA"),
    ("黄金", "122.XAU"),
    ("原油", "122.SC0"),
    ("VIX", "100.VIX"),
]

FIELDS = "f43,f44,f45,f46,f47,f48,f170,f58"
URL_TMPL = "https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=" + FIELDS


def fetch_feed_json(url, retries=3):
    """抓取单条行情 JSON。失败返回 None。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; news_auto/1.0)",
        "Referer": "https://quote.eastmoney.com/",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[warn] eastmoney fetch error ({exc}), attempt {attempt+1}: {url}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def _parse_one(raw, fallback_name):
    """解析单条行情 JSON 为展示字典。"""
    if not raw or raw.get("rc") != 0:
        return None
    data = raw.get("data") or {}
    if not data:
        return None
    return {
        "name": data.get("f58") or fallback_name,
        "price": (data.get("f43") or 0) / 100,
        "change_pct": (data.get("f170") or 0) / 100,
        "amount": data.get("f48"),
    }


def fetch_quotes():
    """抓取全部行情。全部失败返回 None；部分失败返回已成功的列表。"""
    out = []
    for name, secid in QUOTES:
        raw = fetch_feed_json(URL_TMPL.format(secid=secid))
        item = _parse_one(raw, name)
        if item:
            out.append(item)
        else:
            print(f"[warn] {name} 行情获取失败，跳过", file=sys.stderr)
    return out if out else None
