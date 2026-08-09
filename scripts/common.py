"""共享工具：纯函数、seen.json、LLM 客户端、渲染工具。四版面共用。"""

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

# 历史兼容；深度版面现按刊物 category 分组
DEEP_CATEGORY = "深度精选"

# 分类展示顺序
CATEGORY_ORDER = [
    "AI 动态",
    "社区热点",
    "国际新闻",
    "经济学人",
    "科学美国人",
    "长读",
    "大西洋月刊",
    DEEP_CATEGORY,
]


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


# 评分标准与选取规则：供 LLM prompt 与站点「方法」页共用，改这里即两边同步
SCORE_BANDS = [
    ("9-10", "全球级重大事件（重要 AI 模型/产品发布如 GPT、Kimi、DeepSeek 新版本，重大地缘政治事件，重要国际会议如 WAIC 开幕，行业格局改变的收购/政策）"),
    ("7-8", "有广泛影响的行业新闻、重要国家的重大政策、知名公司重要动向、社区高热度讨论"),
    ("5-6", "一般性行业新闻、区域性事件"),
    ("1-4", "琐碎消息、营销软文、纯观点评论、影响面小的本地新闻"),
]

RANK_RULES = [
    "「社区热点」分类（Hacker News 高分榜、Reddit AI 社区当日最热）代表技术社区正在疯传的内容：热度高（如 HN 500+ points）且话题重大的条目应显著加分；纯梗图、灌水贴、无关娱乐内容仍应打低分。",
    "同一事件的多条重复报道只选最权威的一条。",
    "以重要性优先，不强求各分类数量平衡。",
]

HIGHLIGHT_SCORE = 9  # 正文【重点】标记与今日焦点优先门槛


def build_rank_prompt(limit, items_text):
    bands = "\n".join(f"- {band} 分：{desc}" for band, desc in SCORE_BANDS)
    rules = "\n".join(f"{i}. {rule}" for i, rule in enumerate(RANK_RULES, 1))
    return (
        "你是资深国际新闻主编。以下是今日候选新闻列表（编号、标题、来源、分类，部分带社区热度数据）。\n"
        f"请评估每条新闻的重要性和影响力，选出最重要的 {limit} 条。评分标准（1-10 分）：\n\n"
        f"{bands}\n\n"
        "要求：\n"
        f"{rules}\n"
        f'{len(RANK_RULES) + 1}. 返回 JSON（不要其他文字）：{{"selected": [{{"index": 编号, "score": 分数}}, ...]}}，'
        f"按分数从高到低排列，最多 {limit} 条。\n\n"
        f"候选新闻：\n{items_text}\n"
    )


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
    """深度阅读：按时间取最新，来源均衡，不与快讯竞争名额。"""
    settings = config.get("settings", {})
    limit = settings.get("deep_limit", 8)
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
    prompt = build_rank_prompt(total_limit, "\n".join(lines))

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

DEEP_PROMPT_TMPL = """你是深度刊物编辑。请将下面这篇长读翻译并写导读，返回 JSON（不要包含其他文字）：
{{"title_zh": "中文标题", "summary_zh": "中文导读，3-4句话，180字以内，客观精炼，并点明为何值得深入阅读"}}

英文标题: {title}
英文内容: {summary}
"""


def _llm_summarize(client, item, prompt_tmpl, summary_chars, retries=2):
    if client is None:
        return None
    prompt = prompt_tmpl.format(title=item["title"], summary=item["summary"][:summary_chars])
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


def summarize(client, item, retries=2):
    """调用 DeepSeek 生成中文标题与摘要；失败时返回 None（降级为原始内容）。"""
    return _llm_summarize(client, item, PROMPT_TMPL, 500, retries=retries)


def summarize_deep(client, item, retries=2):
    """深度阅读：加长导读摘要。"""
    return _llm_summarize(client, item, DEEP_PROMPT_TMPL, 900, retries=retries)


def render_item(item, num):
    """渲染单条新闻为 markdown 行列表。"""
    block = []
    title_zh = item.get("title_zh") or item["title"]
    score = item.get("score")
    badge = "【重点】" if isinstance(score, (int, float)) and score >= HIGHLIGHT_SCORE else ""
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


def render_deep_item(item, num):
    """深度阅读单条：刊物式标题 / 英文副题 / 加长导读 / 刊头来源。"""
    title_zh = item.get("title_zh") or item["title"]
    summary_zh = item.get("summary_zh") or item.get("summary", "")[:280]
    source = item["source"]
    link = item["link"]
    block = [
        f'<article class="deep-item">',
        "",
        f"### {num}. {title_zh}",
        "",
    ]
    if item.get("title_zh"):
        block.append(f'<p class="deep-dek">{html.escape(item["title"])}</p>')
        block.append("")
    if summary_zh:
        block.append(summary_zh)
        block.append("")
    block.append(
        f'<p class="deep-source"><a href="{html.escape(link, quote=True)}">'
        f"{html.escape(source)}</a></p>"
    )
    block.append("")
    block.append("</article>")
    block.append("")
    return block


def render_deep(items, title, summary):
    """深度阅读版面：今日精选 + 按刊物分组。"""
    lines = [
        "---",
        f'title: "{title}"',
        f"date: {datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')}",
        'tags: ["每日简报", "深度阅读"]',
        f'summary: "{summary}"',
        "---",
        "",
        '<div class="deep-digest">',
        "",
        "## 今日精选",
        "",
    ]
    for n, item in enumerate(items, 1):
        lines.extend(render_deep_item(item, n))

    by_category = {}
    for item in items:
        by_category.setdefault(item.get("category") or "深度精选", []).append(item)
    order = sorted(by_category.keys(), key=lambda c: (category_rank(c), c))
    if len(order) > 1:
        lines.append("## 按刊物")
        lines.append("")
        for category in order:
            lines.append(f"### {category}")
            lines.append("")
            for item in by_category[category]:
                title_zh = item.get("title_zh") or item["title"]
                link = item["link"]
                lines.append(f"- [{title_zh}]({link})")
            lines.append("")

    lines.append("</div>")
    lines.append("")
    return "\n".join(lines)


def load_config(path=None):
    path = Path(path) if path else ROOT / "scripts" / "feeds.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
