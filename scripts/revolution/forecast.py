"""成分级预测与滚动回测（纯 Python）。

为什么不直接预测 D/B/S/C：指数是本站自定的加权合成量，成分频率不一、历史短，
直接对它回测既循环（权重一改历史就变）又没有可结算的真实目标。所以只预测可观测成分，
按成分自身的发布频率预测后 h 期，到期用真实发布值结算；指数预测由成分预测推导，标注「衍生」，不单独计分。

对每个成分、每个周期 h：
- 基准：不变预测（随机游走）ŷ = y_t。对增速、金融状况这类高持续性序列很难打败。
- 模型：直接多步回归 y_{t+h} = a + b·y_t（扩展窗口 OLS，只用 t 时已实现的样本对）。
  b < 1 时向历史均值回归；直接法避免迭代误差累积（Marcellino-Stock-Watson 2006）。
- 区间：所用方法在过去样本外误差的经验 10% / 90% 分位（不假设正态）。样本外误差不足 MIN_INTERVAL 时不给区间。
- 门槛（与资产走势预测一致并更严）：样本外点数 ≥ MIN_OOS、MSE 技能分 ≥ 1%、DM 单侧 p < 0.05 才显示模型，
  否则显示基准；点数不足时状态为 insufficient（样本不足，仅示意）。
- 阈值概率（如 NFCI 13 周后 > 0）：基准 = 不变预测 + 基准的经验误差分布，模型 = 点预测 + 模型的经验误差分布，比较 Brier。
  不用无条件历史发生率当基准：高持续性序列只要知道当前水平就能大幅「打败」发生率，那不是模型的本事。
  历史发生率另行输出，仅作背景。
"""

from __future__ import annotations

import math
from bisect import bisect_right, insort

MIN_TRAIN = 20       # 开始预测前至少需要的训练样本对
MIN_OOS = 40         # 上线门槛：样本外点数
MIN_INTERVAL = 20    # 给出区间所需的样本外误差数
GATE_SKILL = 0.01
GATE_P = 0.05
QUANTILES = (0.1, 0.9)


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def newey_west_var(d, lags):
    n = len(d)
    mu = sum(d) / n
    e = [x - mu for x in d]
    var = sum(x * x for x in e) / n
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * sum(e[i] * e[i - k] for i in range(k, n)) / n
    return max(var, 1e-18)


def dm_test(loss_base, loss_model, h):
    """单侧 DM：H1 模型损失更小。重叠预测用 Newey-West（滞后 h−1）。"""
    d = [b - m for b, m in zip(loss_base, loss_model)]
    if len(d) < 30:
        return None
    stat = (sum(d) / len(d)) / math.sqrt(newey_west_var(d, max(0, h - 1)) / len(d))
    return 1 - phi(stat)


class Errors:
    """有序误差池。"""

    def __init__(self):
        self.values = []

    def add(self, value):
        insort(self.values, value)

    def __len__(self):
        return len(self.values)

    def quantile(self, q):
        v = self.values
        pos = q * (len(v) - 1)
        low = int(pos)
        high = min(low + 1, len(v) - 1)
        return v[low] + (v[high] - v[low]) * (pos - low)

    def share_above(self, threshold):
        return 1 - bisect_right(self.values, threshold) / len(self.values)


def walk_forward(values, h, event=None):
    """values: 按期连续的序列（不允许缺期）。返回逐起点预测列表与最后一个起点的预测。

    每个起点 t：先把目标在 t 期实现的样本对 (y_{t-h}, y_t) 加入训练，再用 y_t 预测 y_{t+h}。
    """
    n = len(values)
    sx = sy = sxx = sxy = 0.0
    m = 0
    err_b, err_m = Errors(), Errors()
    pending = {}  # 起点 → 预测，等目标实现后计入误差池
    hits = events = 0
    out = []
    for t in range(n):
        s = t - h
        if s >= 0:
            x, y = values[s], values[t]
            sx, sy, sxx, sxy, m = sx + x, sy + y, sxx + x * x, sxy + x * y, m + 1
            if s in pending:
                err_b.add(y - pending[s]["baseline"])
                err_m.add(y - pending[s]["model"])
            if event is not None:
                events += 1
                hits += y > event
        if m < MIN_TRAIN:
            continue
        var = sxx - sx * sx / m
        b = (sxy - sx * sy / m) / var if var > 1e-12 else 0.0
        a = (sy - b * sx) / m
        item = {"t": t, "baseline": values[t], "model": a + b * values[t], "b": b, "a": a}
        for kind, pool in (("baseline", err_b), ("model", err_m)):
            if len(pool) >= MIN_INTERVAL:
                item[f"{kind}_q"] = [item[kind] + pool.quantile(q) for q in QUANTILES]
        if event is not None and len(err_m) >= MIN_INTERVAL and events:
            item["p_baseline"] = err_b.share_above(event - item["baseline"])
            item["p_model"] = err_m.share_above(event - item["model"])
            item["p_rate"] = hits / events
        if t + h < n:
            item["realized"] = values[t + h]
        pending[t] = item
        out.append(item)
    return out, (out[-1] if out else None)


def score(forecasts, h, event=None):
    sample = [f for f in forecasts if "realized" in f]
    stats = {"n": len(sample)}
    if not sample:
        return stats
    se_b = [(f["realized"] - f["baseline"]) ** 2 for f in sample]
    se_m = [(f["realized"] - f["model"]) ** 2 for f in sample]
    stats["mse_baseline"], stats["mse_model"] = sum(se_b) / len(se_b), sum(se_m) / len(se_m)
    stats["mae_baseline"] = sum(abs(f["realized"] - f["baseline"]) for f in sample) / len(sample)
    stats["mae_model"] = sum(abs(f["realized"] - f["model"]) for f in sample) / len(sample)
    stats["skill"] = 1 - stats["mse_model"] / stats["mse_baseline"] if stats["mse_baseline"] > 0 else 0.0
    stats["dm_p"] = dm_test(se_b, se_m, h)
    for kind in ("baseline", "model"):
        covered = [f for f in sample if f"{kind}_q" in f]
        stats[f"coverage_{kind}"] = (sum(f[f"{kind}_q"][0] <= f["realized"] <= f[f"{kind}_q"][1] for f in covered) / len(covered)
                                     if covered else None)
    if event is not None:
        scored = [f for f in sample if "p_model" in f]
        if scored:
            br_b = [(f["p_baseline"] - (f["realized"] > event)) ** 2 for f in scored]
            br_m = [(f["p_model"] - (f["realized"] > event)) ** 2 for f in scored]
            stats["event"] = {"n": len(scored), "brier_baseline": sum(br_b) / len(br_b), "brier_model": sum(br_m) / len(br_m),
                              "skill": 1 - sum(br_m) / sum(br_b) if sum(br_b) > 0 else 0.0, "dm_p": dm_test(br_b, br_m, h),
                              "rate": sum(f["realized"] > event for f in scored) / len(scored)}
    stats["start"], stats["end"] = sample[0]["t"], sample[-1]["t"]
    return stats


def choose(stats, skill_key="skill", p_key="dm_p"):
    """返回 (采用的方法, 状态)。状态：model / baseline / insufficient。"""
    if stats.get("n", 0) < MIN_OOS:
        return "baseline", "insufficient"
    if stats.get(skill_key, 0) >= GATE_SKILL and stats.get(p_key) is not None and stats[p_key] < GATE_P:
        return "model", "model"
    return "baseline", "baseline"


def contiguous_tail(rows, step_ok):
    """取最后一段不缺期的序列（遇到缺期就从缺期之后开始），保证 t+h 真的是 h 期之后。"""
    start = 0
    for i in range(1, len(rows)):
        if not step_ok(rows[i - 1]["date"], rows[i]["date"]):
            start = i
    return rows[start:]
