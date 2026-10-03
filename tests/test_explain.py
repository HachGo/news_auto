import json
from datetime import date, timedelta

from explain import attach_explanations
from radar import build_idea_trends, write_radar


class FakeClient:
    def __init__(self, reply):
        self.calls, self.prompts, self.reply = 0, [], reply
        self.chat = self.completions = self

    def create(self, messages, **_):
        self.calls += 1
        self.prompts.append(messages[0]["content"])
        message = type("M", (), {"content": json.dumps(self.reply)})
        return type("R", (), {"choices": [type("C", (), {"message": message})]})


def entry(id_, rising=True, related=True):
    return {"id": id_, "rising": rising, "name": {"zh": "芯片", "en": "Chips"},
            "related": [{"title": {"zh": "GPU 涨价", "en": "GPU prices jump"}}] if related else []}


def test_only_rising_entries_with_headlines_get_grounded_explanations(tmp_path):
    entries = [entry("chips"), entry("calm", rising=False), entry("bare", related=False)]
    client = FakeClient({"items": [{"id": "chips", "zh": "GPU 涨价报道增多。", "en": "More reports of GPU prices rising."},
                                   {"id": "invented", "zh": "x", "en": "x"}]})
    attach_explanations(entries, client, tmp_path / "why.json")
    assert entries[0]["why"]["en"] == "More reports of GPU prices rising."
    assert "why" not in entries[1] and "why" not in entries[2]
    assert "GPU prices jump" in client.prompts[0] and "calm" not in client.prompts[0]
    assert json.loads((tmp_path / "why.json").read_text()) == {"chips": entries[0]["why"]}


def test_cached_explanations_are_reused_without_calling_the_model(tmp_path):
    (tmp_path / "why.json").write_text(json.dumps({"chips": {"zh": "缓存", "en": "cached"}}))
    client = FakeClient({"items": []})
    entries = [entry("chips")]
    attach_explanations(entries, client, tmp_path / "why.json")
    assert client.calls == 0 and entries[0]["why"]["en"] == "cached"


def test_no_key_means_no_explanation(tmp_path):
    entries = [entry("chips")]
    attach_explanations(entries, None, tmp_path / "why.json")
    assert "why" not in entries[0] and not (tmp_path / "why.json").exists()


def write_idea_days(folder, counts, start=date(2026, 9, 20)):
    folder.mkdir(parents=True, exist_ok=True)
    for offset, count in enumerate(counts):
        day = (start + timedelta(days=offset)).isoformat()
        items = [{"id": f"show_hn:{day}-{i}", "source": "show_hn", "type": "hack", "url": f"https://x/{day}/{i}",
                  "title": {"zh": f"创意 {i}", "en": f"Idea {i}"}} for i in range(count)]
        (folder / f"{day}.json").write_text(json.dumps({"date": day, "items": items}))
    return (start + timedelta(days=len(counts) - 1)).isoformat()


def test_idea_categories_need_eight_days(tmp_path):
    last = write_idea_days(tmp_path / "ideas", [2] * 7)
    assert build_idea_trends(tmp_path / "ideas", last) == []


def test_idea_category_spike_is_rising_with_recent_ideas(tmp_path):
    last = write_idea_days(tmp_path / "ideas", [2, 3, 2, 2, 3, 2, 2, 3, 2, 9])
    [hack] = build_idea_trends(tmp_path / "ideas", last)
    assert hack["id"] == "idea-hack" and hack["kind"] == "idea" and hack["rising"]
    assert hack["stats"][0] == {"k": "ideas_today", "v": "9"}
    assert hack["related"][0]["date"] == last and len(hack["related"]) == 5
    assert hack["related"][0]["source"] == "Show HN"


def test_write_radar_merges_idea_entries_into_trends(tmp_path):
    last = write_idea_days(tmp_path / "ideas", [2, 3, 2, 2, 3, 2, 2, 3, 2, 9])
    write_radar(tmp_path / "trends", last, tmp_path / "radar", ideas_dir=tmp_path / "ideas")
    trends = json.loads((tmp_path / "radar" / "trends.json").read_text())
    assert [item["id"] for item in trends["entries"]] == ["idea-hack"]
