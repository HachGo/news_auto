import json
import math
import random
from datetime import date

import pytest

from revolution import build, catalog, forecast, series, sources


# ---------- 数据源 ----------

def test_quarterly_from_ytd_cash_flow_facts():
    """10-Q 累计值相减得到单季；财年末季度 = 10-K 全年 − 九个月累计。"""
    facts = [
        {"start": "2025-07-01", "end": "2025-09-30", "val": 10, "filed": "2025-10-30"},
        {"start": "2025-07-01", "end": "2025-12-31", "val": 25, "filed": "2026-01-30"},
        {"start": "2025-07-01", "end": "2026-03-31", "val": 45, "filed": "2026-04-30"},
        {"start": "2025-07-01", "end": "2026-06-30", "val": 70, "filed": "2026-07-30"},
        {"start": "2025-07-01", "end": "2025-09-30", "val": 11, "filed": "2026-10-30"},  # 次年 10-Q 中的修订值
    ]
    rows = sources.quarterly_from_facts(facts)
    assert rows == [{"date": "2025-07-01", "value": 11}, {"date": "2025-10-01", "value": 14},
                    {"date": "2026-01-01", "value": 20}, {"date": "2026-04-01", "value": 25}]


def test_quarterly_leaves_gap_when_not_derivable():
    facts = [{"start": "2017-01-01", "end": "2017-03-31", "val": 5},
             {"start": "2017-01-01", "end": "2017-09-30", "val": 20}]  # 缺六个月累计，不能推出 Q2/Q3
    assert sources.quarterly_from_facts(facts) == [{"date": "2017-01-01", "value": 5}]


def test_parse_epoch_keeps_only_models_with_compute():
    text = ("Model,Organization,Publication date,Training compute (FLOP)\n"
            "A,Lab,2024-01-02,1e25\nB,Lab,2024-02-01,\nC,Lab,bad,1e20\n")
    assert sources.parse_epoch(text) == [{"date": "2024-01-02", "flop": 1e25, "model": "A", "organization": "Lab"}]


def test_load_all_keeps_cache_and_flags_failure(tmp_path):
    calls = []

    def ok(key, root):
        calls.append(key)
        return [{"date": "2020-01-01", "value": 1.0}]
    data, meta = sources.load_all(tmp_path, "2026-01-01", fetcher=ok, keys=["NFCI"])
    assert data["NFCI"] and meta["NFCI"]["ok"]
    sources.load_all(tmp_path, "2026-01-01", fetcher=ok, keys=["NFCI"])
    assert calls == ["NFCI"]  # 当天已抓取过，不重复请求

    def fail(key, root):
        raise RuntimeError("down")
    data, meta = sources.load_all(tmp_path, "2026-01-02", fetcher=fail, keys=["NFCI"])
    assert data["NFCI"] == [{"date": "2020-01-01", "value": 1.0}]
    assert meta["NFCI"]["ok"] is False and meta["NFCI"]["fetched_on"] == "2026-01-01"


# ---------- 变换与指数 ----------

def test_capex_total_requires_every_company():
    raw = {key: [{"date": "2025-01-01", "value": 1.0}, {"date": "2025-04-01", "value": 2.0}] for key, _ in catalog.CAPEX_COMPANIES}
    raw["CAPEX_META"] = raw["CAPEX_META"][:1]
    assert series.capex_total(raw) == [{"date": "2025-01-01", "value": 4.0}]


def test_yoy_skips_periods_without_a_year_ago_value():
    rows = [{"date": "2024-01-01", "value": 100.0}, {"date": "2025-01-01", "value": 110.0}, {"date": "2025-02-01", "value": 1.0}]
    assert series.yoy(rows, "monthly") == [{"date": "2025-01-01", "value": 10.0}]


def test_as_of_respects_publication_lag_and_staleness():
    ind = {"freq": "monthly", "transform": "level", "lag_days": 10}
    rows = [{"date": "2025-01-01", "value": 1.0}]  # 1 月观测，2 月 10 日公布
    months = [(2025, 1), (2025, 2), (2025, 3), (2025, 4), (2025, 6)]
    assert series.as_of_monthly(rows, ind, months) == [None, 1.0, 1.0, None, None]


def test_expanding_z_has_no_lookahead():
    rng = random.Random(3)
    values = [rng.gauss(0, 1) for _ in range(80)]
    full = series.expanding_z(values)
    cut = series.expanding_z(values[:60])
    assert full[:60] == cut
    assert all(v is None for v in full[: series.MIN_Z_MONTHS - 1])


def test_index_averages_available_components_without_filling():
    today = date(2010, 12, 31)
    months = series.months_between(series.START_MONTH, today)
    rng = random.Random(1)
    nfci = [{"date": f"{y}-{m:02d}-28", "value": rng.gauss(0, 1)} for y, m in months]
    out = series.build_indices({"s_nfci": nfci}, today)
    s = out["indices"]["S"]
    present = [c for c in s["coverage"] if c]
    members = len(s["members"])
    assert present and all(c == round(1 / members, 2) for c in present)  # 只有一个成分有数据
    assert all(v is None for v in out["indices"]["D"]["values"])          # 没有数据的指数不输出读数


# ---------- 预测 ----------

def ar1(n, b, seed=1, sd=1.0):
    rng = random.Random(seed)
    y, out = 0.0, []
    for _ in range(n):
        y = b * y + rng.gauss(0, sd)
        out.append(y)
    return out


def test_walk_forward_has_no_lookahead():
    values = ar1(300, 0.5)
    full, _ = forecast.walk_forward(values, 3)
    _, last = forecast.walk_forward(values[:200], 3)
    same = next(f for f in full if f["t"] == 199)
    assert last["t"] == 199 and "realized" not in last
    assert last["model"] == same["model"] and last.get("model_q") == same.get("model_q")


def test_gate_keeps_baseline_for_random_walk():
    values = [0.0]
    rng = random.Random(5)
    for _ in range(600):
        values.append(values[-1] + rng.gauss(0, 1))
    items, _ = forecast.walk_forward(values, 4)
    used, status = forecast.choose(forecast.score(items, 4))
    assert (used, status) == ("baseline", "baseline")


def test_gate_accepts_model_for_strong_mean_reversion():
    values = ar1(600, 0.2)
    items, _ = forecast.walk_forward(values, 1)
    stats = forecast.score(items, 1)
    assert forecast.choose(stats) == ("model", "model")
    assert 0.7 <= stats["coverage_model"] <= 0.9


def test_gate_marks_short_samples_insufficient():
    items, _ = forecast.walk_forward(ar1(50, 0.2), 1)
    assert forecast.choose(forecast.score(items, 1)) == ("baseline", "insufficient")


def test_event_baseline_is_conditional_on_current_level():
    """基准概率来自不变预测 + 误差分布，而不是无条件发生率。"""
    values = ar1(400, 0.95, sd=0.2)
    values[-1] = 3.0  # 远高于阈值：不变预测 + 小误差 → 几乎必然仍在阈值之上
    _, last = forecast.walk_forward(values, 4, event=0.0)
    assert 0.3 < last["p_rate"] < 0.7
    assert last["p_baseline"] > 0.95


def test_contiguous_tail_starts_after_last_gap():
    rows = [{"date": d, "value": 1.0} for d in ("2020-01-01", "2020-04-01", "2020-10-01", "2021-01-01")]
    tail = forecast.contiguous_tail(rows, build.step_ok("quarterly"))
    assert [r["date"] for r in tail] == ["2020-10-01", "2021-01-01"]


# ---------- 登记与结算 ----------

def test_ledger_appends_once_and_resolves_once(tmp_path):
    fc = [{"id": "s_nfci", "horizons": [{"h": 1, "origin": "2026-01-02", "target": "2026-01-09", "source": "baseline",
                                         "status": "baseline", "point": 0.1, "baseline": 0.1, "q": [0.0, 0.2]}]}]
    build.update_ledger(tmp_path, "2026-01-03", fc, {"s_nfci": []})
    build.update_ledger(tmp_path, "2026-01-04", fc, {"s_nfci": []})
    log = (tmp_path / "forecast_log.jsonl").read_text(encoding="utf-8")
    assert len(log.splitlines()) == 1
    logged, res = build.update_ledger(tmp_path, "2026-01-10", fc, {"s_nfci": [{"date": "2026-01-09", "value": 0.5}]})
    logged, res = build.update_ledger(tmp_path, "2026-01-11", fc, {"s_nfci": [{"date": "2026-01-09", "value": 9.9}]})
    assert (tmp_path / "forecast_log.jsonl").read_text(encoding="utf-8") == log  # 只追加，不改写
    assert len(res) == 1 and res[0]["actual"] == 0.5 and res[0]["covered"] is False  # 按首次看到的值结算
    live = build.live_record(logged, res)
    assert live["s_nfci"]["n"] == 1 and live["s_nfci"]["mae"] == 0.4


# ---------- 整体构建（离线合成数据） ----------

def synthetic_fetcher(key, root):
    rng = random.Random(sum(map(ord, key)))  # 不用 hash()：字符串哈希每个进程随机
    spec = catalog.RAW[key]
    if key == "EPOCH":
        return [{"date": f"{y}-06-01", "flop": 10 ** (18 + (y - 2010) * 0.6), "model": f"M{y}", "organization": "Lab"}
                for y in range(2010, 2027)]
    if key.startswith("CAPEX"):
        return [{"date": f"{y}-{m:02d}-01", "value": 1e9 * (1.1 ** (y - 2010))} for y in range(2010, 2027) for m in (1, 4, 7, 10)
                if (y, m) <= (2026, 7)]
    if key in ("NFCI", "STLFSI4"):
        out, v, d = [], 0.0, date(1995, 1, 6)
        while d <= date(2026, 11, 13):
            v = 0.97 * v + rng.gauss(0, 0.1)
            out.append({"date": d.isoformat(), "value": v})
            d = date.fromordinal(d.toordinal() + 7)
        return out
    if key in ("SOX", "VIX", "HY", "SOFTDEV_POSTINGS"):
        out, p = [], 100.0
        for i in range(4000):
            d = date.fromordinal(date(2011, 1, 3).toordinal() + i)
            if d.weekday() < 5:
                p *= math.exp(rng.gauss(0.0003, 0.01))
                out.append({"date": d.isoformat(), "value": p})
        return out
    if key == "GDP" or key in ("INFO_EQUIP", "SOFTWARE"):
        return [{"date": f"{y}-{m:02d}-01", "value": 100 * 1.01 ** ((y - 1990) * 4 + m)} for y in range(1990, 2027) for m in (1, 4, 7, 10)
                if (y, m) <= (2026, 7)]
    return [{"date": f"{y}-{m:02d}-01", "value": 100 * (1 + 0.002 * ((y - 1990) * 12 + m)) + rng.gauss(0, 0.5)}
            for y in range(1990, 2027) for m in range(1, 13) if (y, m) <= (2026, 10)]


def test_run_writes_versioned_files_and_summary(tmp_path):
    page = build.run(tmp_path, "2026-11-22", fetcher=synthetic_fetcher)
    out = tmp_path / "static" / "data" / "revolution" / "v1"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == 1 and set(manifest["files"]) == {"indices", "series", "forecasts", "events"}
    for name, info in manifest["files"].items():
        assert (out / info["path"]).stat().st_size == info["bytes"]
    assert [c["key"] for c in page["cards"]] == ["D", "B", "S", "C"]
    assert all(c["value"] is not None for c in page["cards"])
    assert {row["kind"] for row in page["sources"]} <= set(catalog.KIND_LABEL)
    assert all(row["freq_label"]["zh"] for row in page["sources"])
    assert page["forecasts"] and all(f["status"] in ("model", "baseline", "insufficient") for f in page["forecasts"])
    assert (tmp_path / "data" / "radar" / "revolution.json").exists()


def test_failed_sources_are_reported_not_filled(tmp_path):
    def partial(key, root):
        if key in ("NFCI", "STLFSI4", "SOX"):
            raise RuntimeError("down")
        return synthetic_fetcher(key, root)
    page = build.run(tmp_path, "2026-11-22", fetcher=partial)
    card = {c["key"]: c for c in page["cards"]}
    assert card["S"]["value"] is None and card["S"]["coverage"] == 0
    rows = {row["id"]: row for row in page["sources"]}
    assert rows["s_nfci"]["fetch_ok"] is False and rows["s_nfci"]["count"] == 0
    indices = json.loads((tmp_path / "static" / "data" / "revolution" / "v1" / "indices.json").read_text(encoding="utf-8"))
    assert all(v is None for v in indices["indices"]["S"]["values"])


def test_derived_forecast_holds_unforecast_components():
    """没有预测的成分保持当前 z：成分全是不变预测时，衍生读数等于当前读数，不会因构成变化凭空跳动。"""
    levels = [float(i % 7) for i in range(60)]
    state = series.z_state(levels)
    current = (levels[-1] - state[0]) / state[1]
    idx = {"components": {"s_nfci": [current], "s_stlfsi": [current], "s_sox_heat": [2.0]},
           "levels": {"s_nfci": levels, "s_stlfsi": levels, "s_sox_heat": levels}}
    fc = {i: {"horizons": [{"h": 4, "point": levels[-1]}, {"h": 13, "point": levels[-1]}]} for i in ("s_nfci", "s_stlfsi")}
    out = build.derived_index_forecast(fc, idx)["S"]
    expected = round(50 + 10 * (2 * current + 2.0) / 3, 2)
    assert [item["value"] for item in out] == [expected, expected]
    assert all(item["coverage"] == round(2 / 3, 2) for item in out)


# ---------- 页面（需要 hugo） ----------

import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUGO = shutil.which("hugo")
needs_hugo = pytest.mark.skipif(HUGO is None or not (ROOT / "themes" / "PaperMod" / "layouts").exists(), reason="需要 hugo 与 PaperMod 主题")


@needs_hugo
def test_page_builds_bilingual_and_navigation_is_unchanged(tmp_path):
    out = tmp_path / "public"
    subprocess.run([HUGO, "--quiet", "--destination", str(out), "--baseURL", "https://example.com/news_auto/"],
                   cwd=ROOT, check=True, capture_output=True)
    for lang_dir, title in (("", "AI 工业革命观测台"), ("en/", "AI Industrial Revolution Observatory")):
        page = (out / lang_dir / "revolution" / "index.html").read_text(encoding="utf-8")
        assert title in page and "revolution-config" in page
        assert "echarts-5.6.0.min" in page                         # 图表库只在本页加载
        home = (out / lang_dir / "index.html").read_text(encoding="utf-8")
        assert "revolution/" in home                                # 首页有入口
        assert "echarts" not in home
        nav = re.search(r'<ul id="?menu"?[^>]*>(.*?)</ul>', home, re.S)
        assert nav and "revolution" not in nav.group(1)             # 不进主导航
