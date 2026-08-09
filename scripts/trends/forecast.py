"""可解释的第一版趋势预测和到期评估。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def generate_forecasts(period: dict, created_at: str | None = None) -> list[dict]:
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    quality = period.get("data_quality", {})
    if quality.get("status") == "unavailable" or quality.get("ratio", 0) < 0.6:
        return [_forecast(period, created_at, "insufficient_data", "low", "数据不足")]
    topic_momentum = [value.get("momentum") for value in period.get("topics", {}).values() if value.get("momentum") is not None]
    topic_signal = sum(topic_momentum) / len(topic_momentum) if topic_momentum else 0
    market_signal = period.get("market", {}).get("latest_momentum")
    market_signal = market_signal if market_signal is not None else 0
    direction = _direction(topic_signal + market_signal)
    confidence = "high" if quality.get("ratio", 0) >= 0.9 else "medium"
    drivers = _drivers(period)
    invalidation = ["数据覆盖率低于最低阈值", "主要驱动主题在下一周期明显降温"]
    return [_forecast(period, created_at, direction, confidence, "规则模型", drivers, invalidation)]


def _forecast(period, created_at, direction, confidence, reason, drivers=None, invalidation=None):
    end_date = date.fromisoformat(period["end_date"])
    horizon_days = {"week": 7, "month": 30, "quarter": 91, "year": 365}.get(period["period"], 7)
    return {
        "forecast_id": f"trend-{period['period']}-{period['end_date']}",
        "created_at": created_at,
        "target": "combined_trend",
        "horizon": period["period"],
        "direction": direction,
        "confidence": confidence,
        "reason": reason,
        "scenarios": _scenarios(direction),
        "drivers": drivers or [],
        "invalidation_conditions": invalidation or [],
        "model_version": "rules-v1",
        "data_snapshot": period["end_date"],
        "target_date": (end_date + timedelta(days=horizon_days)).isoformat(),
        "status": "open",
        "realized_result": None,
    }


def _direction(value):
    if value > 0.01:
        return "positive"
    if value < -0.01:
        return "negative"
    return "neutral"


def _scenarios(direction):
    if direction == "positive":
        return [{"name": "基准", "direction": "positive", "description": "主题动量与市场信号维持当前方向。"}, {"name": "上行", "direction": "positive", "description": "多源事件持续确认，风险偏好继续改善。"}, {"name": "下行", "direction": "negative", "description": "热点退潮或宏观风险重新抬升。"}]
    if direction == "negative":
        return [{"name": "基准", "direction": "negative", "description": "风险信号延续，市场偏向防御。"}, {"name": "上行", "direction": "positive", "description": "流动性改善并出现新的产业催化。"}, {"name": "下行", "direction": "negative", "description": "波动率和负面事件同时上升。"}]
    return [{"name": "基准", "direction": "neutral", "description": "多空信号接近，趋势暂未确认。"}, {"name": "上行", "direction": "positive", "description": "主题动量重新加速。"}, {"name": "下行", "direction": "negative", "description": "风险事件增加且市场广度收缩。"}]


def _drivers(period):
    topics = sorted(period.get("topics", {}).items(), key=lambda entry: abs(entry[1].get("momentum") or 0), reverse=True)
    return [{"topic": key, "name": value.get("name"), "momentum": value.get("momentum")} for key, value in topics[:3]]


def evaluate_forecast(forecast: dict, period: dict | None) -> dict:
    result = dict(forecast)
    if not period:
        result["status"] = "unresolved"
        return result
    actual = period.get("market", {}).get("latest_momentum")
    if actual is None:
        result["status"] = "unresolved"
        return result
    observed = _direction(actual)
    result["realized_result"] = {"direction": observed, "value": actual, "evaluated_at": period.get("end_date")}
    result["status"] = "correct" if observed == forecast.get("direction") else "incorrect"
    return result
