from pathlib import Path

from trends.pipeline import run


def test_pipeline_writes_snapshot_periods_and_frontend_payload(tmp_path):
    sections = {
        "ai": {"items": [{"title": "GPU data center funding", "source": "TechCrunch AI", "link": "https://example.com/a", "score": 8}]},
        "market": {"items": [], "quotes": [{"name": "上证指数", "price": 100, "change_pct": 1}], "calendar": []},
    }
    result = run("2026-08-09", sections, tmp_path / "data", tmp_path / "static")
    assert result["snapshot"]["schema_version"] == 1
    assert (tmp_path / "data/daily/2026-08-09.json").exists()
    assert (tmp_path / "data/weekly/2026-08-09.json").exists()
    assert (tmp_path / "static/latest.json").exists()


def test_pipeline_keeps_insufficient_periods_honest(tmp_path):
    run("2026-08-09", {"ai": {"items": []}, "market": {"quotes": [], "calendar": None}}, tmp_path / "data", tmp_path / "static")
    import json
    value = json.loads((tmp_path / "static/latest.json").read_text(encoding="utf-8"))
    assert value["periods"]["week"]["data_quality"]["status"] == "partial"
    assert all(item["direction"] == "insufficient_data" for item in value["forecasts"])
