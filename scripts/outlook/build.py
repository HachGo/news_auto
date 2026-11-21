"""趋势与预测页的资产预测数据。

产物：
- data/radar/outlook.json：页面服务端渲染用的摘要（不含序列，Hugo 读取）。
- static/data/trends/outlook.json：图表用的完整数据（历史收盘 + 预测扇形），浏览器按需加载。
返回 {(展示名, 周期): {...}}，供行情概率问题使用同一组概率。
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

from generators.market import QUOTE_NAMES_EN

from . import history, model
from .assets import ASSETS, GROUPS, HORIZONS

MODEL_VERSION = "outlook-v1"
SERIES_DAYS = 504  # 约两年交易日，季度视图使用
SIGNALS = {
    "tsmom12": {"zh": "12 个月趋势动量", "en": "12-month trend"},
    "tsmom3": {"zh": "3 个月趋势动量", "en": "3-month trend"},
    "rev1w": {"zh": "一周反转", "en": "1-week reversal"},
    "vix_mr": {"zh": "相对一年均值的偏离（均值回复）", "en": "Distance from 1-year mean (mean reversion)"},
}


def add_business_days(day, count):
    current = date.fromisoformat(day)
    while count > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count -= 1
    return current.isoformat()


def pct(log_return):
    return round((math.exp(log_return) - 1) * 100, 2)


def _fan(last_date, close, q, h):
    """预测扇形：中位数随时间线性展开、区间按 √(k/h) 展开（随机游走的方差尺度）。"""
    points = [{"k": 0, "d": last_date, "lo": close, "mid": close, "hi": close}]
    for k in sorted({max(1, round(h * f)) for f in (0.25, 0.5, 0.75, 1.0)}):
        drift, scale = q[1] * k / h, math.sqrt(k / h)
        points.append({"k": k, "d": add_business_days(last_date, k),
                       "lo": round(close * math.exp(drift + scale * (q[0] - q[1])), 4),
                       "mid": round(close * math.exp(drift), 4),
                       "hi": round(close * math.exp(drift + scale * (q[2] - q[1])), 4)})
    return points


def _round(stats):
    out = {"n": stats["n"], "start": stats["start"], "end": stats["end"],
           "skill": round(stats["skill"] * 100, 1) + 0.0, "skill_pinball": round(stats["skill_pinball"] * 100, 1) + 0.0,  # +0.0 去掉 -0.0
           "dm_p": round(stats["dm_p"], 3) if stats["dm_p"] is not None else None, "up_rate": round(stats["up_rate"] * 100)}
    for kind in ("baseline", "model"):
        k = stats[kind]
        out[kind] = {"brier": round(k["brier"], 4), "coverage80": round(k["coverage80"] * 100),
                     "hit_rate": round(k["hit_rate"] * 100) if k["hit_rate"] is not None else None,
                     "calibration": [{**c, "predicted": round(c["predicted"] * 100), "observed": round(c["observed"] * 100)}
                                     for c in k["calibration"]]}
    return out


def _drivers(last, used):
    """各信号对预测均值的贡献（单位：σ），未通过符号约束的信号贡献为 0。"""
    n = len(last["parts"])
    base = last["mean_z"]["baseline"]
    return [{"key": part["name"], "name": SIGNALS[part["name"]], "x": round(part["x"], 2) if part["x"] is not None else None,
             "active": part["active"] and used == "model",
             "effect": round((part["forecast"] - base) / n, 3) if used == "model" else 0.0}
            for part in last["parts"]]


def _rationale(used, stats, h):
    skill, p = stats["skill"], stats["dm_p"]
    p_text = f"{p:.3f}" if p is not None else "—"
    if used == "model":
        return {"zh": f"HAR 波动率 + 信号组合。滚动回测 {stats['n']} 次（{stats['start'][:4]}–{stats['end'][:4]}），Brier 技能分 {skill:+.1f}%，DM 检验 p={p_text}。",
                "en": f"HAR volatility + signal combination. {stats['n']} walk-forward tests ({stats['start'][:4]}–{stats['end'][:4]}), Brier skill {skill:+.1f}%, DM test p={p_text}."}
    return {"zh": f"基准：历史平均漂移 + HAR 波动率。信号模型回测技能分 {skill:+.1f}%（p={p_text}），未达到上线门槛。",
            "en": f"Baseline: historical average drift + HAR volatility. The signal model scored {skill:+.1f}% skill in backtests (p={p_text}), below the publishing bar."}


def forecast_asset(asset, rows):
    """单个资产三个周期的预测；历史不足时返回 None。"""
    if len(rows) < model.MIN_HAR + model.MIN_SIGNAL * 2 + 63:
        return None
    last_row = rows[-1]
    horizons = {}
    for horizon, h in HORIZONS.items():
        forecasts, last = model.walk_forward(rows, h, asset["predictors"])
        stats = model.score(forecasts, h)
        if not last or not stats or last["date"] != last_row["date"]:
            continue
        stats = _round(stats)
        used = model.choose({**stats, "skill": stats["skill"] / 100})
        dist = last[used]
        horizons[horizon] = {
            "h": h, "source": used, "target_date": add_business_days(last_row["date"], h),
            "p_up": round(dist["p_up"] * 100), "p_up_baseline": round(last["baseline"]["p_up"] * 100),
            "p_up_model": round(last["model"]["p_up"] * 100),
            "q": [pct(v) for v in dist["q"]], "price_q": [round(last_row["close"] * math.exp(v), 2) for v in dist["q"]],
            "fan": _fan(last_row["date"], last_row["close"], dist["q"], h),
            "drivers": _drivers(last, used), "backtest": stats, "rationale": _rationale(used, stats, h),
        }
    if not horizons:
        return None
    closes = rows[-SERIES_DAYS:]
    return {
        "key": asset["key"], "group": asset["group"], "name": {"zh": asset["name"], "en": QUOTE_NAMES_EN.get(asset["name"], asset["name"])},
        "as_of": last_row["date"], "close": round(last_row["close"], 2),
        "change_1w": pct(math.log(last_row["close"] / rows[-6]["close"])),
        "series": [[row["date"], round(row["close"], 4)] for row in closes],
        "horizons": horizons,
    }


def build(history_dir, date_str, fetcher=history.fetch, assets=ASSETS):
    items, missing = [], []
    for asset in assets:
        try:
            rows = history.update(asset, history_dir, date.fromisoformat(date_str), fetcher=fetcher)
            item = forecast_asset(asset, rows)
        except Exception as exc:  # 单个资产失败不影响其他资产
            print(f"[warn] outlook {asset['key']}: {exc}", file=sys.stderr)
            item = None
        if item:
            items.append(item)
        else:
            missing.append({"zh": asset["name"], "en": QUOTE_NAMES_EN.get(asset["name"], asset["name"])})
    groups = [{"key": key, "name": name, "assets": [item["key"] for item in items if item["group"] == key]}
              for key, name in GROUPS.items()]
    return {"as_of": date_str, "model_version": MODEL_VERSION, "horizons": list(HORIZONS),
            "groups": [g for g in groups if g["assets"]], "assets": items, "missing": missing,
            "gate": {"skill": round(model.GATE_SKILL * 100), "p": model.GATE_P}}


def summary(payload):
    """去掉序列和扇形，供 Hugo 服务端渲染。"""
    assets = []
    for item in payload["assets"]:
        horizons = {key: {k: v for k, v in value.items() if k != "fan"} for key, value in item["horizons"].items()}
        assets.append({**{k: v for k, v in item.items() if k != "series"}, "horizons": horizons})
    return {**payload, "assets": assets}


def questions_input(payload):
    """{(展示名, 周期): 概率与说明}，行情概率问题直接采用页面上展示的同一个概率。"""
    return {(item["name"]["zh"], horizon): {"p": value["p_up"], "rationale": value["rationale"], "source": value["source"]}
            for item in payload["assets"] for horizon, value in item["horizons"].items()}


def run(root, date_str, fetcher=history.fetch):
    from common import atomic_write_text
    root = Path(root)
    payload = build(root / "history", date_str, fetcher=fetcher)
    for path, data in ((root / "static" / "data" / "trends" / "outlook.json", payload),
                       (root / "data" / "radar" / "outlook.json", summary(payload))):
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            atomic_write_text(path, text)
    return payload
