import json
from datetime import datetime, timedelta, timezone

from brief import build_brief, importance_dots, load_brief, rising, write_brief
from common import item_id

NOW = datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)


def _item(title, link, score=None, **extra):
    item = {"title": title, "link": link, "source": "S", "category": "AI 动态",
            "summary": "", "time": NOW}
    if score is not None:
        item["score"] = score
    item.update(extra)
    return item


def test_events_ranked_by_score_with_fields_and_bilingual_text():
    results = {
        "ai": {"items": [
            _item("Model launch", "https://a/1", 7, title_zh="模型发布", summary_zh="中文摘要",
                  summary_en="English summary."),
        ]},
        "world": {"items": [_item("Quake hits coast", "https://w/1", 9, title_zh="海岸地震")]},
        "market": {"items": [
            _item("央行降准", "https://m/1", title_zh="央行降准", importance=8,
                  title_en="Central bank cuts reserve ratio"),
        ]},
    }
    brief = build_brief(results, "2026-09-05", "2026-09-05T16:00:00+08:00")
    assert [event["field"] for event in brief["events"]] == ["world", "finance", "ai_tech"]
    world, market, ai = brief["events"]
    assert world["title"] == {"zh": "海岸地震", "en": "Quake hits coast"}
    assert world["lang"] == "en" and world["importance"] == 4
    # 中文来源：英文标题来自模型；分数取模型给的 importance
    assert market["title"]["en"] == "Central bank cuts reserve ratio"
    assert market["lang"] == "zh" and market["score"] == 8
    assert ai["summary"] == {"zh": "中文摘要", "en": "English summary."}
    assert ai["id"] == item_id({"link": "https://a/1"})
    assert brief["stats"]["fields"] == {"ai_tech": 1, "world": 1, "finance": 1}


def test_english_summary_never_falls_back_to_chinese_text():
    results = {"market": {"items": [_item("央行降准", "https://m/1", summary="中文 RSS 摘要")]}}
    event = build_brief(results, "2026-09-05", "t")["events"][0]
    assert event["summary"]["en"] == ""
    assert event["title"]["en"] == "央行降准"


def test_importance_dots_cover_full_range():
    assert [importance_dots(score) for score in (1, 3, 5, 7, 10)] == [1, 2, 2, 4, 5]


def test_reused_items_keep_previous_scores_and_english(tmp_path):
    fresh = {"ai": {"items": [_item("Model launch", "https://a/1", 9, title_zh="模型发布",
                                     summary_en="English summary.")]}}
    first = build_brief(fresh, "2026-09-05", "2026-09-05T08:00:00+08:00")
    path = tmp_path / "2026-09-05.json"
    assert write_brief(path, first) is True
    before = path.read_bytes()

    # 同日重跑复用日报：Markdown 回读的条目没有时间、分数和英文摘要
    reused = {"ai": {"items": [{"title": "Model launch", "title_zh": "模型发布",
                                "link": "https://a/1", "source": "S", "category": "AI 动态",
                                "summary": "中文摘要"}]}}
    second = build_brief(reused, "2026-09-05", "2026-09-05T09:00:00+08:00", previous=load_brief(path))
    assert second["events"][0]["score"] == 9
    assert second["events"][0]["summary"]["en"] == "English summary."
    assert write_brief(path, second, load_brief(path)) is False
    assert path.read_bytes() == before


def test_fresh_item_missing_english_is_restored_from_same_day_brief():
    previous = build_brief({"ai": {"items": [_item("Model launch", "https://a/1", 9,
                                                   summary_en="Old English.")]}}, "2026-09-05", "t")
    refreshed = {"ai": {"items": [_item("Model launch", "https://a/1", 8)]}}
    brief = build_brief(refreshed, "2026-09-05", "t2", previous=previous)
    assert brief["events"][0]["score"] == 8
    assert brief["events"][0]["summary"]["en"] == "Old English."


def _row(day, activity, change, price):
    return {
        "date": day,
        "topic_metrics": {"foundation_models": {"activity": activity}, "open_source": {"activity": 1.0}},
        "market_quotes": [{"name": "恒生科技", "change_pct": change, "price": price}],
    }


def test_rising_flags_spikes_against_baseline():
    rows = [_row(f"2026-08-{d:02d}", 1.0 + (d % 2) * 0.2, 0.1 * (-1) ** d, 4000 + d) for d in range(1, 21)]
    rows.append(_row("2026-08-21", 3.0, 3.2, 4200))
    signals = rising(rows)
    ids = [signal["id"] for signal in signals]
    assert ids[:2] == ["quote-恒生科技", "foundation_models"] or ids[:2] == ["foundation_models", "quote-恒生科技"]
    topic = next(signal for signal in signals if signal["id"] == "foundation_models")
    assert topic["z"] > 2 and topic["field"] == "ai_tech"
    assert topic["name"] == {"zh": "基础模型", "en": "Foundation models"}
    assert len(topic["bars"]) == 14 and max(topic["bars"]) == 100
    market = next(signal for signal in signals if signal["id"] == "quote-恒生科技")
    assert market["field"] == "finance" and market["name"]["en"] == "Hang Seng Tech"
    # 平稳话题不会出现在“上升中”
    assert "open_source" not in ids


def test_rising_needs_enough_history():
    rows = [_row(f"2026-08-0{d}", 1.0, 0.1, 4000) for d in range(1, 6)]
    assert rising(rows) == []


def test_forecasts_and_track_record_from_trend_dir(tmp_path):
    (tmp_path / "forecasts").mkdir()
    (tmp_path / "evaluations").mkdir()
    (tmp_path / "forecasts" / "2026-09-05.json").write_text(json.dumps({"forecasts": [{
        "horizon": "month", "direction": "positive", "confidence": "high", "target_date": "2026-10-05",
        "scenarios": [{"name": "基准", "direction": "positive", "description": "主题动量与市场信号维持当前方向。"}],
        "drivers": [{"topic": "chips_compute", "name": "芯片与算力"}],
    }]}), encoding="utf-8")
    (tmp_path / "evaluations" / "2026-09-05.json").write_text(json.dumps({"evaluations": [
        {"status": "correct"}, {"status": "incorrect"}, {"status": "unresolved"}, {"status": "correct"},
    ]}), encoding="utf-8")
    brief = build_brief({}, "2026-09-05", "t", trend_dir=tmp_path)
    forecast = brief["forecasts"][0]
    # 旧预测文件没有英文字段时按固定模板补齐
    assert forecast["scenarios"][0]["name"] == {"zh": "基准", "en": "Base case"}
    assert forecast["scenarios"][0]["description"]["en"].startswith("Topic momentum")
    assert forecast["drivers"] == [{"zh": "芯片与算力", "en": "Chips & compute"}]
    assert brief["track_record"] == {"resolved": 3, "correct": 2}
