"""收益分布预测与滚动回测（纯 Python，无第三方依赖）。

对每个资产、每个周期 h（交易日）做一次按时间顺序的单遍扫描，任何时点只用当时已经实现的数据：

1. 波动率：直接多步 HAR（Corsi 2009），对未来 h 日平均 Parkinson 日内方差取对数回归
   log RV̄(t+1..t+h) = b0 + bd·log RV_d + bw·log RV_w + bm·log RV_m，得到 σ_h(t)。
2. 标准化收益 z = R(t, t+h) / σ_h(t)。
3. 基准：z 的历史均值（Goyal-Welch 2008：样本外最难打败的对照）。
4. 模型：每个信号各做一元回归 z = a + b·x，Campbell-Thompson 约束（b 符号与理论相反时
   该信号退回基准），再对各信号预测等权平均（Rapach-Strauss-Zhou 2010）。
5. 分布：过滤历史模拟——σ_h ×（预测均值 + 实时残差的经验分布），给出分位数与上涨概率。

回测按周取样（每 5 个交易日一个起点）计算 Brier、分位数损失与区间覆盖率，
Diebold-Mariano 检验用 Newey-West 方差（滞后 = 重叠期数）。
"""

from __future__ import annotations

import math
from bisect import bisect_right, insort

LN2x4 = 4 * math.log(2)
MIN_HAR = 250       # HAR 回归最少训练行数
MIN_SIGNAL = 250    # 信号回归与残差池最少样本
CLIP = 3.0          # 信号截断（风险调整后的收益 t 值）
QUANTILES = (0.1, 0.5, 0.9)
EXPECTED_SIGN = {"tsmom12": 1, "tsmom3": 1, "rev1w": -1, "vix_mr": -1}
SAMPLE_EVERY = 5


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def parkinson(row):
    if row["high"] > row["low"] > 0:
        return math.log(row["high"] / row["low"]) ** 2 / LN2x4
    return None


def prepare(rows):
    """对数收盘价、日收益与日内方差；方差缺失（高低价相同）时用当日收益平方代替。"""
    logs = [math.log(row["close"]) for row in rows]
    returns = [0.0] + [logs[i] - logs[i - 1] for i in range(1, len(logs))]
    variance = []
    for row, r in zip(rows, returns):
        v = parkinson(row)
        variance.append(max(v if v is not None else r * r, 1e-8))
    return logs, returns, variance


class Prefix:
    """前缀和，O(1) 区间求和。"""

    def __init__(self, values):
        self.s = [0.0]
        for value in values:
            self.s.append(self.s[-1] + value)

    def sum(self, start, end):  # [start, end)
        return self.s[end] - self.s[start]

    def mean(self, start, end):
        return self.sum(start, end) / (end - start)


def signal_values(name, t, logs, returns, sq, logvix=None):
    """t 日收盘时可得的信号值；历史不足返回 None。"""
    def risk_adjusted(window):
        if t < window or t < 252:
            return None
        sd = math.sqrt(max(sq.mean(t - 251, t + 1), 1e-12))
        return max(-CLIP, min(CLIP, (logs[t] - logs[t - window]) / (sd * math.sqrt(window))))
    if name == "tsmom12":
        return risk_adjusted(252)
    if name == "tsmom3":
        return risk_adjusted(63)
    if name == "rev1w":
        return risk_adjusted(5)
    if name == "vix_mr":
        if t < 252:
            return None
        return max(-CLIP, min(CLIP, (logs[t] - logvix.mean(t - 251, t + 1)) / 0.3))
    raise ValueError(name)


def solve(matrix, vector, ridge=1e-6):
    """高斯消元解 (A + ridge·I) x = b。"""
    n = len(vector)
    a = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for i in range(n):
        a[i][i] += ridge
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        if abs(a[col][col]) < 1e-12:
            return None
        for r in range(n):
            if r != col:
                factor = a[r][col] / a[col][col]
                for c in range(col, n + 1):
                    a[r][c] -= factor * a[col][c]
    return [a[i][n] / a[i][i] for i in range(n)]


class OLS1:
    """一元回归的累加统计量。"""

    def __init__(self):
        self.n = self.sx = self.sy = self.sxx = self.sxy = 0.0

    def add(self, x, y):
        self.n += 1
        self.sx += x
        self.sy += y
        self.sxx += x * x
        self.sxy += x * y

    def coef(self):
        if self.n < 2:
            return None, None
        var = self.sxx - self.sx * self.sx / self.n
        if var <= 1e-12:
            return self.sy / self.n, 0.0
        b = (self.sxy - self.sx * self.sy / self.n) / var
        return (self.sy - b * self.sx) / self.n, b


class Pool:
    """有序残差池：分位数与超过阈值的比例。"""

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


def distribution(sigma, mean_z, pool):
    """收益分位数（对数收益）与上涨概率。"""
    return {"p_up": pool.share_above(-mean_z),
            "q": [sigma * (mean_z + pool.quantile(q)) for q in QUANTILES]}


def walk_forward(rows, h, predictors):
    """单遍实时扫描，返回每个起点的预测（含基准与模型）以及最后一日的状态。"""
    n = len(rows)
    logs, returns, variance = prepare(rows)
    rv = Prefix(variance)
    sq = Prefix([r * r for r in returns])
    logvix = Prefix(logs) if "vix_mr" in predictors else None
    xtx = [[0.0] * 4 for _ in range(4)]
    xty = [0.0] * 4
    har_n = 0
    base = OLS1()
    regs = {name: OLS1() for name in predictors}
    pool_b, pool_m = Pool(), Pool()
    sigma, fc_b, fc_m, xs, feat = {}, {}, {}, {}, {}
    forecasts = []
    last = None

    def har_x(t):
        if t < 21:
            return None
        return [1.0, math.log(variance[t]), math.log(rv.mean(t - 4, t + 1)), math.log(rv.mean(t - 21, t + 1))]

    for t in range(n):
        # 1) 起点 s = t - h 的目标在 t 日实现，加入训练集
        s = t - h
        if s >= 0:
            x = feat.get(s)
            if x is not None:
                y = math.log(rv.mean(s + 1, t + 1))
                for i in range(4):
                    xty[i] += x[i] * y
                    for j in range(4):
                        xtx[i][j] += x[i] * x[j]
                har_n += 1
            if s in sigma:
                z = (logs[t] - logs[s]) / sigma[s]
                base.add(1.0, z)
                for name, value in xs[s].items():
                    if value is not None:
                        regs[name].add(value, z)
                if s in fc_b:
                    pool_b.add(z - fc_b[s])
                    pool_m.add(z - fc_m[s])
        # 2) t 日收盘时的预测
        feat[t] = har_x(t)
        if feat[t] is None or har_n < MIN_HAR:
            continue
        coef = solve(xtx, xty)
        if coef is None:
            continue
        log_rv = sum(c * v for c, v in zip(coef, feat[t]))
        sigma[t] = math.sqrt(h * math.exp(log_rv))
        xs[t] = {name: signal_values(name, t, logs, returns, sq, logvix) for name in predictors}
        if base.n < MIN_SIGNAL:
            continue
        mean_z = base.sy / base.n
        parts = []
        for name in predictors:
            value = xs[t][name]
            a, b = regs[name].coef()
            active = value is not None and b is not None and regs[name].n >= MIN_SIGNAL and b * EXPECTED_SIGN[name] > 0
            parts.append({"name": name, "x": value, "b": b if active else 0.0, "active": active,
                          "forecast": a + b * value if active else mean_z})
        fc_b[t] = mean_z
        fc_m[t] = sum(part["forecast"] for part in parts) / len(parts)
        if len(pool_b) < MIN_SIGNAL:
            continue
        item = {"t": t, "date": rows[t]["date"], "sigma": sigma[t],
                "baseline": distribution(sigma[t], fc_b[t], pool_b),
                "model": distribution(sigma[t], fc_m[t], pool_m),
                "mean_z": {"baseline": fc_b[t], "model": fc_m[t]}, "parts": parts}
        if t + h < n:
            item["realized"] = logs[t + h] - logs[t]
        forecasts.append(item)
        last = item
    return forecasts, last


def pinball(q_values, realized):
    return sum(max(q * (realized - v), (q - 1) * (realized - v)) for q, v in zip(QUANTILES, q_values)) / len(QUANTILES)


def newey_west_var(d, lags):
    n = len(d)
    mu = sum(d) / n
    e = [x - mu for x in d]
    var = sum(x * x for x in e) / n
    for k in range(1, lags + 1):
        cov = sum(e[i] * e[i - k] for i in range(k, n)) / n
        var += 2 * (1 - k / (lags + 1)) * cov
    return max(var, 1e-18)


def dm_test(loss_base, loss_model, h):
    """单侧 DM 检验：H1 模型损失更小。返回 (统计量, p 值)。"""
    d = [b - m for b, m in zip(loss_base, loss_model)]
    if len(d) < 30:
        return None, None
    lags = max(0, math.ceil(h / SAMPLE_EVERY) - 1)
    stat = (sum(d) / len(d)) / math.sqrt(newey_west_var(d, lags) / len(d))
    return stat, 1 - phi(stat)


def score(forecasts, h):
    """按周取样的回测得分。"""
    sample = [f for f in forecasts if "realized" in f and f["t"] % SAMPLE_EVERY == 0]
    if not sample:
        return None
    out = {"n": len(sample), "start": sample[0]["date"], "end": sample[-1]["date"]}
    losses = {}
    for kind in ("baseline", "model"):
        brier = [(f[kind]["p_up"] - (f["realized"] > 0)) ** 2 for f in sample]
        pin = [pinball(f[kind]["q"], f["realized"]) for f in sample]
        cover = sum(f[kind]["q"][0] <= f["realized"] <= f[kind]["q"][2] for f in sample) / len(sample)
        called = [f for f in sample if f[kind]["p_up"] != 0.5]
        hit = sum((f[kind]["p_up"] > 0.5) == (f["realized"] > 0) for f in called)
        losses[kind] = (brier, pin)
        out[kind] = {"brier": sum(brier) / len(brier), "pinball": sum(pin) / len(pin), "coverage80": cover,
                     "hit_rate": hit / len(called) if called else None,
                     "calibration": calibration(sample, kind)}
    out["up_rate"] = sum(f["realized"] > 0 for f in sample) / len(sample)
    out["skill"] = 1 - out["model"]["brier"] / out["baseline"]["brier"] if out["baseline"]["brier"] else 0.0
    out["skill_pinball"] = 1 - out["model"]["pinball"] / out["baseline"]["pinball"] if out["baseline"]["pinball"] else 0.0
    out["dm_stat"], out["dm_p"] = dm_test(losses["baseline"][0], losses["model"][0], h)
    return out


def calibration(sample, kind):
    """展示所用概率的分箱校准（10 个百分点一档，只列有样本的档）。"""
    bins = {}
    for f in sample:
        p = f[kind]["p_up"]
        key = min(int(p * 10), 9)
        bins.setdefault(key, []).append((p, f["realized"] > 0))
    return [{"bin": f"{k * 10}–{k * 10 + 10}", "n": len(v), "predicted": sum(p for p, _ in v) / len(v),
             "observed": sum(o for _, o in v) / len(v)} for k, v in sorted(bins.items())]


GATE_P = 0.05
GATE_SKILL = 0.01


def choose(stats):
    """上线门槛：Brier 技能分 ≥ 1% 且 DM 单侧 p < 0.05 才采用模型，否则显示基准。

    约 30 个资产×周期同时检验，p < 0.10 会放进约 3 个偶然胜出的模型，所以门槛比单次检验更严。
    """
    return ("model" if stats and stats["skill"] >= GATE_SKILL and stats["dm_p"] is not None and stats["dm_p"] < GATE_P
            else "baseline")
