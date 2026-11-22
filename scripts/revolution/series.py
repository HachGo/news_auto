"""指标变换与 D/B/S/C 指数。

指数按月计算，每个月只使用「当月末之前已经公布」的观测（观测期末 + 发布滞后 ≤ 月末），
标准化用扩展窗口（只用当月及以前的值），因此任何一个月的读数都不含未来信息，时间轴回放可以直接逐月展示。
局限：用的是最新修订值而不是当时的初值（页面注明）。

指数 = 50 + 10 × 平均(方向 × 截断后的 z 值)。成分缺失时不填补：只对可得成分取平均，并输出覆盖率；
一个成分都没有的月份输出 null。
"""

from __future__ import annotations

import calendar
import math
from bisect import bisect_right
from datetime import date, timedelta

from .catalog import CAPEX_COMPANIES, INDEX_ORDER, INDICATORS

START_MONTH = "2000-01"
MIN_Z_MONTHS = 36   # 扩展窗口标准化至少需要 3 年月度读数
CLIP = 4.0
# 观测期末超过这个天数仍无新数据就视为缺失（不沿用过旧的值）
MAX_AGE = {"daily": 14, "weekly": 35, "biweekly": 35, "monthly": 75, "quarterly": 200, "event": 75}


def month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def add_months(day, months):
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def period_end(day, freq):
    """FRED 月度 / 季度序列以期初日期标注；周度（NFCI 等）以周五即周末标注。"""
    d = date.fromisoformat(day)
    if freq == "monthly":
        return month_end(d.year, d.month)
    if freq == "quarterly":
        return _quarter_last(d)
    return d


def _quarter_last(d):
    end = add_months(date(d.year, d.month, 1), 2)
    return month_end(end.year, end.month)


def yoy(rows, freq):
    """同比（%）：与一年前同一期比较；一年前缺失的期不输出。"""
    by_key = {row["date"][:7]: row["value"] for row in rows}
    out = []
    for row in rows:
        year, month = int(row["date"][:4]), int(row["date"][5:7])
        prev = by_key.get(f"{year - 1}-{month:02d}")
        if prev and prev > 0:
            out.append({"date": row["date"], "value": round((row["value"] / prev - 1) * 100, 4)})
    return out


def dev_from_average(rows, window=756):
    """对数价格相对过去 window 个交易日均值的偏离（%）。"""
    logs = [math.log(row["value"]) for row in rows if row["value"] > 0]
    days = [row["date"] for row in rows if row["value"] > 0]
    out, total = [], 0.0
    for i, value in enumerate(logs):
        total += value
        if i >= window:
            total -= logs[i - window]
        if i >= window - 1:
            out.append({"date": days[i], "value": round((math.exp(value - total / window) - 1) * 100, 3)})
    return out


def frontier(models, start="2010-01"):
    """每月末的前沿训练算力 log10(FLOP)：截至当月发布的所有模型中的最大值。"""
    if not models:
        return []
    ordered = sorted(models, key=lambda m: m["date"])
    out, best, i = [], None, 0
    y, m = int(start[:4]), int(start[5:7])
    last = date.fromisoformat(ordered[-1]["date"])
    while (y, m) <= (last.year, last.month):
        end = month_end(y, m).isoformat()
        while i < len(ordered) and ordered[i]["date"] <= end:
            value = math.log10(ordered[i]["flop"])
            best = value if best is None else max(best, value)
            i += 1
        if best is not None:
            out.append({"date": f"{y}-{m:02d}-01", "value": round(best, 4)})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def change_12(rows):
    by_key = {row["date"][:7]: row["value"] for row in rows}
    out = []
    for row in rows:
        prev = by_key.get(f"{int(row['date'][:4]) - 1}{row['date'][4:7]}")
        if prev is not None:
            out.append({"date": row["date"], "value": round(row["value"] - prev, 4)})
    return out


def capex_total(raw):
    """四家公司在同一季度都有数据才相加，缺任何一家的季度不输出。"""
    series = [{row["date"]: row["value"] for row in raw.get(key, [])} for key, _ in CAPEX_COMPANIES]
    common = set(series[0]).intersection(*series[1:]) if series and all(series) else set()
    return [{"date": day, "value": sum(s[day] for s in series)} for day in sorted(common)]


def transform(indicator, raw):
    """返回指标自身频率下的序列 [{date, value}]（日期为观测期标注日）。"""
    name, kind = indicator["raw"], indicator["transform"]
    rows = capex_total(raw) if name == "CAPEX_TOTAL" else raw.get(name, [])
    if kind == "level":
        # 抽样调查（BTOS）带标准误，原样保留供图表画置信带
        return [{"date": r["date"], "value": r["value"], **({"se": r["se"]} if r.get("se") is not None else {})} for r in rows]
    if kind == "yoy":
        return yoy(rows, indicator["freq"])
    if kind == "dev3y":
        return dev_from_average(rows)
    if kind == "frontier_chg12":
        return change_12(frontier(rows))
    raise ValueError(kind)


def native_freq(indicator):
    # 前沿算力变换后是月度序列
    return "monthly" if indicator["transform"] == "frontier_chg12" else indicator["freq"]


def months_between(start, end_day):
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while (y, m) <= (end_day.year, end_day.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def as_of_monthly(rows, indicator, months):
    """每个月末当时可见的最新值；过旧或尚无数据为 None。"""
    freq = native_freq(indicator)
    lag = timedelta(days=indicator["lag_days"])
    ends = [period_end(r["date"], freq) for r in rows]
    visible = sorted((end + lag, end, r["value"]) for end, r in zip(ends, rows))
    keys = [v[0] for v in visible]
    # 前缀中观测期最新的一条（发布滞后相同时就是最后一条，这里不依赖这一点）
    newest, best = [], None
    for item in visible:
        if best is None or item[1] >= best[1]:
            best = item
        newest.append(best)
    out = []
    for y, m in months:
        cutoff = month_end(y, m)
        i = bisect_right(keys, cutoff) - 1
        if i < 0:
            out.append(None)
            continue
        _, obs_end, value = newest[i]
        out.append(value if (cutoff - obs_end).days <= MAX_AGE[freq] else None)
    return out


def expanding_z(values, min_n=MIN_Z_MONTHS):
    out, n, s, ss = [], 0, 0.0, 0.0
    for value in values:
        if value is None:
            out.append(None)
            continue
        n, s, ss = n + 1, s + value, ss + value * value
        if n < min_n:
            out.append(None)
            continue
        mean = s / n
        sd = math.sqrt(max(ss / n - mean * mean, 0.0))
        out.append(max(-CLIP, min(CLIP, (value - mean) / sd)) if sd > 1e-12 else 0.0)
    return out


def z_state(values, min_n=MIN_Z_MONTHS):
    """扩展窗口最后一个月的 (均值, 标准差)，用于把成分预测换算成 z 值。"""
    xs = [v for v in values if v is not None]
    if len(xs) < min_n:
        return None
    mean = sum(xs) / len(xs)
    sd = math.sqrt(max(sum(x * x for x in xs) / len(xs) - mean * mean, 0.0))
    return (mean, sd) if sd > 1e-12 else None


def build_indices(transformed, today):
    """transformed: {indicator_id: rows}。返回月份、各指数读数与覆盖率、各成分 z 值。"""
    months = months_between(START_MONTH, today)
    labels = [f"{y}-{m:02d}" for y, m in months]
    components, levels = {}, {}
    for indicator in INDICATORS:
        if not indicator["index"]:
            continue
        monthly = as_of_monthly(transformed.get(indicator["id"], []), indicator, months)
        levels[indicator["id"]] = monthly
        components[indicator["id"]] = [round(z, 3) if z is not None else None for z in expanding_z(monthly)]
    indices = {}
    for key in INDEX_ORDER:
        members = [ind for ind in INDICATORS if ind["index"] == key]
        values, coverage = [], []
        for i in range(len(months)):
            parts = [ind["sign"] * components[ind["id"]][i] for ind in members if components[ind["id"]][i] is not None]
            values.append(round(50 + 10 * sum(parts) / len(parts), 2) if parts else None)
            coverage.append(round(len(parts) / len(members), 2) if members else 0)
        indices[key] = {"values": values, "coverage": coverage, "members": [ind["id"] for ind in members]}
    # 去掉开头所有指数都为空的月份
    first = next((i for i in range(len(months)) if any(indices[k]["values"][i] is not None for k in INDEX_ORDER)), len(months))
    trim = lambda seq: seq[first:]
    return {
        "months": trim(labels),
        "indices": {k: {**v, "values": trim(v["values"]), "coverage": trim(v["coverage"])} for k, v in indices.items()},
        "components": {k: trim(v) for k, v in components.items()},
        # 不截断：z_state 需要与 expanding_z 相同的完整窗口
        "levels": levels,
    }
