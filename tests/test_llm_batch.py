import json
from types import SimpleNamespace

import pytest

import common


class FakeClient:
    """按顺序返回预设回复的假 LLM 客户端，同时记录每次调用的 prompt。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        if not self.responses:
            raise RuntimeError("没有更多预设回复")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=item))])


def _batch(*pairs):
    return json.dumps({"items": [{"index": i, "title_zh": t, "summary_zh": s} for i, t, s in pairs]})


def _items(count):
    return [{"title": f"T{i}", "summary": f"S{i}", "link": f"l{i}", "source": "src"} for i in range(count)]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(common.time, "sleep", lambda *_: None)


def test_batch_request_handles_several_items_per_call():
    client = FakeClient([_batch((0, "中0", "摘0"), (1, "中1", "摘1"), (2, "中2", "摘2"))])

    out = common.summarize_all(client, _items(3), batch_size=6)

    assert len(client.prompts) == 1  # 3 条只花 1 次请求
    assert [o["title_zh"] for o in out] == ["中0", "中1", "中2"]
    assert "编号: 0" in client.prompts[0] and "编号: 2" in client.prompts[0]


def test_batch_splits_into_chunks():
    client = FakeClient([
        _batch((0, "A", "a"), (1, "B", "b")),
        _batch((0, "C", "c"), (1, "D", "d")),
        _batch((0, "E", "e")),
    ])

    out = common.summarize_all(client, _items(5), batch_size=2)

    assert len(client.prompts) == 3
    assert [o["title_zh"] for o in out] == ["A", "B", "C", "D", "E"]


def test_batch_results_follow_index_not_order():
    payload = json.dumps({"items": [
        {"index": 1, "title_zh": "第二条", "summary_zh": "摘"},
        {"index": 0, "title_zh": "第一条", "summary_zh": "摘"},
    ]})
    client = FakeClient([payload])

    out = common.summarize_all(client, _items(2), batch_size=2)

    assert [o["title_zh"] for o in out] == ["第一条", "第二条"]


def test_missing_entry_falls_back_to_single_call():
    client = FakeClient([
        _batch((0, "批量", "摘")),                      # 只回了第 0 条
        '{"title_zh": "单条", "summary_zh": "摘"}',      # 第 1 条走逐条补
    ])

    out = common.summarize_all(client, _items(2), batch_size=2)

    assert [o["title_zh"] for o in out] == ["批量", "单条"]
    assert len(client.prompts) == 2
    assert "编号:" not in client.prompts[1]  # 第二次是单条 prompt


def test_whole_batch_failure_falls_back_to_single_calls():
    client = FakeClient([
        "不是 JSON",
        '{"title_zh": "A", "summary_zh": "a"}',
        '{"title_zh": "B", "summary_zh": "b"}',
    ])

    out = common.summarize_all(client, _items(2), batch_size=2, retries=0)

    assert [o["title_zh"] for o in out] == ["A", "B"]


def test_failed_items_stay_none_instead_of_raising():
    client = FakeClient(["不是 JSON", RuntimeError("boom"), RuntimeError("boom")])

    out = common.summarize_all(client, _items(1), batch_size=1, retries=0)

    assert out == [None]


def test_invalid_batch_entries_are_dropped_and_retried_individually():
    payload = json.dumps({"items": [
        {"index": 0, "title_zh": "有效", "summary_zh": "摘"},
        {"index": 1, "title_zh": None, "summary_zh": "摘"},   # 字段类型不对
        {"index": 9, "title_zh": "越界", "summary_zh": "摘"},  # index 越界
    ]})
    client = FakeClient([payload, '{"title_zh": "补齐", "summary_zh": "摘"}'])

    out = common.summarize_all(client, _items(2), batch_size=2)

    assert [o["title_zh"] for o in out] == ["有效", "补齐"]


def test_no_client_returns_all_none():
    assert common.summarize_all(None, _items(3)) == [None, None, None]
    assert common.summarize_all(FakeClient([]), []) == []


def test_deep_style_uses_deep_rule():
    client = FakeClient([_batch((0, "深", "读"))])

    common.summarize_all(client, _items(1), style="deep")

    assert "导读" in client.prompts[0]
    assert "短摘要" not in client.prompts[0]


def test_unknown_style_falls_back_to_short():
    client = FakeClient([_batch((0, "中", "摘"))])

    common.summarize_all(client, _items(1), style="没这个风格")

    assert "120字以内" in client.prompts[0]


def test_apply_summaries_updates_items_and_counts():
    client = FakeClient([_batch((0, "中文0", "摘要0"), (1, "中文1", "摘要1"))])
    items = _items(2)

    ok = common.apply_summaries(client, items)

    assert ok == 2
    assert [i["title_zh"] for i in items] == ["中文0", "中文1"]
    assert [i["summary_zh"] for i in items] == ["摘要0", "摘要1"]


def test_apply_summaries_leaves_failures_untouched():
    client = FakeClient(["不是 JSON", RuntimeError("boom")])
    items = _items(1)

    ok = common.apply_summaries(client, items, retries=0)

    assert ok == 0
    assert "title_zh" not in items[0]


def test_single_item_helpers_unchanged():
    """逐条接口仍保留（批量失败兜底 + 既有调用方）。"""
    client = FakeClient(['{"title_zh": "单", "summary_zh": "摘"}'])
    assert common.summarize(client, {"title": "T", "summary": "S"}) == {"title_zh": "单", "summary_zh": "摘"}
    assert common.summarize(None, {"title": "T", "summary": "S"}) is None


def test_batch_size_comes_from_config_settings():
    client = FakeClient([
        _batch((0, "A", "a"), (1, "B", "b")),
        _batch((0, "C", "c")),
    ])

    out = common.summarize_all(client, _items(3), config={"settings": {"batch_size": 2}})

    assert len(client.prompts) == 2          # 按配置切成 2 + 1
    assert [o["title_zh"] for o in out] == ["A", "B", "C"]


def test_batch_size_falls_back_on_bad_config():
    assert common.batch_size_from(None) == common.BATCH_SIZE
    assert common.batch_size_from({"settings": {"batch_size": 0}}) == common.BATCH_SIZE
    assert common.batch_size_from({"settings": {"batch_size": "x"}}) == common.BATCH_SIZE
    assert common.batch_size_from({"settings": {"batch_size": 3}}) == 3
    assert common.batch_size_from({}, batch_size=2) == 2
