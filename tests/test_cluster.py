from datetime import datetime, timezone

from brief import build_brief
from cluster import cluster_events, tokens


def item(title, link, **extra):
    return {"title": title, "link": link, "source": "RSS", "time": datetime(2026, 10, 3, tzinfo=timezone.utc), **extra}


def test_tokens_english_stop_words_and_cjk_bigrams():
    assert tokens("The NEW rocket is on a launch pad") == ["new", "rocket", "launch", "pad"]
    assert tokens("星舰发射") == ["星舰", "舰发", "发射"]


def test_bilingual_selected_attaches_english_and_chinese_reports():
    selected = item("SpaceX launches Starship rocket", "https://en/1", title_zh="SpaceX 星舰火箭成功发射")
    candidates = [item("星舰火箭成功发射", "https://zh/1"), item("SpaceX launches Starship rocket", "https://en/2")]
    event = cluster_events({"ai": [selected]}, {"world": candidates})[0]
    assert event["report_count"] == 3
    assert event["langs"] == {"en": 2, "zh": 1}
    assert event["reports"][0]["link"] == selected["link"]


def test_one_common_word_never_merges_unrelated_titles():
    selected = item("Apple reveals redesigned laptop computer", "https://a")
    unrelated = item("Apple orchard suffers drought damage", "https://b")
    assert cluster_events({"ai": [selected]}, {"world": [unrelated]})[0]["report_count"] == 1


def test_cross_section_merge_uses_higher_score_and_unions_fields():
    low = item("SpaceX launches Starship rocket", "https://a", score=7)
    high = item("SpaceX launches Starship rocket", "https://b", score=9)
    events = cluster_events({"ai": [low], "world": [high]}, {})
    assert len(events) == 1
    assert events[0]["link"] == high["link"]
    assert events[0]["field"] == "world"
    assert set(events[0]["fields"]) == {"ai_tech", "world"}


def test_reports_dedupe_links_and_sort_representative_then_newest():
    selected = item("SpaceX launches Starship rocket", "https://a")
    earlier = item(selected["title"], "https://b", time="2026-10-01T00:00:00+00:00")
    later = item(selected["title"], "https://c", time="2026-10-02T00:00:00+00:00")
    event = cluster_events({"ai": [selected]}, {"ai": [earlier, later, selected, later]})[0]
    assert [report["link"] for report in event["reports"]] == ["https://a", "https://c", "https://b"]


def test_same_day_reuse_preserves_merged_reports_and_fields():
    a = item("SpaceX launches Starship rocket", "https://a", score=7)
    b = item(a["title"], "https://b", score=9)
    first = build_brief({"ai": {"items": [a]}, "world": {"items": [b], "candidates": [item(a["title"], "https://c")]}}, "2026-10-03", "t")
    reused = {"ai": {"items": [{k: v for k, v in a.items() if k not in ("time", "score")}]},
              "world": {"items": [{k: v for k, v in b.items() if k not in ("time", "score")}]}}
    second = build_brief(reused, "2026-10-03", "t2", previous=first)
    assert second["events"] == first["events"]
    assert second["stats"] == first["stats"]
    assert first["schema"] == 2
    assert first["stats"]["fields"]["ai_tech"] == first["stats"]["fields"]["world"] == 1


def test_same_link_across_sections_keeps_both_fields():
    a = item("SpaceX launches Starship rocket", "https://same", score=7)
    b = item("Starship launch", "https://same", score=9)
    events = cluster_events({"ai": [a], "market": [b]}, {})
    assert len(events) == 1
    assert events[0]["fields"] == ["finance", "ai_tech"]
    assert events[0]["report_count"] == 1


def test_unrelated_and_explicitly_rejected_candidates_stay_private():
    selected = item("SpaceX launches Starship rocket", "https://a")
    candidates = [item(selected["title"], "https://rejected", score=1),
                  item("Election party diplomacy sanctions", "https://unrelated")]
    assert cluster_events({"ai": [selected]}, {"world": candidates})[0]["report_count"] == 1


def test_candidate_pool_does_not_mutate_inputs():
    selected = item("SpaceX launches Starship rocket", "https://a")
    candidate = item(selected["title"], "https://b")
    cluster_events({"ai": [selected]}, {"world": [candidate]})
    assert "reports" not in selected and "reports" not in candidate


def test_schema_one_brief_still_renders_in_hugo(tmp_path):
    import json
    import shutil
    import subprocess
    from pathlib import Path
    import pytest

    hugo = shutil.which("hugo") or ("/tmp/wr-tools/hugo" if Path("/tmp/wr-tools/hugo").exists() else None)
    if not hugo:
        pytest.skip("Hugo 未安装；构建验证另行执行")
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "layouts/_partials").mkdir(parents=True)
    for name in ("today_event.html", "brief_latest.html"):
        shutil.copy(root / "layouts/_partials" / name, tmp_path / "layouts/_partials" / name)
    (tmp_path / "layouts/_partials/page_any_lang.html").write_text('{{ return false }}')
    (tmp_path / "layouts/index.html").write_text(
        '<html><body>{{ $b := partial "brief_latest.html" . }}'
        '{{ range $b.events }}{{ partial "today_event.html" (dict "event" . "date" $b.date "lang" "en" "rank" 1) }}{{ end }}</body></html>')
    shutil.copytree(root / "i18n", tmp_path / "i18n")
    (tmp_path / "hugo.toml").write_text('baseURL = "https://example.org/"\ndefaultContentLanguage = "en"\ndisableKinds = ["taxonomy", "term", "RSS", "sitemap"]\n')
    (tmp_path / "data/brief").mkdir(parents=True)
    event = build_brief({"ai": {"items": [item("Rocket launches today", "https://a")] }}, "2026-10-03", "t")["events"][0]
    for key in ("reports", "fields", "report_count", "langs"):
        del event[key]
    (tmp_path / "data/brief/2026-10-03.json").write_text(json.dumps({"schema": 1, "date": "2026-10-03", "events": [event]}))
    output = subprocess.run([hugo, "--source", str(tmp_path), "--printI18nWarnings"], capture_output=True, text=True)
    assert output.returncode == 0, output.stderr
    assert "WARN" not in output.stdout + output.stderr
    rendered = (tmp_path / "public/index.html").read_text()
    assert 'data-fields="ai_tech"' in rendered
    assert "Rocket launches today" in rendered
    assert 'href="https://a"' in rendered


def test_source_suffix_and_summary_link_real_world_pair():
    # 2026-10-03 真实候选：仅比标题相似度 0.26，加入摘要并去掉来源后缀后应合并
    selected = item("G7 to release 100m barrels from reserves to combat surging diesel prices", "https://g",
                    summary_en="G7 nations agreed to release diesel stocks from strategic reserves as prices surge.")
    candidate = item("Oil prices lower as G7 nations to release diesel stocks - CNBC", "https://c",
                     summary="Oil fell after G7 nations agreed to release diesel stocks from reserves.")
    assert cluster_events({"world": [selected]}, {"market": [candidate]})[0]["report_count"] == 2


def test_shared_topic_word_with_different_story_stays_apart():
    selected = item("GPT-6.1 sol scores 100% in frontier math benchmark", "https://a",
                    summary_en="The model solved every problem in the frontier math benchmark.")
    other = item("PewDiePie is trying to distill GPT-Sol", "https://b",
                 summary="The YouTuber is training a small model on outputs from the new release.")
    assert cluster_events({"ai": [selected]}, {"ai": [other]})[0]["report_count"] == 1
