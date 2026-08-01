"""共享工具：纯函数、seen.json、LLM 客户端、渲染工具。三版面共用。"""

import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dateutil import parser as dtparser

CST = timezone(timedelta(hours=8))  # 北京时间

DEEP_CATEGORY = "深度精选"  # 独立模块，不参与 LLM 重要性排序

# 分类展示顺序：AI 与科技优先，深度媒体次之，其余靠后
CATEGORY_ORDER = ["AI 动态", "社区热点", DEEP_CATEGORY, "国际新闻"]


def category_rank(category):
    try:
        return CATEGORY_ORDER.index(category)
    except ValueError:
        return len(CATEGORY_ORDER)


def link_hash(link: str) -> str:
    return hashlib.sha1(link.encode("utf-8")).hexdigest()


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def entry_time(entry):
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            try:
                dt = dtparser.parse(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, OverflowError):
                continue
    return None


def matches_keywords(entry, keywords):
    text = " ".join(
        [entry.get("title", ""), strip_html(entry.get("summary", ""))]
    ).lower()
    for kw in keywords:
        kw_l = kw.lower()
        # 短关键词（如 AI）用单词边界匹配，避免误伤 (e.g. "aid")
        if len(kw_l) <= 4:
            if re.search(r"\b" + re.escape(kw_l) + r"\b", text):
                return True
        elif kw_l in text:
            return True
    return False


ROOT = Path(__file__).resolve().parent.parent
SEEN_FILE_DEFAULT = ROOT / "data" / "seen.json"

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")


def load_seen(path=None):
    path = path or SEEN_FILE_DEFAULT
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_seen(path, seen):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 只保留最近 30 天的指纹，防止文件无限增长
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=0, sort_keys=True)


def build_llm_client():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("[warn] DEEPSEEK_API_KEY 未设置，跳过 LLM，使用 RSS 原始摘要", file=sys.stderr)
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    except Exception as exc:
        print(f"[warn] 初始化 LLM 客户端失败: {exc}", file=sys.stderr)
        return None


RANK_PROMPT = """你是资深国际新闻主编。以下是今日候选新闻列表（编号、标题、来源、分类，部分带社区热度数据）。
请评估每条新闻的重要性和影响力，选出最重要的 {limit} 条。评分标准（1-10 分）：

- 9-10 分：全球级重大事件（重要 AI 模型/产品发布如 GPT、Kimi、DeepSeek 新版本，重大地缘政治事件，重要国际会议如 WAIC 开幕，行业格局改变的收购/政策）
- 7-8 分：有广泛影响的行业新闻、重要国家的重大政策、知名公司重要动向、社区高热度讨论
- 5-6 分：一般性行业新闻、区域性事件
- 1-4 分：琐碎消息、营销软文、纯观点评论、影响面小的本地新闻

要求：
1. 「社区热点」分类（Hacker News 高分榜、Reddit AI 社区当日最热）代表 X/Twitter 和技术社区正在疯传的内容，是捕捉病毒式传播事件的重要信号：热度高（如 HN 500+ points）且话题重大的条目应显著加分；但纯梗图、灌水贴、与 AI/科技/时事无关的娱乐内容仍应打低分。
2. 同一事件的多条重复报道只选最权威的一条。
3. AI 领域与国际新闻兼顾，但以重要性优先，不强求数量平衡。
4. 返回 JSON（不要其他文字）：{{"selected": [{{"index": 编号, "score": 分数}}, ...]}}，按分数从高到低排列，最多 {limit} 条。

候选新闻：
{items}
"""


def select_items(candidates, config):
    """降级方案：按来源均衡挑选，最多 total_limit 条（LLM 不可用时使用）。"""
    settings = config.get("settings", {})
    total_limit = settings.get("total_limit", 15)
    per_source_limit = settings.get("per_source_limit", 4)

    candidates.sort(key=lambda x: x["time"], reverse=True)

    selected, per_source = [], {}
    by_source = {}
    for item in candidates:
        by_source.setdefault(item["source"], []).append(item)

    sources = list(by_source.keys())
    idx = 0
    while len(selected) < total_limit and sources:
        src = sources[idx % len(sources)]
        pool = by_source[src]
        if pool and per_source.get(src, 0) < per_source_limit:
            item = pool.pop(0)
            selected.append(item)
            per_source[src] = per_source.get(src, 0) + 1
            idx += 1
        else:
            sources.remove(src)
            if sources:
                idx %= len(sources)
    selected.sort(key=lambda x: (x["category"], x["time"]), reverse=False)
    return selected


def select_deep(candidates, config):
    """「深度精选」模块：按时间取最新，来源均衡，不与常规新闻竞争名额。"""
    settings = config.get("settings", {})
    limit = settings.get("deep_limit", 6)
    per_source_limit = settings.get("deep_per_source_limit", 2)

    candidates.sort(key=lambda x: x["time"], reverse=True)
    selected = []
    counts = {}
    for item in candidates:
        if len(selected) >= limit:
            break
        if counts.get(item["source"], 0) >= per_source_limit:
            continue
        selected.append(item)
        counts[item["source"]] = counts.get(item["source"], 0) + 1
    return selected


def rank_and_select(client, candidates, config):
    """用 LLM 按重要性排序选取；失败时降级为来源均衡策略。"""
    settings = config.get("settings", {})
    total_limit = settings.get("total_limit", 15)

    if client is None or not candidates:
        return select_items(candidates, config)

    lines = []
    for i, item in enumerate(candidates):
        heat = ""
        m = re.search(r"Points:\s*(\d+)", item.get("summary", ""))
        if m:
            heat = f" (热度: {m.group(1)} points)"
        lines.append(f"{i}. [{item['category']}/{item['source']}] {item['title']}{heat}")
    prompt = RANK_PROMPT.format(limit=total_limit, items="\n".join(lines))

    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                reasoning_effort="high",
                max_tokens=8000,
                timeout=180,
                extra_body={"thinking": {"type": "enabled"}},
            )
            data = json.loads(resp.choices[0].message.content)
            picked = []
            seen_idx = set()
            for entry in data.get("selected", []):
                idx = entry.get("index")
                if not isinstance(idx, int) or idx in seen_idx:
                    continue
                if 0 <= idx < len(candidates):
                    item = candidates[idx]
                    item["score"] = entry.get("score", 5)
                    picked.append(item)
                    seen_idx.add(idx)
                if len(picked) >= total_limit:
                    break
            if picked:
                print(f"[info] LLM 重要性排序完成，选出 {len(picked)} 条")
                return picked
        except Exception as exc:
            print(f"[warn] 重要性排序失败 (attempt {attempt + 1}): {exc}", file=sys.stderr)
            time.sleep(3)
    print("[warn] 重要性排序不可用，降级为来源均衡策略", file=sys.stderr)
    return select_items(candidates, config)


PROMPT_TMPL = """你是新闻编辑。请将下面这条英文新闻翻译并总结，返回 JSON（不要包含其他文字）：
{{"title_zh": "中文标题", "summary_zh": "中文摘要，2-3句话，120字以内，客观精炼"}}

英文标题: {title}
英文内容: {summary}
"""


def summarize(client, item, retries=2):
    """调用 DeepSeek 生成中文标题与摘要；失败时返回 None（降级为原始内容）。"""
    if client is None:
        return None
    prompt = PROMPT_TMPL.format(title=item["title"], summary=item["summary"][:500])
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                reasoning_effort="high",
                max_tokens=2000,
                timeout=120,
                extra_body={"thinking": {"type": "enabled"}},
            )
            data = json.loads(resp.choices[0].message.content)
            title_zh = str(data.get("title_zh", "")).strip()
            summary_zh = str(data.get("summary_zh", "")).strip()
            if title_zh and summary_zh:
                return {"title_zh": title_zh, "summary_zh": summary_zh}
        except Exception as exc:
            print(f"[warn] LLM 调用失败 (attempt {attempt + 1}): {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def render_item(item, num):
    """渲染单条新闻为 markdown 行列表。"""
    block = []
    title_zh = item.get("title_zh") or item["title"]
    score = item.get("score")
    badge = "【重点】" if isinstance(score, (int, float)) and score >= 9 else ""
    block.append(f"### {num}. {badge}{title_zh}")
    block.append("")
    if item.get("title_zh"):
        block.append(f"> {item['title']}")
        block.append("")
    summary_zh = item.get("summary_zh") or item.get("summary", "")[:200]
    if summary_zh:
        block.append(summary_zh)
        block.append("")
    block.append(f"来源：[{item['source']}]({item['link']})")
    block.append("")
    return block


def render_sectioned(items, title, summary, focus_count=3):
    """渲染带焦点区 + 分类区的版面文章。ai/world 版面共用。"""
    date_str = title  # 调用方传入「每日资讯 YYYY-MM-DD」
    lines = [
        "---",
        f'title: "{title}"',
        f"date: {datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')}",
        'tags: ["每日简报"]',
        f'summary: "{summary}"',
        "---",
        "",
    ]

    scored = [i for i in items if "score" in i]
    if scored:
        items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
        focus, rest = items[:focus_count], items[focus_count:]
        lines.append("## 今日焦点")
        lines.append("")
        for n, item in enumerate(focus, 1):
            lines.extend(render_item(item, n))
        by_category = {}
        for item in rest:
            by_category.setdefault(item["category"], []).append(item)
        order = sorted(by_category.keys(), key=lambda c: (category_rank(c), c))
        for category in order:
            lines.append(f"## {category}")
            lines.append("")
            for n, item in enumerate(by_category[category], 1):
                lines.extend(render_item(item, n))
    else:
        by_category = {}
        for item in items:
            by_category.setdefault(item["category"], []).append(item)
        order = sorted(by_category.keys(), key=lambda c: (category_rank(c), c))
        for category in order:
            lines.append(f"## {category}")
            lines.append("")
            for n, item in enumerate(by_category[category], 1):
                lines.extend(render_item(item, n))
    return "\n".join(lines)


def load_config(path=None):
    path = Path(path) if path else ROOT / "scripts" / "feeds.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
