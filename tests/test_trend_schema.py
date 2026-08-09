import pytest

from trends.schema import SchemaError, validate_daily, validate_forecast, validate_period


def daily():
    return {
        "schema_version": 1,
        "date": "2026-08-09",
        "generated_at": "2026-08-09T00:00:00+00:00",
        "pipeline_version": "trend-v1",
        "coverage": {"overall_ratio": 1},
        "news_signals": [],
        "market_quotes": [],
        "macro_events": [],
        "data_warnings": [],
    }


def test_daily_schema_accepts_minimum_snapshot():
    assert validate_daily(daily())["date"] == "2026-08-09"


def test_daily_schema_rejects_invalid_coverage():
    value = daily()
    value["coverage"]["overall_ratio"] = 2
    with pytest.raises(SchemaError):
        validate_daily(value)


def test_period_schema_requires_known_period():
    value = {"period": "day", "start_date": "2026-08-09", "end_date": "2026-08-09", "data_quality": {"ratio": 1}}
    with pytest.raises(SchemaError):
        validate_period(value)


def test_forecast_schema_rejects_unknown_direction():
    value = {"forecast_id": "x", "created_at": "now", "target": "x", "horizon": "week", "direction": "buy", "confidence": "low", "model_version": "v1"}
    with pytest.raises(SchemaError):
        validate_forecast(value)
