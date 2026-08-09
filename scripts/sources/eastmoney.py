"""行情抓取：东方财富 batch ulist 为主，新浪 / Yahoo 补缺。

东方财富 push2 单票接口易被断开；改走 push2delay ulist 批量接口（fltt=2，价格已是真实点位）。
恒生科技 / 原油等 secid 已校正；VIX 在东财无稳定 secid，走 Yahoo 补齐。
全部失败返回 None；部分成功返回已拿到的列表。
"""

import re
import sys
import time

import requests

# name, eastmoney secid（None 表示东财不拉）, 用于匹配 ulist 的 f12
QUOTES = [
    ("上证指数", "1.000001", "000001"),
    ("深证成指", "0.399001", "399001"),
    ("创业板指", "0.399006", "399006"),
    ("恒生指数", "100.HSI", "HSI"),
    ("恒生科技", "124.HSTECH", "HSTECH"),
    ("标普500", "100.SPX", "SPX"),
    ("纳斯达克", "100.NDX", "NDX"),
    ("道琼斯", "100.DJIA", "DJIA"),
    ("黄金", "122.XAU", "XAU"),
    ("原油", "102.CL00Y", "CL00Y"),
    ("VIX", None, "VIX"),
]

# 兼容旧单票解析（测试 / 降级）
FIELDS = "f43,f44,f45,f46,f47,f48,f170,f58"
URL_TMPL = "https://push2delay.eastmoney.com/api/qt/stock/get?secid={secid}&fields=" + FIELDS

ULIST_URLS = [
    "https://push2delay.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&secids={secids}&fields=f12,f14,f2,f3,f6",
    "https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&invt=2&secids={secids}&fields=f12,f14,f2,f3,f6",
]

SINA_SYMBOLS = [
    # (展示名, sina list 代码, 解析类型)
    ("上证指数", "s_sh000001", "s"),
    ("深证成指", "s_sz399001", "s"),
    ("创业板指", "s_sz399006", "s"),
    ("恒生指数", "int_hangseng", "int"),
    ("恒生科技", "rt_hkHSTECH", "hk"),
    ("标普500", "int_sp500", "int"),
    ("纳斯达克", "int_nasdaq", "int"),
    ("道琼斯", "int_dji", "int"),
    ("黄金", "hf_GC", "hf"),
    ("原油", "hf_CL", "hf"),
]

YAHOO_SYMBOLS = [
    ("VIX", "%5EVIX"),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
}


def fetch_feed_json(url, retries=3):
    """抓取单条行情 JSON。失败返回 None。"""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[warn] eastmoney fetch error ({exc}), attempt {attempt+1}: {url}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def _parse_one(raw, fallback_name):
    """解析单条行情 JSON（未 fltt 缩放）为展示字典。"""
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


def _as_float(val):
    if val is None or val == "" or val == "-":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _fetch_eastmoney_batch():
    """批量 ulist：一次拿齐有 secid 的标的。"""
    secids = [secid for _, secid, _ in QUOTES if secid]
    if not secids:
        return []
    code_to_name = {code: name for name, _, code in QUOTES}
    for tmpl in ULIST_URLS:
        url = tmpl.format(secids=",".join(secids))
        raw = fetch_feed_json(url, retries=2)
        if not raw or raw.get("rc") != 0:
            continue
        diff = (raw.get("data") or {}).get("diff") or []
        out = []
        for row in diff:
            code = str(row.get("f12") or "")
            name = code_to_name.get(code)
            if not name:
                # 宽松匹配：东财名称含我们清单名
                em_name = row.get("f14") or ""
                name = next((n for n, _, _ in QUOTES if n in em_name or em_name in n), None)
            price = _as_float(row.get("f2"))
            pct = _as_float(row.get("f3"))
            if not name or price is None or pct is None:
                continue
            amount = _as_float(row.get("f6"))
            out.append({"name": name, "price": price, "change_pct": pct, "amount": amount, "source": "eastmoney"})
        if out:
            return out
    return []


def _fetch_sina_quotes():
    """新浪财经 hq.sinajs.cn 批量补缺。"""
    symbols = [sym for _, sym, _ in SINA_SYMBOLS]
    url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
    headers = {
        **_HEADERS,
        "Referer": "https://finance.sina.com.cn/",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        text = resp.content.decode("gbk", errors="replace")
    except Exception as exc:
        print(f"[warn] sina quotes fetch error: {exc}", file=sys.stderr)
        return []

    by_sym = {}
    for m in re.finditer(r'hq_str_([^=]+)="([^"]*)"', text):
        by_sym[m.group(1)] = m.group(2)

    out = []
    for name, sym, kind in SINA_SYMBOLS:
        payload = by_sym.get(sym)
        if not payload:
            continue
        fields = payload.split(",")
        item = _parse_sina_fields(name, fields, kind)
        if item:
            item["source"] = "sina"
            out.append(item)
    return out


def _parse_sina_fields(name, fields, kind):
    try:
        if kind == "s":
            # name, price, change, pct, volume, amount(万元)
            price = float(fields[1])
            pct = float(fields[3])
            amount = float(fields[5]) * 10000 if len(fields) > 5 and fields[5] else None
            return {"name": name, "price": price, "change_pct": pct, "amount": amount}
        if kind == "int":
            # name, price, change, pct
            return {
                "name": name,
                "price": float(fields[1]),
                "change_pct": float(fields[3]),
                "amount": None,
            }
        if kind == "hk":
            # code, name, price, prev_close, ...
            price = float(fields[2])
            prev = float(fields[3])
            pct = (price - prev) / prev * 100 if prev else 0.0
            return {"name": name, "price": price, "change_pct": pct, "amount": None}
        if kind == "hf":
            # price, ..., prev_settle at index 7
            price = float(fields[0])
            prev = float(fields[7]) if len(fields) > 7 and fields[7] else None
            pct = ((price - prev) / prev * 100) if prev else 0.0
            return {"name": name, "price": price, "change_pct": pct, "amount": None}
    except (IndexError, ValueError, TypeError) as exc:
        print(f"[warn] sina parse {name}: {exc}", file=sys.stderr)
    return None


def _fetch_yahoo_quotes():
    """Yahoo chart API 补 VIX 等东财/新浪缺失项。"""
    out = []
    headers = {"User-Agent": _HEADERS["User-Agent"]}
    for name, sym in YAHOO_SYMBOLS:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            meta = resp.json()["chart"]["result"][0]["meta"]
            price = _as_float(meta.get("regularMarketPrice"))
            prev = _as_float(meta.get("chartPreviousClose") or meta.get("previousClose"))
            if price is None or prev is None or prev == 0:
                continue
            out.append({
                "name": name,
                "price": price,
                "change_pct": (price - prev) / prev * 100,
                "amount": None,
                "source": "yahoo",
            })
        except Exception as exc:
            print(f"[warn] yahoo {name} fetch error: {exc}", file=sys.stderr)
    return out


def fetch_quotes():
    """抓取全部行情。全部失败返回 None；部分失败返回已成功的列表。"""
    by_name = {}

    for item in _fetch_eastmoney_batch():
        by_name[item["name"]] = item

    missing = [name for name, _, _ in QUOTES if name not in by_name]
    if missing:
        print(f"[info] eastmoney 缺 {missing}，尝试新浪补齐", file=sys.stderr)
        for item in _fetch_sina_quotes():
            if item["name"] not in by_name:
                by_name[item["name"]] = item

    still = [name for name, _, _ in QUOTES if name not in by_name]
    if still:
        print(f"[info] 仍缺 {still}，尝试 Yahoo 补齐", file=sys.stderr)
        for item in _fetch_yahoo_quotes():
            if item["name"] not in by_name:
                by_name[item["name"]] = item

    # 按清单顺序输出
    out = [by_name[name] for name, _, _ in QUOTES if name in by_name]
    for name, _, _ in QUOTES:
        if name not in by_name:
            print(f"[warn] {name} 行情获取失败，跳过", file=sys.stderr)
    return out if out else None
