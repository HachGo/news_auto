"""生成站点「网站规则」页：从 feeds.yaml 与评分常量同步，供网站展示。

运行：python scripts/method.py
每日 fetch_news 主流程会自动调用。
"""

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, unquote

from common import (
    CST,
    SCORE_BANDS,
    RANK_RULES,
    HIGHLIGHT_SCORE,
    DEEPSEEK_MODEL,
    load_config,
)

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = Path(__file__).resolve().parent / "feeds.yaml"
METHOD_PATH = ROOT / "content" / "method.md"

SECTION_META = {
    "ai": {
        "name": "AI与科技",
        "select": "LLM 按重要性评分排序（见下方评分标准），取 total_limit 条；失败时降级为来源轮询均衡。",
        "summary": "短摘要（约 2–3 句 / 120 字内）",
    },
    "world": {
        "name": "国际资讯",
        "select": "与 AI 版面相同：LLM 重要性排序 + 来源均衡降级。",
        "summary": "短摘要（约 2–3 句 / 120 字内）",
    },
    "market": {
        "name": "金融市场与股市",
        "select": "财经要闻取候选前 8 条、研报前 4 条（不做重要性排序，省 token）；行情 / 宏观日历 / 公告走专用接口。",
        "summary": "财经要闻与研报走短摘要；行情与日历为结构化表格。",
    },
    "deep": {
        "name": "深度阅读与学习",
        "select": "不参与 LLM 重要性排序；按发布时间取新，来源均衡（deep_limit / deep_per_source_limit）。",
        "summary": "加长导读（约 3–4 句 / 180 字内），强调为何值得读。",
    },
}

SECTION_ORDER = ("ai", "world", "market", "deep")

# 非 RSS、写死在生成器中的市场数据源（变更时请同步改这里）
MARKET_EXTRA_SOURCES = [
    ("东方财富", "https://quote.eastmoney.com/", "行情速览", "主要股指 / 商品 / VIX 点位与涨跌幅"),
    ("金十数据 / Forex Factory", "https://www.jin10.com/", "宏观与政策", "当日重要宏观数据日历"),
    ("巨潮资讯", "http://www.cninfo.com.cn/", "公告与研报", "A 股公司公告列表"),
]


def site_label(url):
    """从 RSS URL 提炼可读站点标识（优先域名，Google News 则尽量还原目标站）。"""
    if not url:
        return "—"
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    # Google News 聚合：从 q=site:example.com 还原目标站
    if "news.google.com" in host:
        query = unquote(parsed.query or "")
        for part in query.split("&"):
            if part.startswith("q="):
                q = part[2:]
                if "site:" in q:
                    after = q.split("site:", 1)[1]
                    # site:jiemian.com+财经 → 只取域名
                    site = after.replace("+", " ").split()[0].strip().rstrip("/")
                    return site or host
                return "news.google.com"
        return "news.google.com"

    return host or url


def feed_link_cell(feed):
    """表格中的「网站」列：可点击的站点标识。"""
    url = (feed.get("url") or "").strip()
    label = site_label(url)
    if url:
        return f"[{label}]({url})"
    return label


def build_method_page(config=None):
    config = config or load_config(FEEDS_FILE)
    settings = config.get("settings") or {}
    feeds = config.get("feeds") or []
    keywords = config.get("ai_keywords") or []
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M %z")

    by_section = {key: [] for key in SECTION_ORDER}
    for feed in feeds:
        sec = feed.get("section")
        if sec in by_section:
            by_section[sec].append(feed)

    total_feeds = sum(len(by_section[k]) for k in SECTION_ORDER)

    lines = [
        "---",
        'title: "网站规则"',
        'url: "/rules/"',
        f"date: {datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')}",
        'summary: "本站抓取哪些网站，以及如何筛选、评分与排序每日资讯。"',
        'body_class: "section-rules"',
        "ShowToc: true",
        "TocOpen: true",
        "---",
        "",
        "> 本页由脚本根据 `scripts/feeds.yaml` 与 `scripts/common.py` 中的公开规则自动生成，"
        "列出当前实际抓取的网站与筛选权重。"
        f"更新源或规则后，重新跑抓取流水线即可同步。上次生成：{now}。",
        "",
        "## 获取哪些网站",
        "",
        f"当前共配置 **{total_feeds}** 个 RSS / 新闻源，另加市场专用接口。"
        "下表即本站实际拉取的来源（含网站链接），增删改 `scripts/feeds.yaml` 后会自动反映到本页。",
        "",
    ]

    for key in SECTION_ORDER:
        meta = SECTION_META[key]
        lines.append(f"### {meta['name']}")
        lines.append("")
        lines.append("| 来源名称 | 网站 | 分类 | AI 过滤 | 候选上限 |")
        lines.append("|---|---|---|---|---|")
        for feed in by_section[key]:
            name = feed.get("name", "")
            cat = feed.get("category", "")
            ai_f = "是" if feed.get("ai_filter") else "否"
            max_items = feed.get("max_items", "—")
            lines.append(
                f"| {name} | {feed_link_cell(feed)} | {cat} | {ai_f} | {max_items} |"
            )
        if not by_section[key]:
            lines.append("| （暂无） | — | — | — | — |")
        lines.append("")

    lines.extend([
        "### 市场专用数据源（非 RSS）",
        "",
        "| 来源 | 网站 | 板块 | 说明 |",
        "|---|---|---|---|",
    ])
    for name, url, block, note in MARKET_EXTRA_SOURCES:
        label = site_label(url)
        lines.append(f"| {name} | [{label}]({url}) | {block} | {note} |")
    lines.append("")

    lines.extend([
        "## 筛选与排序规则",
        "",
        "### 流水线概览",
        "",
        "1. 按版面拉取上表中的 RSS / 专用数据源，过滤时间窗与已读指纹（`data/seen.json`，保留约 30 天）。",
        "2. **AI / 国际**：LLM 重要性排序 → 中文标题与摘要 → 写入当日 markdown。",
        "3. **市场**：行情 + 宏观日历 + 公告 + 财经 RSS（概览截取）→ 摘要要闻。",
        "4. **深度**：来源均衡选刊 → 加长导读 → 刊物式排版。",
        "5. 汇总四版面焦点，生成首页；并刷新本「网站规则」页。",
        "",
        f"默认摘要模型：`{DEEPSEEK_MODEL}`（可通过环境变量 `DEEPSEEK_MODEL` 覆盖）。"
        "未配置 API Key 时降级为英文 RSS 原文摘要，排序改为来源轮询。",
        "",
        "### 全局参数",
        "",
        "| 参数 | 当前值 | 含义 |",
        "|---|---|---|",
        f"| `total_limit` | {settings.get('total_limit', 15)} | AI / 国际每日最多精选条数 |",
        f"| `per_source_limit` | {settings.get('per_source_limit', 4)} | AI / 国际单来源最多入选 |",
        f"| `hours_window` | {settings.get('hours_window', 36)} | 只取最近 N 小时内发布的条目 |",
        f"| `deep_limit` | {settings.get('deep_limit', 8)} | 深度版面每日最多条数 |",
        f"| `deep_per_source_limit` | {settings.get('deep_per_source_limit', 2)} | 深度版面单来源最多条数 |",
        "",
        "### 各版面选取策略",
        "",
    ])

    for key in SECTION_ORDER:
        meta = SECTION_META[key]
        count = len(by_section[key])
        lines.append(f"#### {meta['name']}（`{key}`）")
        lines.append("")
        lines.append(f"- 配置源数量：{count}")
        lines.append(f"- 选取策略：{meta['select']}")
        lines.append(f"- 摘要形态：{meta['summary']}")
        lines.append("")

    lines.extend([
        "### LLM 重要性评分（AI / 国际）",
        "",
        "评分范围 1–10，由模型给出；分数越高越优先入选与进入「今日焦点」。",
        "",
        "| 分数段 | 含义 |",
        "|---|---|",
    ])
    for band, desc in SCORE_BANDS:
        lines.append(f"| {band} | {desc} |")
    lines.append("")
    lines.append("附加规则：")
    lines.append("")
    for i, rule in enumerate(RANK_RULES, 1):
        lines.append(f"{i}. {rule}")
    lines.append(
        f"{len(RANK_RULES) + 1}. 评分 ≥ {HIGHLIGHT_SCORE} 的条目在正文标记【重点】，并优先进入「今日焦点」。"
    )
    lines.append("")

    lines.extend([
        "### AI 关键词过滤",
        "",
        "对 `ai_filter: true` 的源（如 Hacker News Frontpage），标题/摘要需命中下列关键词之一才会进入候选"
        "（短词按单词边界匹配）：",
        "",
    ])
    if keywords:
        lines.append(", ".join(f"`{kw}`" for kw in keywords))
    else:
        lines.append("（当前未配置）")
    lines.append("")

    lines.extend([
        "### 去重与降级",
        "",
        "- 链接指纹写入 `data/seen.json`，已见条目不再重复入选。",
        "- LLM 排序失败：按来源轮询均衡选取（`select_items`）。",
        "- LLM 摘要失败：使用 RSS 原始英文摘要；若配置了 Key 且该版面全部摘要失败则跳过发布。",
        "",
        "## 如何更新本页",
        "",
        "1. 改 `scripts/feeds.yaml`（源、网站、条数、时间窗等）。",
        "2. 改 `scripts/common.py` 中的 `SCORE_BANDS` / `RANK_RULES` / `HIGHLIGHT_SCORE`（公开评分权重）。",
        "3. 运行 `python scripts/fetch_news.py`（或单独 `python scripts/method.py`）。",
        "",
    ])
    return "\n".join(lines)


def write_method_page(config=None, path=None):
    path = Path(path) if path else METHOD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    text = build_method_page(config)
    path.write_text(text, encoding="utf-8")
    print(f"[info] 网站规则页已生成 {path}")
    return path


if __name__ == "__main__":
    write_method_page()
