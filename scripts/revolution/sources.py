"""原始数据抓取与缓存（history/revolution/{RAW}.csv；不放 data/，Hugo 会解析 data/ 下的 CSV）。

每个原始序列每天最多抓取一次；抓取失败或返回空时沿用缓存，并在元数据里记录失败，页面据此标注「数据过期」。
所有来源都无需 API Key。
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
from datetime import date
from pathlib import Path

import requests

from .catalog import RAW

# SEC 要求声明身份的 User-Agent；不含个人邮箱，可通过环境变量覆盖
SEC_UA = os.environ.get("SEC_USER_AGENT", "news_auto research bot")
EPOCH_URL = "https://epoch.ai/data/notable_ai_models.csv"


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fetch_fred(series_id):
    """FRED 公开 CSV：DATE,VALUE；缺失值为 '.' 或空，直接丢弃（不插值）。"""
    response = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout=30)
    response.raise_for_status()
    rows = []
    for record in csv.reader(io.StringIO(response.text)):
        if len(record) < 2 or not record[0][:4].isdigit():
            continue
        value = _num(record[1])
        if value is not None:
            rows.append({"date": record[0][:10], "value": value})
    return rows


def _quarter_end(day):
    """把日期归到自然季度末（云厂商财季都以自然季度末结束）。"""
    d = date.fromisoformat(day)
    month = ((d.month - 1) // 3 + 1) * 3
    return f"{d.year}-{month:02d}"


def quarterly_from_facts(facts):
    """10-Q 现金流量表是年初至今累计值：单季 = 本期累计 − 同一起点、截至上一季度末的累计。

    facts: [{start, end, val, filed}]，同一 (start, end) 保留最晚提交的版本（含修订）。
    返回 [{date: 季度首日, value}]，单位为美元。
    """
    latest = {}
    for fact in facts:
        key = (fact["start"], fact["end"])
        if key not in latest or fact.get("filed", "") >= latest[key].get("filed", ""):
            latest[key] = fact
    by_end = {}
    for (start, end), fact in latest.items():
        by_end.setdefault(end, []).append((start, fact["val"]))
    quarters = {}
    for end, items in by_end.items():
        end_day = date.fromisoformat(end)
        value = None
        for start, val in items:
            days = (end_day - date.fromisoformat(start)).days
            if 80 <= days <= 100:
                value = val
                break
        if value is None:
            for start, val in items:
                days = (end_day - date.fromisoformat(start)).days
                if days <= 100:
                    continue
                # 同起点、早一个季度结束的累计值
                for prev_end, prev_items in by_end.items():
                    gap = (end_day - date.fromisoformat(prev_end)).days
                    if not 80 <= gap <= 100:
                        continue
                    match = next((v for s, v in prev_items if s == start), None)
                    if match is not None:
                        value = val - match
                        break
                if value is not None:
                    break
        if value is not None and value > 0:
            label = _quarter_end(end)
            year, month = label.split("-")
            quarters[f"{year}-{int(month) - 2:02d}-01"] = value
    return [{"date": day, "value": quarters[day]} for day in sorted(quarters)]


def fetch_edgar(cik, tags):
    ciks = cik if isinstance(cik, list) else [cik]
    facts = []
    for c_rank, number in enumerate(ciks):
        for t_rank, tag in enumerate(tags):
            url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{number:010d}/us-gaap/{tag}.json"
            response = requests.get(url, headers={"User-Agent": SEC_UA, "Accept-Encoding": "identity"}, timeout=30)
            if response.status_code == 404:
                continue
            response.raise_for_status()
            for item in response.json().get("units", {}).get("USD", []):
                if item.get("form", "").startswith(("10-Q", "10-K")) and item.get("start") and item.get("end"):
                    facts.append({"start": item["start"], "end": item["end"], "val": item["val"], "filed": item.get("filed", ""),
                                  "rank": (t_rank, -c_rank)})
    # 后列的标签是新口径、先列的 CIK 是现主体：同一期间重复时按此优先
    best = {}
    for fact in facts:
        key = (fact["start"], fact["end"])
        if key not in best or fact["rank"] > best[key]["rank"]:
            best[key] = fact
    return quarterly_from_facts(best.values())


def parse_epoch(text):
    """只保留有训练算力估计的模型：date, flop, model, organization。"""
    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        day, flop = (record.get("Publication date") or "")[:10], _num(record.get("Training compute (FLOP)"))
        if len(day) == 10 and flop and flop > 0:
            rows.append({"date": day, "flop": flop, "model": (record.get("Model") or "").strip()[:80],
                         "organization": (record.get("Organization") or "").strip()[:80]})
    rows.sort(key=lambda r: (r["date"], -r["flop"]))
    return rows


def fetch_epoch():
    response = requests.get(EPOCH_URL, timeout=60)
    response.raise_for_status()
    return parse_epoch(response.content.decode("utf-8-sig"))


BTOS_BASE = "https://www.census.gov/hfp/btos/downloads/"


def _pct(value):
    """BTOS 表格里的百分比是 '25.0%' 文本，缺失为 '.'。"""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().rstrip("%")
    return _num(text) if text not in ("", ".") else None


def _rows(sheet):
    rows = list(sheet.iter_rows(values_only=True))
    return rows[0], rows[1:]


def _iso_date(value):
    """日期单元格可能是 datetime、'YYYY-MM-DD' 或 'MM/DD/YYYY' 文本（不同文件不一致）。"""
    from datetime import datetime
    if hasattr(value, "date"):
        return value.date().isoformat()
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"BTOS date not recognized: {text[:20]}")


def parse_btos(content, sheets, qid, contains):
    """全国估计：按题号取「Yes」行，期号映射到收集结束日，附标准误。

    题号与题干文字必须同时匹配，Census 调整题号时直接报错（沿用缓存），不会悄悄换成别的题。
    """
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    est_header, est_rows = _rows(wb[sheets[0]])
    se_header, se_rows = _rows(wb[sheets[1]])

    def yes_row(rows):
        for row in rows:
            if row and row[0] == qid and str(row[3]).strip() == "Yes":
                if contains not in str(row[1]):
                    raise ValueError(f"BTOS question {qid} wording changed: {str(row[1])[:80]}")
                return row
        raise ValueError(f"BTOS question {qid} not found")
    est, se = yes_row(est_rows), yes_row(se_rows)
    se_by_period = {str(h): _pct(v) for h, v in zip(se_header[4:], se[4:])}
    date_header, date_rows = _rows(wb["Collection and Reference Dates"])
    col = {name: i for i, name in enumerate(date_header) if name}
    end_by_period = {}
    for row in date_rows:
        period, end = row[col["Smpdt"]], row[col["Col End"]]
        if period and end:
            end_by_period[str(period)] = _iso_date(end)
    out = []
    for header, value in zip(est_header[4:], est[4:]):
        period, number = str(header), _pct(value)
        if number is None:
            continue
        if period not in end_by_period:
            raise ValueError(f"BTOS period {period} has no collection dates")
        out.append({"date": end_by_period[period], "value": number, "se": se_by_period.get(period)})
    return sorted(out, key=lambda r: r["date"])


def fetch_btos(spec):
    from urllib.parse import quote
    response = requests.get(BTOS_BASE + quote(spec["file"]), headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    response.raise_for_status()
    return parse_btos(response.content, spec["sheets"], spec["qid"], spec["contains"])


def fetch_yahoo(symbol):
    from outlook.history import fetch_yahoo as yahoo
    return [{"date": row["date"], "value": row["close"]} for row in yahoo(symbol, "2000-01-01") if _num(row["close"])]


def fetch_raw(key, root):
    spec = RAW[key]
    kind = spec["fetch"]
    if kind == "fred":
        return fetch_fred(spec["id"])
    if kind == "edgar":
        return fetch_edgar(spec["cik"], spec["tags"])
    if kind == "epoch":
        return fetch_epoch()
    if kind == "yahoo":
        return fetch_yahoo(spec["symbol"])
    if kind == "btos":
        return fetch_btos(spec)
    if kind == "local":
        from outlook.history import read_cache
        return [{"date": row["date"], "value": row["close"]} for row in read_cache(Path(root) / "history" / f"{spec['key']}.csv")]
    raise ValueError(kind)


FIELDS = {"EPOCH": ["date", "flop", "model", "organization"],
          "BTOS_AI": ["date", "value", "se"], "BTOS_AI_OLD": ["date", "value", "se"]}


def read_cache(path, key):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if key == "EPOCH":
        return [{**row, "flop": float(row["flop"])} for row in rows]
    if "se" in FIELDS.get(key, []):
        return [{"date": row["date"], "value": float(row["value"]), "se": _num(row.get("se"))} for row in rows]
    return [{"date": row["date"], "value": float(row["value"])} for row in rows]


def write_cache(path, key, rows):
    from common import atomic_write_text
    fields = FIELDS.get(key, ["date", "value"])
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: (f"{row[k]:.10g}" if isinstance(row[k], float) else row[k]) for k in fields})
    text = buffer.getvalue()
    path = Path(path)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        atomic_write_text(path, text)


def load_all(root, today, fetcher=None, keys=None):
    """刷新并读取全部原始序列。返回 (data, meta)：meta[key] = {fetched_on, ok, error}。"""
    fetcher = fetcher or (lambda key, folder: fetch_raw(key, folder))  # 调用时解析，便于测试替换
    from common import atomic_write_text
    root = Path(root)
    folder = root / "history" / "revolution"
    meta_path = folder / "_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    data = {}
    for key in keys or RAW:
        path = folder / f"{key}.csv"
        cached = read_cache(path, key)
        info = meta.get(key, {})
        fresh_today = info.get("fetched_on") == today and info.get("ok") and cached
        if RAW[key]["fetch"] == "local" or not fresh_today:
            try:
                rows = fetcher(key, root)
                if not rows:
                    raise ValueError("empty response")
                if RAW[key]["fetch"] != "local":
                    write_cache(path, key, rows)
                cached = rows
                info = {"fetched_on": today, "ok": True}
            except Exception as exc:  # 单个来源失败不影响其他来源，沿用缓存
                print(f"[warn] revolution {key}: {exc}", file=sys.stderr)
                info = {"fetched_on": info.get("fetched_on"), "ok": False, "error": str(exc)[:200], "tried_on": today}
        meta[key] = info
        data[key] = cached
    text = json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if not meta_path.exists() or meta_path.read_text(encoding="utf-8") != text:
        atomic_write_text(meta_path, text)
    return data, meta
