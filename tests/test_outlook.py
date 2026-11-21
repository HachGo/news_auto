import json
import math
import random
from datetime import date, timedelta

import pytest

from outlook import build, history, model
from trends import market_forecast


def synthetic(n=1500, seed=1, kind="walk"):
    """确定性的合成日 K：walk 为带小漂移的随机游走；mean_revert 为对数价格的均值回复过程。"""
    rng = random.Random(seed)
    rows, log_price, day = [], math.log(100), date(2015, 1, 1)
    for _ in range(n):
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        shock = rng.gauss(0, 0.01 if kind == "walk" else 0.05)
        if kind == "walk":
            log_price += 0.0003 + shock
        else:
            log_price = math.log(20) + 0.9 * (log_price - math.log(20)) + shock
        close = math.exp(log_price)
        spread = abs(rng.gauss(0, 0.008 if kind == "walk" else 0.04))
        rows.append({"date": day.isoformat(), "open": close, "high": close * math.exp(spread), "low": close * math.exp(-spread), "close": close})
    return rows


def test_clean_drops_non_positive_and_fills_missing_range():
    rows = history.clean([
        {"date": "2020-04-21", "open": 1, "high": None, "low": None, "close": 10},
        {"date": "2020-04-20", "open": 1, "high": 2, "low": -40, "close": -37.6},
        {"date": "2020-04-21", "open": 1, "high": 12, "low": 9, "close": 11},
    ])
    assert rows == [{"date": "2020-04-21", "open": 1.0, "high": 12.0, "low": 9.0, "close": 11.0}]


def test_update_fetches_full_history_then_increments(tmp_path):
    asset = {"key": "x"}
    calls = []
    rows = synthetic(300)

    def fetcher(a, start):
        calls.append(start)
        return rows if start == history.START else [{**rows[-1], "close": 999.0}]

    first = history.update(asset, tmp_path, date.fromisoformat(rows[-1]["date"]) + timedelta(days=1), fetcher=fetcher)
    assert len(first) == 300 and calls == [history.START]
    second = history.update(asset, tmp_path, date.fromisoformat(rows[-1]["date"]) + timedelta(days=2), fetcher=fetcher)
    assert calls[-1] > history.START
    assert second[-1]["close"] == 999.0 and len(second) == 300
    assert history.read_cache(tmp_path / "x.csv")[-1]["close"] == 999.0


def test_update_keeps_cache_when_fetch_fails(tmp_path):
    rows = synthetic(300)
    history.write_cache(tmp_path / "x.csv", rows)
    kept = history.update({"key": "x"}, tmp_path, date(2030, 1, 1), fetcher=lambda a, s: [])
    assert len(kept) == 300


def test_walk_forward_has_no_lookahead():
    rows = synthetic(1100)
    full, _ = model.walk_forward(rows, 5, ["tsmom12", "tsmom3"])
    cut = 1000
    _, last = model.walk_forward(rows[:cut], 5, ["tsmom12", "tsmom3"])
    same = next(f for f in full if f["t"] == cut - 1)
    assert last["t"] == cut - 1
    assert last["model"] == same["model"] and last["baseline"] == same["baseline"]
    assert "realized" not in last


def test_random_walk_keeps_baseline_and_intervals_are_calibrated():
    rows = synthetic(1500)
    forecasts, _ = model.walk_forward(rows, 5, ["tsmom12", "tsmom3"])
    stats = model.score(forecasts, 5)
    assert model.choose(stats) == "baseline"
    assert 0.7 <= stats["baseline"]["coverage80"] <= 0.9


def test_mean_reversion_signal_beats_baseline():
    rows = synthetic(2500, kind="mean_revert")
    forecasts, last = model.walk_forward(rows, 5, ["vix_mr"])
    stats = model.score(forecasts, 5)
    assert stats["skill"] > model.GATE_SKILL and stats["dm_p"] < model.GATE_P
    assert model.choose(stats) == "model"
    assert last["parts"][0]["active"] and last["parts"][0]["b"] < 0


def test_wrong_sign_signal_falls_back_to_baseline():
    """Campbell-Thompson：均值回复序列上的动量信号符号为负，应被关闭。"""
    rows = synthetic(1500, kind="mean_revert")
    _, last = model.walk_forward(rows, 5, ["tsmom3"])
    assert not last["parts"][0]["active"]
    assert last["mean_z"]["model"] == last["mean_z"]["baseline"]


def test_dm_test_direction():
    stat, p = model.dm_test([1.0, 1.2] * 30, [0.5, 0.7] * 30, 5)
    assert stat > 0 and p < 0.01
    assert model.dm_test([1.0] * 10, [0.5] * 10, 5) == (None, None)


def test_build_outputs_and_question_link(tmp_path):
    assets = [{"key": "spx", "name": "标普500", "group": "us", "predictors": ["tsmom12", "tsmom3"]},
              {"key": "vix", "name": "VIX", "group": "vol", "predictors": ["vix_mr"]},
              {"key": "none", "name": "恒生科技", "group": "hk", "predictors": ["tsmom12"]}]
    data = {"spx": synthetic(1500), "vix": synthetic(2500, kind="mean_revert"), "none": []}
    payload = build.build(tmp_path, "2030-01-01", fetcher=lambda a, s: data[a["key"]], assets=assets)
    assert [a["key"] for a in payload["assets"]] == ["spx", "vix"]
    assert payload["missing"] == [{"zh": "恒生科技", "en": "Hang Seng Tech"}]
    spx = payload["assets"][0]
    assert set(spx["horizons"]) == {"week", "month", "quarter"}
    week = spx["horizons"]["week"]
    assert week["q"][0] < week["q"][1] < week["q"][2]
    assert week["fan"][0]["k"] == 0 and week["fan"][-1]["k"] == 5
    assert payload["assets"][1]["horizons"]["week"]["source"] == "model"
    small = build.summary(payload)
    assert "series" not in small["assets"][0] and "fan" not in small["assets"][0]["horizons"]["week"]
    json.dumps(payload)
    linked = build.questions_input(payload)
    assert linked[("VIX", "week")]["p"] == payload["assets"][1]["horizons"]["week"]["p_up"]


def _snapshots(n=25):
    rows, day = [], date(2026, 10, 1)
    for i in range(n):
        rows.append({"date": (day + timedelta(days=i)).isoformat(),
                     "market_quotes": [{"name": "VIX", "symbol": "VIX", "price": 20 + i, "change_pct": 1.0 if i % 2 else -0.5}]})
    return rows


def test_market_questions_use_outlook_probability():
    rows = _snapshots()
    today = rows[-1]["date"]
    plain = market_forecast.create_questions(rows, today, set())
    assert {q["horizon"] for q in plain} == {"week", "month"}
    rationale = {"zh": "模型", "en": "model"}
    linked = {("VIX", h): {"p": 14, "rationale": rationale, "source": "model"} for h in ("week", "month", "quarter")}
    questions = market_forecast.create_questions(rows, today, set(), linked)
    assert {q["horizon"] for q in questions} == {"week", "month", "quarter"}
    assert all(q["p"] == 14 and q["model_version"] == "outlook-v1" and q["rationale"] == rationale for q in questions)
