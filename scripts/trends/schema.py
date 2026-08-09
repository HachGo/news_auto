"""轻量级数据契约校验。

不引入 Pandas 或 Pydantic，保证 GitHub Actions 上的趋势模块依赖足够小。
"""

from __future__ import annotations

from datetime import date
from numbers import Real


class SchemaError(ValueError):
    """趋势快照不满足公开契约。"""


def _require(obj, key, path):
    if key not in obj:
        raise SchemaError(f"{path}.{key} is required")
    return obj[key]


def _string(value, path, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise SchemaError(f"{path} must be a non-empty string")


def _number(value, path, low=None, high=None):
    if not isinstance(value, Real) or isinstance(value, bool):
        raise SchemaError(f"{path} must be a number")
    if low is not None and value < low:
        raise SchemaError(f"{path} must be >= {low}")
    if high is not None and value > high:
        raise SchemaError(f"{path} must be <= {high}")


def _date(value, path):
    _string(value, path)
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise SchemaError(f"{path} must be an ISO date") from exc


def validate_daily(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict):
        raise SchemaError("snapshot must be an object")
    _require(snapshot, "schema_version", "snapshot")
    if snapshot["schema_version"] != 1:
        raise SchemaError("unsupported schema_version")
    _date(_require(snapshot, "date", "snapshot"), "snapshot.date")
    _string(_require(snapshot, "generated_at", "snapshot"), "snapshot.generated_at")
    _string(_require(snapshot, "pipeline_version", "snapshot"), "snapshot.pipeline_version")
    for key in ("news_signals", "market_quotes", "macro_events", "data_warnings"):
        if not isinstance(_require(snapshot, key, "snapshot"), list):
            raise SchemaError(f"snapshot.{key} must be an array")
    quality = _require(snapshot, "coverage", "snapshot")
    if not isinstance(quality, dict):
        raise SchemaError("snapshot.coverage must be an object")
    _number(_require(quality, "overall_ratio", "snapshot.coverage"), "snapshot.coverage.overall_ratio", 0, 1)
    for item in snapshot["news_signals"]:
        _validate_news(item)
    for item in snapshot["market_quotes"]:
        _validate_quote(item)
    return snapshot


def _validate_news(item):
    if not isinstance(item, dict):
        raise SchemaError("news_signals entries must be objects")
    for key in ("id", "title", "source", "published_at", "section"):
        _string(_require(item, key, "news_signals[]"), f"news_signals[].{key}")
    topics = _require(item, "topics", "news_signals[]")
    if not isinstance(topics, list):
        raise SchemaError("news_signals[].topics must be an array")
    if "importance" in item:
        _number(item["importance"], "news_signals[].importance", 0, 10)
    for key in ("sentiment", "novelty", "source_quality"):
        if key in item and item[key] is not None:
            _number(item[key], f"news_signals[].{key}", -1 if key == "sentiment" else 0, 1)


def _validate_quote(item):
    if not isinstance(item, dict):
        raise SchemaError("market_quotes entries must be objects")
    for key in ("symbol", "name", "market", "trading_date", "source"):
        _string(_require(item, key, "market_quotes[]"), f"market_quotes[].{key}")
    _date(item["trading_date"], "market_quotes[].trading_date")
    for key in ("price", "change_pct"):
        if item.get(key) is not None:
            _number(item[key], f"market_quotes[].{key}")


def validate_period(period: dict) -> dict:
    if not isinstance(period, dict):
        raise SchemaError("period must be an object")
    for key in ("period", "start_date", "end_date", "data_quality"):
        _require(period, key, "period")
    if period["period"] not in {"week", "month", "quarter", "year"}:
        raise SchemaError("period.period is invalid")
    _date(period["start_date"], "period.start_date")
    _date(period["end_date"], "period.end_date")
    quality = period["data_quality"]
    if not isinstance(quality, dict):
        raise SchemaError("period.data_quality must be an object")
    _number(quality.get("ratio", 0), "period.data_quality.ratio", 0, 1)
    return period


def validate_forecast(forecast: dict) -> dict:
    if not isinstance(forecast, dict):
        raise SchemaError("forecast must be an object")
    for key in ("forecast_id", "created_at", "target", "horizon", "direction", "confidence", "model_version"):
        _string(_require(forecast, key, "forecast"), f"forecast.{key}")
    if forecast["direction"] not in {"positive", "neutral", "negative", "insufficient_data"}:
        raise SchemaError("forecast.direction is invalid")
    if forecast["confidence"] not in {"low", "medium", "high"}:
        raise SchemaError("forecast.confidence is invalid")
    return forecast


def validate_all(snapshot: dict) -> dict:
    """兼容 pipeline 中的统一校验调用。"""
    return validate_daily(snapshot)
