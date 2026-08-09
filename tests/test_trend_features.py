from trends.features import compute_daily_features, news_contribution


def test_news_contribution_increases_with_confirmation_but_is_capped():
    base = {"importance": 8, "novelty": 1, "source_quality": 1, "corroborating_sources": 1}
    confirmed = {**base, "corroborating_sources": 4}
    assert news_contribution(confirmed) > news_contribution(base)
    assert news_contribution(confirmed) <= 1


def test_daily_features_are_null_safe():
    result = compute_daily_features([], [], [])
    assert result["topic_metrics"]
    assert result["market_metrics"]["breadth"] is None
