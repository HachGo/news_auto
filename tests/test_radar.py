import json
from datetime import date, timedelta
from statistics import mean, pstdev

import pytest

from brief import rising
from radar import build_forecasts, build_trends, write_radar


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _daily(folder, activities, changes=None):
    rows = []
    for i, activity in enumerate(activities):
        day = (date(2026, 9, 1) + timedelta(days=i)).isoformat()
        row = {"date": day, "topic_metrics": {"chips_compute": {"activity": activity, "event_count": 2, "source_count": 3}},
               "market_quotes": [{"name": "恒生科技", "change_pct": (changes or [0] * len(activities))[i], "price": 100 + i}]}
        _write(folder / "daily" / f"{day}.json", row)
        rows.append(row)
    return rows


def _entry(payload, key="chips_compute"):
    return next(entry for entry in payload["entries"] if entry["id"] == key)


def test_topic_z_matches_brief_and_stats(tmp_path):
    rows = _daily(tmp_path, [1] * 30 + [3])
    entry = _entry(build_trends(tmp_path, rows[-1]["date"]))
    assert entry["z"] == next(item["z"] for item in rising(rows) if item["id"] == entry["id"])
    assert entry["rising"] is True
    assert entry["stats"] == [{"k": "heat", "v": "3.00"}, {"k": "mean", "v": "1.00"},
                              {"k": "change_7d", "v": "+29%"}, {"k": "mentions", "v": "2 · 3"}]


def test_chart_negative_values_and_missing_market(tmp_path):
    changes = [-1, 1] * 15 + [-2]
    rows = _daily(tmp_path, [1] * 31, changes)
    rows[29]["market_quotes"] = []
    _write(tmp_path / "daily" / f'{rows[29]["date"]}.json', rows[29])
    chart = _entry(build_trends(tmp_path, rows[-1]["date"]), "quote-恒生科技")["chart"]
    history = changes[:29]
    spread = max(pstdev(history), abs(mean(history)) * .25, .25)
    lo, hi = -2, max(1, mean(history) + spread)
    position = lambda value: (value - lo) / (hi - lo) * 100
    assert chart["zero"] == pytest.approx(position(0))
    assert chart["band"]["b"] == pytest.approx(position(mean(history) - spread))
    assert chart["band"]["h"] == pytest.approx(2 * spread / (hi - lo) * 100)
    assert chart["bars"][-1]["b"] == 0
    assert chart["bars"][-1]["h"] == pytest.approx(position(0))
    assert chart["bars"][-2]["h"] == 0
    assert len(chart["bars"]) == 30
    assert chart["dates"] == [rows[1]["date"], rows[16]["date"], rows[-1]["date"]]
    assert not any(bar["recent"] for bar in chart["bars"])


def test_zero_earlier_sum_and_insufficient_rows(tmp_path):
    rows = _daily(tmp_path, [0] * 7 + [1] * 7)
    assert _entry(build_trends(tmp_path, rows[-1]["date"]))["stats"][2]["v"] == "—"
    assert build_trends(tmp_path, rows[6]["date"])["entries"] == []


def test_related_dedupe_sort_limit_and_forecast_links(tmp_path):
    rows = _daily(tmp_path, [1] * 8)
    for i, row in enumerate(rows[-7:]):
        row["news_signals"] = [{"id": str(i), "topics": ["chips_compute"], "title": f"新闻{i}",
                                "title_en": f"News {i}", "link": f"https://example.com/{i}", "source": "S", "importance": i}]
        _write(tmp_path / "daily" / f'{row["date"]}.json', row)
    rows[-1]["news_signals"].append({**rows[-1]["news_signals"][0], "id": "0", "importance": 10})
    _write(tmp_path / "daily" / f'{rows[-1]["date"]}.json', rows[-1])
    _write(tmp_path / "forecasts" / "2026-09-08.json", {"forecasts": [
        {"horizon": "month", "drivers": [{"topic": "chips_compute"}]},
        {"horizon": "week", "drivers": [{"topic": "chips_compute"}]}]})
    entry = _entry(build_trends(tmp_path, "2026-09-08"))
    assert len(entry["related"]) == 5
    assert [item["title"]["en"] for item in entry["related"]] == ["News 6", "News 6", "News 5", "News 4", "News 3"]
    assert entry["forecasts"] == ["week", "month"]
    assert _entry(build_trends(tmp_path, "2026-09-08"), "quote-恒生科技")["related"] == []


def _forecast(horizon="week", **extra):
    return {"forecast_id": "f", "horizon": horizon, "direction": "negative", "confidence": "high",
            "data_snapshot": "2026-09-01", "target_date": "2026-09-08", **extra}


def test_forecast_mapping_order_and_empty_record(tmp_path):
    _write(tmp_path / "forecasts" / "2026-09-01.json", {"forecasts": [
        _forecast("year"), _forecast("month"), _forecast("week", reason="数据不足",
        drivers=[{"topic": "chips_compute", "name": "芯片与算力", "momentum": .3}],
        invalidation_conditions=["数据覆盖率低于最低阈值", "主要驱动主题在下一周期明显降温"]), _forecast("quarter")]})
    _write(tmp_path / "forecasts" / "2026-10-01.json", {"forecasts": []})
    result = build_forecasts(tmp_path, "2026-09-03")
    assert [item["horizon"] for item in result["open"]] == ["week", "month", "quarter", "year"]
    first = result["open"][0]
    assert first["created"] == "2026-09-01" and first["days_left"] == 5
    assert first["drivers"][0]["name"]["en"] == "Chips & compute"
    assert first["reason"]["en"] == "Insufficient data"
    assert all(item["en"] != item["zh"] for item in first["invalidation"])
    assert result["record"] == {"resolved": 0, "correct": 0, "rate": None, "open": 4, "by_horizon": []}
    assert all(item["rate"] is None for item in result["calibration"])


def test_resolved_dedupe_sort_and_all_record_math(tmp_path):
    entries = [_forecast("week" if i < 40 else "month", forecast_id=f"f{i}", target_date=f"2026-09-{i % 28 + 1:02d}",
                         confidence="high" if i < 40 else "medium", status="correct" if i % 2 else "incorrect",
                         realized_result={"direction": "negative" if i % 2 else "positive"}) for i in range(60)]
    _write(tmp_path / "evaluations" / "2026-09-01.json", {"evaluations": entries})
    _write(tmp_path / "evaluations" / "2026-09-02.json", {"evaluations": [entries[0], _forecast(status="unresolved")]})
    result = build_forecasts(tmp_path, "2026-09-30")
    assert len(result["resolved"]) == 50
    assert len({entry["id"] for entry in result["resolved"]}) == 50
    assert [entry["target_date"] for entry in result["resolved"]] == sorted([entry["target_date"] for entry in result["resolved"]], reverse=True)
    assert result["record"] == {"resolved": 60, "correct": 30, "rate": 50, "open": 0,
        "by_horizon": [{"horizon": "week", "resolved": 40, "correct": 20, "rate": 50},
                       {"horizon": "month", "resolved": 20, "correct": 10, "rate": 50}]}
    assert result["calibration"] == [{"confidence": "low", "n": 0, "correct": 0, "rate": None},
                                    {"confidence": "medium", "n": 20, "correct": 10, "rate": 50},
                                    {"confidence": "high", "n": 40, "correct": 20, "rate": 50}]


def test_writer_skips_unchanged_files(tmp_path):
    out = tmp_path / "radar"
    assert write_radar(tmp_path, "2026-09-30", out) == {"trends": True, "forecasts": True}
    before = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in out.glob("*.json")}
    assert write_radar(tmp_path, "2026-09-30", out) == {"trends": False, "forecasts": False}
    assert before == {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in out.glob("*.json")}


def test_related_equal_importance_uses_newest_date(tmp_path):
    rows = _daily(tmp_path, [1] * 8)
    for i, row in enumerate(rows[-2:]):
        row["news_signals"] = [{"id": f"tie-{i}", "topics": ["chips_compute"],
                                "title": f"Tie {i}", "importance": 5,
                                "link": f"https://example.com/tie-{i}"}]
        _write(tmp_path / "daily" / f'{row["date"]}.json', row)
    related = _entry(build_trends(tmp_path, rows[-1]["date"]))["related"]
    assert [item["date"] for item in related] == [rows[-1]["date"], rows[-2]["date"]]
    assert related[0]["title"] == {"zh": "Tie 1", "en": "Tie 1"}
