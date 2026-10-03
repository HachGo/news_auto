"""趋势“为何上升”：对 z ≥ 2 且有相关条目的趋势项，请模型只依据给出的标题写一两句解释。

每日一次批量调用，结果缓存到 data/radar/explanations/<日期>.json，同日重跑不重复调用。
没有 API Key 或模型无输出时不附解释，页面隐藏该区块，绝不编造。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from common import DEEPSEEK_MODEL, atomic_write_text

PROMPT = """你是数据新闻编辑。下面每个话题在今天的报道量明显高于近 30 天基线。
请只依据每个话题下给出的标题，用一两句话说明它为什么在上升；不要加入标题之外的事实、数字或推测。
只返回 JSON：{{"items": [{{"id": "话题 id", "zh": "中文解释（60 字内）", "en": "English explanation (under 35 words)"}}]}}

{topics}
"""


def attach_explanations(entries, client, cache_path):
    """为上升项附加 why 字段；缓存缺失的项才调用模型。"""
    cache_path = Path(cache_path)
    cache = _load(cache_path)
    wanted = [entry for entry in entries if entry.get("rising") and entry.get("related")]
    missing = [entry for entry in wanted if entry["id"] not in cache]
    if missing and client is not None:
        fresh = explain(client, missing)
        if fresh:
            cache.update(fresh)
            atomic_write_text(cache_path, json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    for entry in wanted:
        if entry["id"] in cache:
            entry["why"] = cache[entry["id"]]
    return entries


def explain(client, entries):
    blocks = []
    for entry in entries:
        titles = "\n".join(f"- {item['title'].get('en') or item['title'].get('zh')}" for item in entry["related"])
        blocks.append(f"[{entry['id']}] {entry['name']['en']} / {entry['name']['zh']}\n{titles}")
    prompt = PROMPT.format(topics="\n\n".join(blocks))
    ids = {entry["id"] for entry in entries}
    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}, max_tokens=4000, timeout=120,
        )
        data = json.loads(response.choices[0].message.content)
    except Exception as exc:
        print(f"[warn] 趋势解释生成失败: {exc}", file=sys.stderr)
        return {}
    output = {}
    for item in (data or {}).get("items") or []:
        if not isinstance(item, dict) or item.get("id") not in ids:
            continue
        zh, en = (item.get("zh") or "").strip(), (item.get("en") or "").strip()
        if zh and en:
            output[item["id"]] = {"zh": zh, "en": en}
    return output


def _load(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
