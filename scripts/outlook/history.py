"""历史日 K 抓取与本地缓存（仓库根目录 history/{key}.csv；不放 data/，Hugo 会把 data/ 下的 CSV 当站点数据解析）。

首次运行拉取 2010 年至今的全部日线，之后只拉近一个月并按日期合并；
抓取全部失败时沿用缓存，不清空已有数据。行格式：date,open,high,low,close。
"""

from __future__ import annotations

import csv
import io
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

START = "2010-01-01"
REFRESH_DAYS = 40  # 增量窗口：覆盖长假和偶发的漏抓
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # 排除 NaN


def clean(rows):
    """按日期去重排序；丢弃收盘价缺失或非正的行（如 2020-04-20 原油负价），高低价缺失时用收盘价代替。"""
    by_date = {}
    for row in rows:
        day, close = row.get("date"), _num(row.get("close"))
        if not day or close is None or close <= 0:
            continue
        high, low = _num(row.get("high")), _num(row.get("low"))
        if high is None or low is None or high < low or low <= 0:
            high = low = close
        by_date[day] = {"date": day, "open": _num(row.get("open")) or close, "high": max(high, close), "low": min(low, close), "close": close}
    return [by_date[day] for day in sorted(by_date)]


def fetch_yahoo(symbol, start):
    period1 = int(datetime.fromisoformat(start).replace(tzinfo=timezone.utc).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol)}?period1={period1}&period2=9999999999&interval=1d"
    response = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    stamps = result.get("timestamp") or []
    q = result["indicators"]["quote"][0]
    offset = result.get("meta", {}).get("gmtoffset") or 0
    rows = []
    for i, stamp in enumerate(stamps):
        day = datetime.fromtimestamp(stamp + offset, tz=timezone.utc).date().isoformat()
        rows.append({"date": day, "open": q["open"][i], "high": q["high"][i], "low": q["low"][i], "close": q["close"][i]})
    return rows


def fetch_sina(symbol, start):
    days = max(30, (date.today() - date.fromisoformat(start)).days)
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
           f"?symbol={symbol}&scale=240&ma=no&datalen={min(6000, days)}")
    response = requests.get(url, headers={"User-Agent": _UA, "Referer": "https://finance.sina.com.cn"}, timeout=30)
    response.raise_for_status()
    return [{"date": item["day"][:10], "open": item["open"], "high": item["high"], "low": item["low"], "close": item["close"]}
            for item in response.json() or [] if item.get("day", "")[:10] >= start]


def fetch_eastmoney(secid, start):
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?secid={secid}&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55&klt=101&fqt=0&beg={start.replace('-', '')}&end=20500101")
    response = requests.get(url, headers={"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"}, timeout=30)
    response.raise_for_status()
    rows = []
    for line in ((response.json() or {}).get("data") or {}).get("klines") or []:
        day, opened, close, high, low = line.split(",")[:5]  # 东财顺序：日期,开,收,高,低
        rows.append({"date": day, "open": opened, "high": high, "low": low, "close": close})
    return rows


FETCHERS = (("yahoo", fetch_yahoo), ("sina", fetch_sina), ("eastmoney", fetch_eastmoney))


def fetch(asset, start):
    """按来源顺序尝试，返回第一个非空结果。"""
    for source, fetcher in FETCHERS:
        symbol = asset.get(source)
        if not symbol:
            continue
        try:
            rows = clean(fetcher(symbol, start))
        except Exception as exc:  # 网络、限频、格式变化都按失败处理，换下一个来源
            print(f"[warn] history {asset['key']} {source}: {exc}", file=sys.stderr)
            continue
        if rows:
            return rows
        time.sleep(1)
    return []


def read_cache(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        return clean(csv.DictReader(stream))


def write_cache(path, rows):
    from common import atomic_write_text
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["date", "open", "high", "low", "close"])
    for row in rows:
        writer.writerow([row["date"]] + [f"{row[k]:.6g}" for k in ("open", "high", "low", "close")])
    text = buffer.getvalue()
    path = Path(path)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        atomic_write_text(path, text)


def merge(old, new):
    """新数据覆盖同日旧数据（最近一根 K 线收盘后可能被修订）。"""
    return clean(list(old) + list(new))


def update(asset, folder, today=None, fetcher=fetch):
    """刷新单个资产缓存并返回完整历史；抓取失败时返回缓存。"""
    path = Path(folder) / f"{asset['key']}.csv"
    cached = read_cache(path)
    today = today or date.today()
    if cached and (today - date.fromisoformat(cached[-1]["date"])).days < 1:
        return cached
    start = START
    if len(cached) > 250:
        start = date.fromordinal(max(date.fromisoformat(cached[-1]["date"]).toordinal() - REFRESH_DAYS, 1)).isoformat()
    fresh = fetcher(asset, start)
    rows = merge(cached, fresh)
    if rows and rows != cached:
        write_cache(path, rows)
    return rows
