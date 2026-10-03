import json
from datetime import date, timedelta

from trends import market_forecast as mf

START = date(2026, 9, 1)


def rows_for(changes, name="纳斯达克", start=START, repeat_on=()):
    """按日生成快照；repeat_on 中的日期重复前一日点位（模拟休市）。"""
    rows, price, previous = [], 100.0, None
    for offset, change in enumerate(changes):
        day = (start + timedelta(days=offset)).isoformat()
        if offset in repeat_on and previous:
            quote = dict(previous)
        else:
            price *= 1 + change / 100
            quote = {"name": name, "symbol": "IXIC", "price": round(price, 4), "change_pct": change, "is_stale": False}
        rows.append({"date": day, "market_quotes": [quote]})
        previous = quote
    return rows


def test_probability_is_normal_approximation_and_clamped():
    assert mf.probability([1.0] * 10 + [1.0001], 5)[0] == 95
    assert mf.probability([0.0] * 20, 5)[0] == 50
    p, sigma, drift = mf.probability([1, -1] * 10, 5)
    assert p == 50 and sigma == 1.0 and drift == 0.0


def test_holiday_repeats_and_stale_quotes_are_not_trading_days():
    rows = rows_for([1, 2, 3, 4], repeat_on={2})
    rows[3]["market_quotes"][0]["is_stale"] = True
    assert [day for day, _ in mf.observations(rows, "纳斯达克")] == ["2026-09-01", "2026-09-02"]


def test_questions_need_twenty_trading_days_and_skip_open_pairs():
    assert mf.create_questions(rows_for([0.5, -0.4] * 9 + [0.5]), "2026-09-19", set()) == []
    rows = rows_for([0.5, -0.4] * 10)
    created = mf.create_questions(rows, "2026-09-20", {("纳斯达克", "week")})
    assert [q["horizon"] for q in created] == ["month"]
    question = created[0]
    assert question["deadline"] == "2026-10-20" and 5 <= question["p"] <= 95
    assert question["baseline"] == round(100 * 11 / 22)
    assert "Nasdaq" in question["question"]["en"] and "纳斯达克" in question["question"]["zh"]


def question(created="2026-09-01", deadline="2026-09-03", p=70, baseline=50):
    return {"id": "q1", "quote": "纳斯达克", "horizon": "week", "created": created, "deadline": deadline, "p": p, "baseline": baseline}


def test_resolution_compounds_daily_changes_up_to_first_trading_day_after_deadline():
    rows = rows_for([0, 2, -1, 0.5], repeat_on={2})  # 09-03 休市重复，09-04 才是截止后首个交易日
    result = mf.resolve(question(), rows, "2026-09-04")
    assert result["resolved_on"] == "2026-09-04" and result["outcome"] == 1
    assert result["change_pct"] == round((1.02 * 1.005 - 1) * 100, 2)
    assert result["brier"] == round((0.7 - 1) ** 2, 4) and result["baseline_brier"] == 0.25


def test_resolution_waits_then_voids_without_data():
    rows = rows_for([0, 1])
    assert mf.resolve(question(deadline="2026-09-05"), rows, "2026-09-04") is None
    assert mf.resolve(question(deadline="2026-09-05"), rows, "2026-09-10") is None
    assert mf.resolve(question(deadline="2026-09-05"), rows, "2026-09-13")["status"] == "void"


def test_run_appends_and_never_rewrites_questions(tmp_path):
    rows = rows_for([0.5, -0.4] * 10)
    first = mf.run(tmp_path, "2026-09-20", rows=rows)
    assert len(first["created"]) == 2
    path = tmp_path / "market_questions" / "2026-09-20.json"
    before = path.read_bytes()
    assert mf.run(tmp_path, "2026-09-20", rows=rows)["created"] == []
    assert path.read_bytes() == before
    later = rows_for([0.5, -0.4] * 10 + [1.0] * 8)
    outcome = mf.run(tmp_path, "2026-09-28", rows=later)
    assert [r["id"] for r in outcome["resolved"]] == [q["id"] for q in first["created"] if q["horizon"] == "week"]
    assert mf.run(tmp_path, "2026-09-28", rows=later)["resolved"] == []
    stored = json.loads((tmp_path / "market_resolutions" / "2026-09-28.json").read_text())
    assert len(stored["resolutions"]) == 1


def test_summary_scores_brier_and_bins(tmp_path):
    (tmp_path / "market_questions").mkdir()
    (tmp_path / "market_resolutions").mkdir()
    qs = [{**question(), "id": f"q{i}", "p": p, "baseline": 50, "question": {}, "rationale": {}} for i, p in enumerate((10, 90, 55))]
    (tmp_path / "market_questions" / "2026-09-01.json").write_text(json.dumps({"questions": qs}))
    res = [{"id": "q0", "status": "resolved", "resolved_on": "2026-09-04", "change_pct": -1, "outcome": 0, "brier": 0.01, "baseline_brier": 0.25},
           {"id": "q1", "status": "resolved", "resolved_on": "2026-09-04", "change_pct": 1, "outcome": 1, "brier": 0.01, "baseline_brier": 0.25}]
    (tmp_path / "market_resolutions" / "2026-09-04.json").write_text(json.dumps({"resolutions": res}))
    summary = mf.summary(tmp_path, "2026-09-05")
    assert summary["record"] == {"resolved": 2, "open": 1, "void": 0, "brier": 0.01, "baseline_brier": 0.25}
    bins = {b["label"]: b for b in summary["calibration"]}
    assert bins["0–20"] == {"label": "0–20", "n": 1, "predicted": 10, "observed": 0}
    assert bins["80–100"]["observed"] == 100
    assert summary["calibration_ready"] is False
