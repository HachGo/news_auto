"""行情概率问题：规则生成、到期自动结算、Brier 评分（不用模型）。

问题形如“{资产} 在 {截止日} 或之后首个交易日收盘，会高于提问当日吗？”。
结算不比较点位：同一资产的点位在新浪 / 东方财富之间可能差 15–20%（不同合约口径），
而每日涨跌幅在各自来源内自洽，所以用提问日之后各交易日的涨跌幅复利累计判断涨跌。
休市日快照会重复上一交易日的点位与涨跌幅，这类重复不计为交易日。

概率：近 20 个交易日涨跌幅的均值（按一半计入）与标准差，正态近似
p = Φ(μ·√t / σ)，t 为交易日数（周 5 / 月 21），截断到 [5%, 95%]。
基准：近 20 个交易日上涨天数占比（拉普拉斯平滑），作为“无模型”对照，不是预测市场价格。

问题与结算分别追加写入 data/trends/market_questions/ 与 market_resolutions/，从不覆盖。
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, pstdev

from generators.market import QUOTE_NAMES_EN

MODEL_VERSION = "market-v1"
HORIZONS = {"week": {"days": 7, "trading": 5}, "month": {"days": 30, "trading": 21}}
LOOKBACK = 20
DRIFT_SHRINK = 0.5
P_MIN, P_MAX = 0.05, 0.95
VOID_AFTER_DAYS = 7  # 截止后 7 个自然日（约 5 个交易日）仍无行情则作废
CALIBRATION_MIN = 20
BINS = ((0, 20), (20, 40), (40, 60), (60, 80), (80, 100))
HORIZON_TEXT = {"week": ("一周", "one week"), "month": ("一个月", "one month")}


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def observations(rows, name):
    """该资产的交易日观测 [(快照日期, 涨跌幅%)]；与前一日点位和涨跌幅完全相同的视为休市重复。"""
    output, previous = [], None
    for row in rows:
        quote = next((q for q in row.get("market_quotes") or [] if q.get("name") == name), None)
        if not quote or quote.get("is_stale") or not isinstance(quote.get("change_pct"), (int, float)) or not quote.get("price"):
            continue
        key = (quote["price"], quote["change_pct"])
        if key != previous:
            output.append((row["date"], float(quote["change_pct"])))
        previous = key
    return output


def probability(changes, trading_days):
    """上涨概率（%）与模型参数。"""
    sigma = pstdev(changes)
    drift = DRIFT_SHRINK * mean(changes)
    p = 0.5 if sigma == 0 else phi(drift * math.sqrt(trading_days) / sigma)
    return round(100 * min(P_MAX, max(P_MIN, p))), round(sigma, 2), round(drift, 2)


def baseline(changes):
    ups = sum(change > 0 for change in changes)
    return round(100 * (ups + 1) / (len(changes) + 2))


def create_questions(rows, date_str, open_keys):
    """为每个资产、每个周期生成一个问题；同一资产同一周期已有未结算问题时不再生成。"""
    if not rows or rows[-1]["date"] != date_str:
        return []
    questions = []
    for quote in rows[-1].get("market_quotes") or []:
        name = quote.get("name")
        obs = observations(rows, name)
        if len(obs) < LOOKBACK or obs[-1][0] != date_str:
            continue
        changes = [change for _, change in obs[-LOOKBACK:]]
        name_en = QUOTE_NAMES_EN.get(name, name)
        for horizon, spec in HORIZONS.items():
            if (name, horizon) in open_keys:
                continue
            p, sigma, drift = probability(changes, spec["trading"])
            deadline = (date.fromisoformat(date_str) + timedelta(days=spec["days"])).isoformat()
            zh_h, en_h = HORIZON_TEXT[horizon]
            questions.append({
                "id": f"mq-{horizon}-{date_str}-{quote.get('symbol') or name}",
                "quote": name, "horizon": horizon, "created": date_str, "deadline": deadline,
                "p": p, "baseline": baseline(changes), "model_version": MODEL_VERSION,
                "question": {"zh": f"{name}在 {deadline} 或之后首个交易日收盘，会高于 {date_str} 吗？",
                             "en": f"Will {name_en} close higher on the first trading day on or after {deadline} than on {date_str}?"},
                "rationale": {"zh": f"近 {LOOKBACK} 个交易日波动 {sigma:.2f}%/日，平均涨跌 {2 * drift:+.2f}%/日（按一半计入），周期约 {spec['trading']} 个交易日（{zh_h}）。",
                              "en": f"{LOOKBACK}-day volatility {sigma:.2f}%/day; average move {2 * drift:+.2f}%/day, counted at half weight; about {spec['trading']} trading days ({en_h})."},
            })
    return questions


def resolve(question, rows, date_str):
    """返回结算结果；尚未到期或等待行情时返回 None。"""
    if date_str < question["deadline"]:
        return None
    obs = observations(rows, question["quote"])
    after = [(day, change) for day, change in obs if day > question["created"]]
    final = next((index for index, (day, _) in enumerate(after) if day >= question["deadline"]), None)
    if final is None:
        if (date.fromisoformat(date_str) - date.fromisoformat(question["deadline"])).days > VOID_AFTER_DAYS:
            return {"id": question["id"], "status": "void", "resolved_on": date_str}
        return None
    growth = 1.0
    for _, change in after[:final + 1]:
        growth *= 1 + change / 100
    outcome = int(growth > 1)
    p, b = question["p"] / 100, question["baseline"] / 100
    return {"id": question["id"], "status": "resolved", "resolved_on": after[final][0],
            "change_pct": round((growth - 1) * 100, 2), "outcome": outcome,
            "brier": round((p - outcome) ** 2, 4), "baseline_brier": round((b - outcome) ** 2, 4)}


def run(trend_dir, date_str, rows=None):
    """当日首次运行时生成问题，并结算到期问题；只追加新文件或新记录。"""
    from radar import load_daily
    trend_dir = Path(trend_dir)
    rows = rows if rows is not None else load_daily(trend_dir / "daily", date_str, 10000)
    questions, resolutions = load(trend_dir)
    pending = [q for q in questions if q["id"] not in resolutions]
    found = []
    for question in pending:
        result = resolve(question, rows, date_str)
        if result:
            found.append(result)
            resolutions[question["id"]] = result
    if found:
        _append(trend_dir / "market_resolutions" / f"{date_str}.json", "resolutions", found)
    question_path = trend_dir / "market_questions" / f"{date_str}.json"
    created = []
    if not question_path.exists():
        open_keys = {(q["quote"], q["horizon"]) for q in questions if q["id"] not in resolutions}
        created = create_questions(rows, date_str, open_keys)
        if created:
            _write(question_path, {"date": date_str, "questions": created})
    return {"created": created, "resolved": found}


def load(trend_dir):
    questions, resolutions = [], {}
    for path in sorted((Path(trend_dir) / "market_questions").glob("*.json")):
        questions.extend(_read(path).get("questions") or [])
    for path in sorted((Path(trend_dir) / "market_resolutions").glob("*.json")):
        for item in _read(path).get("resolutions") or []:
            resolutions.setdefault(item["id"], item)
    return questions, resolutions


def summary(trend_dir, date_str):
    """预测页与首页使用的问题列表、Brier 记录和分箱校准。"""
    questions, resolutions = load(trend_dir)
    questions = [q for q in questions if q["created"] <= date_str]
    today = date.fromisoformat(date_str)
    opened = [{**q, "days_left": max(0, (date.fromisoformat(q["deadline"]) - today).days)}
              for q in questions if q["id"] not in resolutions]
    opened.sort(key=lambda q: (q["deadline"], -abs(q["p"] - 50), q["id"]))
    done = [{**q, **resolutions[q["id"]]} for q in questions
            if q["id"] in resolutions and resolutions[q["id"]]["status"] == "resolved"]
    done.sort(key=lambda q: (q["resolved_on"], q["id"]), reverse=True)
    voided = sum(1 for q in questions if resolutions.get(q["id"], {}).get("status") == "void")
    record = {"resolved": len(done), "open": len(opened), "void": voided,
              "brier": round(mean(q["brier"] for q in done), 3) if done else None,
              "baseline_brier": round(mean(q["baseline_brier"] for q in done), 3) if done else None}
    calibration = []
    for low, high in BINS:
        inside = [q for q in done if low <= q["p"] < high or (high == 100 and q["p"] == 100)]
        calibration.append({"label": f"{low}–{high}", "n": len(inside),
                            "predicted": round(mean(q["p"] for q in inside)) if inside else None,
                            "observed": round(100 * mean(q["outcome"] for q in inside)) if inside else None})
    return {"open": opened, "resolved": done[:50], "record": record, "calibration": calibration,
            "calibration_ready": len(done) >= CALIBRATION_MIN, "calibration_min": CALIBRATION_MIN}


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path, payload):
    from common import atomic_write_text
    atomic_write_text(Path(path), json.dumps(payload, ensure_ascii=False, indent=1) + "\n")


def _append(path, key, items):
    """同日多次运行时追加到当日文件，已有记录不改动。"""
    payload = _read(path) or {"date": Path(path).stem, key: []}
    known = {item["id"] for item in payload.get(key) or []}
    payload[key] = (payload.get(key) or []) + [item for item in items if item["id"] not in known]
    _write(path, payload)
