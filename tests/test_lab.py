import json
from datetime import date, timedelta

import lab
from common import item_id


def test_ascii_aliases_use_word_boundaries_and_cjk_uses_substrings():
    assert lab.matches("SpaceX launches Starship", ["SpaceX"])
    assert not lab.matches("SpaceXAI releases Grok", ["SpaceX"])
    assert not lab.matches("Hybrid car sales rocket in Europe", ["rocket launch"])
    assert lab.matches("马斯克回应欧盟罚款", ["马斯克"])
    assert lab.matches("TSLA falls 6%", ["tsla"])


def write_post(root, section, day, items, en_titles=None):
    folder = root / "content" / section
    folder.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(
        f"### {i + 1}. {item['title_zh']} {{#{item_id(item)}}}\n\n摘要\n\n来源：[{item['source']}]({item['link']})"
        for i, item in enumerate(items))
    (folder / f"{day}.md").write_text(f'---\ntitle: "{section} {day}"\n---\n\n## 重点\n\n{body}\n', encoding="utf-8")
    if en_titles:
        en = "\n\n".join(f"### {i + 1}. {title} {{#{item_id(item)}}}\n\nSummary" for i, (item, title) in enumerate(zip(items, en_titles)))
        (folder / f"{day}.en.md").write_text(f'---\ntitle: "x"\n---\n\n{en}\n', encoding="utf-8")


def test_corpus_reads_archive_english_titles_and_merged_reports(tmp_path):
    item = {"title_zh": "SpaceX 星舰首次入轨", "source": "BBC", "link": "https://bbc.test/1"}
    write_post(tmp_path, "world", "2026-10-02", [item], en_titles=["SpaceX Starship reaches orbit"])
    write_post(tmp_path, "ai", "2026-10-02", [item])  # 同一链接在另一版面重复：只计一次
    (tmp_path / "data" / "brief").mkdir(parents=True)
    (tmp_path / "data" / "brief" / "2026-10-02.json").write_text(json.dumps({"events": [{"id": item_id(item), "reports": [
        {"link": "https://bbc.test/1", "title": "same"}, {"link": "https://cnbc.test/9", "title": "Starship makes orbit"}]}]}))
    items = lab.corpus(tmp_path, "2026-10-03", days=5)
    assert len(items) == 1
    only = items[0]
    assert only["title"] == {"zh": "SpaceX 星舰首次入轨", "en": "SpaceX Starship reaches orbit"}
    assert only["reports"] == 2 and "Starship makes orbit" in only["text"]


def story(day, title, source="S", field="ai_tech"):
    return {"date": day, "field": field, "link": f"https://x.test/{day}/{title}", "source": source, "lang": "en",
            "title": {"zh": title, "en": title}, "text": title, "reports": 1}


TRACKERS = [
    {"id": "musk", "type": "entities", "name": {"zh": "马斯克", "en": "Musk"}, "since": "2026-09-29",
     "entities": [{"id": "tesla", "name": {"zh": "特斯拉", "en": "Tesla"}, "aliases": ["Tesla"]},
                  {"id": "spacex", "name": {"zh": "SpaceX", "en": "SpaceX"}, "aliases": ["SpaceX"]},
                  {"id": "boring", "name": {"zh": "无聊公司", "en": "Boring"}, "aliases": ["Boring Company"]}]},
    {"id": "space", "type": "domain", "name": {"zh": "航天", "en": "Space"}, "since": "2026-10-01", "keywords": ["satellite"]},
]


def day(offset):
    return (date(2026, 10, 3) - timedelta(days=offset)).isoformat()


def test_entity_counts_week_change_and_backfill_flags():
    items = [story(day(1), "Tesla deliveries beat"), story(day(2), "Tesla robotaxi"), story(day(9), "Tesla recall"),
             story(day(3), "SpaceX and Tesla share engineers"), story(day(40), "Tesla old news")]
    out = lab.build_lab(TRACKERS, items, "2026-10-03")
    musk = out["trackers"][0]
    tesla = next(e for e in musk["entities"] if e["id"] == "tesla")
    assert (tesla["m7"], tesla["m30"], tesla["change"]) == (3, 4, 200)
    assert len(tesla["spark"]) == 30 and max(tesla["spark"]) == 100
    assert musk["stats"]["m7"] == 3 and musk["stats"]["m30"] == 4
    shared = next(t for t in musk["timeline"] if "SpaceX" in t["title"]["en"])
    assert [e["id"] for e in shared["entities"]] == ["tesla", "spacex"] and shared["backfilled"] is False
    assert any(t["backfilled"] for t in musk["timeline"])
    boring = next(e for e in musk["entities"] if e["id"] == "boring")
    assert boring["m30"] == 0 and boring["change"] is None and boring["latest"] is None


def test_domain_tracker_links_rising_trends_whose_headlines_match():
    trends = [{"id": "chips", "z": 2.5, "field": "ai_tech", "name": {"zh": "芯片", "en": "Chips"},
               "related": [{"title": {"zh": "卫星芯片", "en": "Chips for a satellite constellation"}}]},
              {"id": "calm", "z": -1, "field": "ai_tech", "name": {}, "related": [{"title": {"zh": "", "en": "satellite"}}]}]
    out = lab.build_lab(TRACKERS, [story(day(0), "Satellite broadband grows")], "2026-10-03", trends)
    space = out["trackers"][1]
    assert space["stats"]["m7"] == 1 and space["timeline"][0]["entities"] == []
    assert [r["id"] for r in space["rising"]] == ["chips"]


def test_empty_tracker_has_zero_counts_for_collecting_state():
    out = lab.build_lab(TRACKERS, [], "2026-10-03")
    assert out["trackers"][1]["stats"]["m30"] == 0 and out["trackers"][1]["timeline"] == []


def test_shipped_tracker_config_loads():
    trackers = lab.load_trackers(lab.Path(lab.__file__).with_name("trackers.yaml"))
    assert [t["id"] for t in trackers] == ["musk", "space"]
    assert all(entity["aliases"] for entity in trackers[0]["entities"])
