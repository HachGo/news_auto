"""共享工具：纯函数、seen.json、LLM 客户端、渲染工具。四版面共用。"""

import hashlib
import html
import json
import os
import re
import sys
import tempfile
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


# 英文版页面的分类 / 分区标题
CATEGORY_EN = {
    "今日焦点": "Top stories",
    "AI 动态": "AI news",
    "社区热点": "Community picks",
    "国际新闻": "World news",
    "经济学人": "The Economist",
    "科学美国人": "Scientific American",
    "长读": "Long reads",
    "大西洋月刊": "The Atlantic",
    DEEP_CATEGORY: "Featured",
    "财经要闻": "Markets news",
    "研报要点": "Research notes",
    "资讯": "News",
}

_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def has_cjk(text) -> bool:
    return bool(_CJK_RE.search(text or ""))


def category_en(category):
    return CATEGORY_EN.get(category, category)


def item_id(item) -> str:
    """条目稳定锚点：中英文页面、首页与搜索共用，与标题文字无关。"""
    key = item.get("link") or item.get("title_zh") or item.get("title") or ""
    return "i-" + link_hash(key)[:10]


def title_en(item) -> str:
    """英文标题：模型译文 > 英文原标题 > 中文标题兜底。"""
    if item.get("title_en"):
        return item["title_en"]
    original = item.get("title") or ""
    if original and not has_cjk(original):
        return original
    return item.get("title_zh") or original


def summary_en(item, limit=200) -> str:
    """英文摘要：模型摘要 > 英文 RSS 摘要；都没有时留空（不用中文充数）。"""
    if item.get("summary_en"):
        return item["summary_en"]
    summary = item.get("summary") or ""
    if summary and not has_cjk(summary):
        return summary[:limit]
    return ""


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


def text_matches_keywords(text, keywords):
    """标题/摘要是否命中关键词列表（不区分大小写）。

    - 含中日韩字符的词：子串匹配（中文无词界）
    - 短英文词（≤4）：单词边界匹配，避免 AI 误伤 aid
    - 其余：子串匹配
    """
    text = strip_html(text or "").lower()
    if not text or not keywords:
        return False
    for kw in keywords:
        kw_l = (kw or "").lower().strip()
        if not kw_l:
            continue
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", kw_l):
            if kw_l in text:
                return True
        elif len(kw_l) <= 4:
            if re.search(r"\b" + re.escape(kw_l) + r"\b", text):
                return True
        elif kw_l in text:
            return True
    return False


def matches_keywords(entry, keywords):
    text = " ".join(
        [entry.get("title", ""), strip_html(entry.get("summary", ""))]
    )
    return text_matches_keywords(text, keywords)


def is_blocked(entry, block_keywords):
    """命中屏蔽词则不应入选。"""
    return matches_keywords(entry, block_keywords or [])


ROOT = Path(__file__).resolve().parent.parent
SEEN_FILE_DEFAULT = ROOT / "data" / "seen.json"

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")


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
    atomic_write_text(path, json.dumps(pruned, ensure_ascii=False, indent=0, sort_keys=True))


def atomic_write_text(path, content):
    """在同一目录写临时文件后原子替换，避免中途失败截断原文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary, path.stat().st_mode if path.exists() else 0o644)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


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


# 评分标准：LLM prompt 与前台「网站规则」页共用
SCORE_BANDS = [
    ("9-10", "全球级重大事件（重要 AI 模型/产品发布如 GPT、Kimi、DeepSeek 新版本，重大地缘政治事件，APEC、G20、联合国气候大会等重要国际会议的重大议程或实质成果，WAIC 等重要科技会议开幕，行业格局改变的收购/政策）"),
    ("7-8", "有广泛影响的行业新闻、重要国家的重大政策、知名公司重要动向、社区高热度讨论"),
    ("5-6", "一般性行业新闻、区域性事件"),
    ("1-4", "琐碎消息、营销软文、纯观点评论、影响面小的本地新闻"),
]

# 可公开展示的排序规则（写入「网站规则」页）
RANK_RULES = [
    "「社区热点」分类（Hacker News 高分榜、Reddit AI 社区当日最热）代表技术社区正在疯传的内容：热度高（如 HN 500+ points）且话题重大的条目应显著加分；纯梗图、灌水贴、无关娱乐内容仍应打低分。",
    "同一事件的多条重复报道只选最权威的一条。",
    "以重要性优先，不强求各分类数量平衡。",
    "重大国际会议、外交、经贸、公共政策和地缘事件的客观事实报道正常参与评选，不因提及政治人物、职务、国家地区、外交或制裁等词汇而排除或降分；按事件的实际影响、事实增量和来源可靠性评分。",
    "APEC、G20、联合国气候大会等重要国际会议，重点关注重大议程、实际协议与政策成果、全球经济和安全影响；不要仅凭会议名称或领导人出席就给高分。",
    "纯党争、竞选宣传、人物吹捧、无实质新增事实的立场评论和重复表态按 1–4 分降权；涉及重大政策或公共影响的事实报道不属于此类。",
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


def _normalize_score(value):
    """模型分数统一为 1–10 的数值，非法值按默认 5 分处理。"""
    if isinstance(value, bool):
        return 5
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return 5
    return score if 1 <= score <= 10 else 5


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
                if not isinstance(entry, dict):
                    continue
                idx = entry.get("index")
                if type(idx) is not int or idx in seen_idx:
                    continue
                if 0 <= idx < len(candidates):
                    item = candidates[idx].copy()
                    item["score"] = _normalize_score(entry.get("score", 5))
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


PROMPT_TMPL = """你是双语新闻编辑。请阅读下面这条新闻（原文可能是英文或中文），翻译并总结，返回 JSON（不要包含其他文字）：
{{"title_zh": "中文标题", "summary_zh": "中文摘要，2-3句话，120字以内，客观精炼",
"title_en": "English headline; keep the original wording if the source is already English",
"summary_en": "English summary, 2-3 sentences, under 60 words, neutral and concise",
"importance": 1-10 的整数（9-10 全球级重大事件，7-8 影响广泛，5-6 一般行业新闻，1-4 琐碎消息）}}

原标题: {title}
原文内容: {summary}
"""

DEEP_PROMPT_TMPL = """你是深度刊物编辑。请将下面这篇长读翻译并写导读，返回 JSON（不要包含其他文字）：
{{"title_zh": "中文标题", "summary_zh": "中文导读，3-4句话，180字以内，客观精炼，并点明为何值得深入阅读",
"title_en": "English headline; keep the original wording if the source is already English",
"summary_en": "English blurb, 3-4 sentences, under 90 words, neutral, saying why it is worth reading"}}

英文标题: {title}
英文内容: {summary}
"""

TRANSLATE_LINES_TMPL = """Translate each line below into concise English. Keep numbers, units and proper nouns.
Return JSON only: {{"lines": ["...", ...]}} with exactly {count} strings in the same order.

{lines}
"""


# 批量摘要：一次请求处理多条，把每天 50 次左右的调用压到 10 次上下
BATCH_PROMPT_TMPL = """你是双语新闻编辑。下面有 {count} 条新闻（原文可能是英文或中文），请逐条翻译并总结，返回 JSON（不要包含其他文字）：
{{"items": [{{"index": 编号, "title_zh": "中文标题", "summary_zh": "{rule}",
"title_en": "English headline; keep the original wording if the source is already English",
"summary_en": "{rule_en}",
"importance": 1-10 的整数（9-10 全球级重大事件，7-8 影响广泛，5-6 一般行业新闻，1-4 琐碎消息）}}, ...]}}

要求：index 必须与下面给出的编号一一对应，不得遗漏或新增条目。

{blocks}"""

SUMMARY_RULES = {
    "short": "中文摘要，2-3句话，120字以内，客观精炼",
    "deep": "中文导读，3-4句话，180字以内，客观精炼，并点明为何值得深入阅读",
}

BATCH_SIZE = 6


def _clean_summary(data):
    """校验中文摘要，并保留有效的英文字段与重要性。"""
    if not isinstance(data, dict):
        return None
    title_zh = data.get("title_zh")
    summary_zh = data.get("summary_zh")
    if not isinstance(title_zh, str) or not isinstance(summary_zh, str):
        return None
    title_zh = title_zh.strip()
    summary_zh = summary_zh.strip()
    if not title_zh or not summary_zh:
        return None
    result = {"title_zh": title_zh, "summary_zh": summary_zh}
    for key in ("title_en", "summary_en"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    if "importance" in data:
        result["importance"] = _normalize_score(data.get("importance"))
    return result


def _llm_call(client, prompt, max_tokens, retries, parse=None, timeout=120):
    """调用 LLM 并把回复交给 parse()；parse 返回 None 就重试，最终失败返回 None。"""
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                reasoning_effort="high",
                max_tokens=max_tokens,
                timeout=timeout,
                extra_body={"thinking": {"type": "enabled"}},
            )
            value = parse(resp.choices[0].message.content) if parse else json.loads(
                resp.choices[0].message.content)
            if value is not None:
                return value
        except Exception as exc:
            print(f"[warn] LLM 调用失败 (attempt {attempt + 1}): {exc}", file=sys.stderr)
        time.sleep(2 * (attempt + 1))
    return None


def _parse_summary(content):
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return None
    return _clean_summary(data)


def _llm_summarize(client, item, prompt_tmpl, summary_chars, retries=2):
    if client is None:
        return None
    prompt = prompt_tmpl.format(title=item["title"], summary=item["summary"][:summary_chars])
    return _llm_call(client, prompt, max_tokens=2000, retries=retries, parse=_parse_summary)


def translate_lines(client, lines, retries=1):
    """批量把短行译成英文；失败或条数不符时返回 None（调用方保留原文）。"""
    if client is None or not lines:
        return None
    prompt = TRANSLATE_LINES_TMPL.format(count=len(lines), lines="\n".join(lines))
    for attempt in range(retries + 1):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=2000,
                timeout=120,
            )
            data = json.loads(resp.choices[0].message.content)
            out = data.get("lines") if isinstance(data, dict) else None
            if isinstance(out, list) and len(out) == len(lines) and all(isinstance(x, str) for x in out):
                return [x.strip() or orig for x, orig in zip(out, lines)]
        except Exception as exc:
            print(f"[warn] 翻译失败 (attempt {attempt + 1}): {exc}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def summarize(client, item, retries=2):
    """调用 DeepSeek 生成中文标题与摘要；失败时返回 None（降级为原始内容）。"""
    return _llm_summarize(client, item, PROMPT_TMPL, 500, retries=retries)


def summarize_deep(client, item, retries=2):
    """深度阅读：加长导读摘要。"""
    return _llm_summarize(client, item, DEEP_PROMPT_TMPL, 900, retries=retries)


def _batch_prompt(items, style, summary_chars):
    blocks = [
        f"编号: {index}\n原标题: {item['title']}\n原文内容: {item['summary'][:summary_chars]}"
        for index, item in enumerate(items)
    ]
    return BATCH_PROMPT_TMPL.format(
        count=len(items), rule=SUMMARY_RULES[style],
        rule_en=("English blurb, 3-4 sentences, under 90 words, neutral, saying why it is worth reading"
                 if style == "deep" else "English summary, 2-3 sentences, under 60 words, neutral and concise"),
        blocks="\n\n".join(blocks))


def _parse_batch(content, size):
    """解析批量回复，按 index 对齐成长度 size 的列表（无效项为 None）。"""
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return None
    entries = data.get("items") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        return None
    results = [None] * size
    filled = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < size:
            continue
        cleaned = _clean_summary(entry)
        if cleaned:
            results[index] = cleaned
            filled += 1
    return results if filled else None


def batch_size_from(config, batch_size=None):
    """每批条数：显式参数 > feeds.yaml 的 settings.batch_size > 默认值。"""
    if batch_size:
        try:
            return max(1, int(batch_size))
        except (TypeError, ValueError):
            return BATCH_SIZE
    try:
        value = int((config or {}).get("settings", {}).get("batch_size", BATCH_SIZE))
    except (TypeError, ValueError, AttributeError):
        return BATCH_SIZE
    return value if value > 0 else BATCH_SIZE


def summarize_all(client, items, style="short", batch_size=None, retries=1, config=None):
    """批量摘要，返回与 items 等长的结果列表（失败项为 None）。

    一次请求处理 batch_size 条，把每日请求数从「每条一次」压到十分之一左右；
    整批失败时退回逐条调用，漏项也只补那几条，不会因为一次失败丢掉整批摘要。
    """
    batch_size = batch_size_from(config, batch_size)
    items = list(items)
    results = [None] * len(items)
    if client is None or not items:
        return results

    style = style if style in SUMMARY_RULES else "short"
    prompt_tmpl = DEEP_PROMPT_TMPL if style == "deep" else PROMPT_TMPL
    summary_chars = 900 if style == "deep" else 500

    for start in range(0, len(items), batch_size):
        chunk = items[start:start + batch_size]
        parsed = _llm_call(
            client,
            _batch_prompt(chunk, style, summary_chars),
            max_tokens=min(8000, 1200 + 700 * len(chunk)),
            retries=retries,
            parse=lambda content, size=len(chunk): _parse_batch(content, size),
        )
        if parsed is None:
            print(f"[warn] 批量摘要失败，退回逐条摘要（{len(chunk)} 条）", file=sys.stderr)
            parsed = [None] * len(chunk)

        for offset, value in enumerate(parsed):
            if value is None:
                value = _llm_summarize(client, chunk[offset], prompt_tmpl, summary_chars, retries=1)
            results[start + offset] = value
    return results


def apply_summaries(client, items, style="short", batch_size=None, retries=1, config=None):
    """批量摘要并写回双语字段与重要性，返回成功条数。"""
    results = summarize_all(client, items, style=style, batch_size=batch_size,
                            retries=retries, config=config)
    ok = 0
    for item, result in zip(items, results):
        if result:
            item.update(result)
            ok += 1
    return ok


def render_item(item, num, lang="zh"):
    """渲染单条新闻为 markdown 行列表。标题带 {#id}，中英文页同一条目锚点一致。"""
    block = []
    anchor = f" {{#{item_id(item)}}}"
    if lang == "en":
        block.append(f"### {num}. {title_en(item)}{anchor}")
        block.append("")
        summary = summary_en(item)
        if summary:
            block.append(summary)
            block.append("")
        block.append(f"Source: [{item['source']}]({item['link']})")
        block.append("")
        return block
    title_zh = item.get("title_zh") or item["title"]
    score = item.get("score")
    badge = "【重点】" if isinstance(score, (int, float)) and score >= HIGHLIGHT_SCORE else ""
    block.append(f"### {num}. {badge}{title_zh}{anchor}")
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


def front_matter(title, summary, tags):
    return [
        "---",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        f"date: {datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        f"summary: {json.dumps(summary, ensure_ascii=False)}",
        "---",
        "",
    ]


def render_sectioned(items, title, summary, focus_count=3, lang="zh"):
    """渲染带焦点区 + 分类区的版面文章。ai/world 版面共用；lang="en" 输出英文版。"""
    en = lang == "en"
    heading = category_en if en else (lambda c: c)
    lines = front_matter(title, summary, ["Daily brief"] if en else ["每日简报"])

    scored = [i for i in items if "score" in i]
    if scored:
        items = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
        focus, rest = items[:focus_count], items[focus_count:]
        lines.append(f"## {heading('今日焦点')}")
        lines.append("")
        for n, item in enumerate(focus, 1):
            lines.extend(render_item(item, n, lang))
        by_category = {}
        for item in rest:
            by_category.setdefault(item["category"], []).append(item)
        order = sorted(by_category.keys(), key=lambda c: (category_rank(c), c))
        for category in order:
            lines.append(f"## {heading(category)}")
            lines.append("")
            for n, item in enumerate(by_category[category], 1):
                lines.extend(render_item(item, n, lang))
    else:
        by_category = {}
        for item in items:
            by_category.setdefault(item["category"], []).append(item)
        order = sorted(by_category.keys(), key=lambda c: (category_rank(c), c))
        for category in order:
            lines.append(f"## {heading(category)}")
            lines.append("")
            for n, item in enumerate(by_category[category], 1):
                lines.extend(render_item(item, n, lang))
    return "\n".join(lines)


def render_deep_item(item, num, lang="zh"):
    """深度阅读单条：刊物式标题 / 原文副题 / 加长导读 / 刊头来源。"""
    source = item["source"]
    link = item["link"]
    anchor = f" {{#{item_id(item)}}}"
    if lang == "en":
        heading, summary = title_en(item), summary_en(item, 280)
    else:
        heading = item.get("title_zh") or item["title"]
        summary = item.get("summary_zh") or item.get("summary", "")[:280]
    block = [
        f'<article class="deep-item">',
        "",
        f"### {num}. {heading}{anchor}",
        "",
    ]
    if lang != "en" and item.get("title_zh"):
        block.append(f'<p class="deep-dek">{html.escape(item["title"])}</p>')
        block.append("")
    if summary:
        block.append(summary)
        block.append("")
    block.append(
        f'<p class="deep-source"><a href="{html.escape(link, quote=True)}" '
        f'target="_blank" rel="noopener">{html.escape(source)}</a></p>'
    )
    block.append("")
    block.append("</article>")
    block.append("")
    return block


def render_deep(items, title, summary, lang="zh"):
    """深度阅读版面：今日精选 + 按刊物分组；lang="en" 输出英文版。"""
    en = lang == "en"
    lines = front_matter(title, summary, ["Daily brief", "Deep reads"] if en else ["每日简报", "深度阅读"])
    lines.extend([
        '<div class="deep-digest">',
        "",
        "## Today's picks" if en else "## 今日精选",
        "",
    ])
    for n, item in enumerate(items, 1):
        lines.extend(render_deep_item(item, n, lang))

    by_category = {}
    for item in items:
        by_category.setdefault(item.get("category") or "深度精选", []).append(item)
    order = sorted(by_category.keys(), key=lambda c: (category_rank(c), c))
    if len(order) > 1:
        lines.append("## By publication" if en else "## 按刊物")
        lines.append("")
        for category in order:
            lines.append(f"### {category_en(category) if en else category}")
            lines.append("")
            for item in by_category[category]:
                label = title_en(item) if en else (item.get("title_zh") or item["title"])
                lines.append(f"- [{label}]({item['link']})")
            lines.append("")

    lines.append("</div>")
    lines.append("")
    return "\n".join(lines)


def load_config(path=None):
    path = Path(path) if path else ROOT / "scripts" / "feeds.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
