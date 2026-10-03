"""生成站点「网站规则」页：从 feeds.yaml 与评分常量同步，供网站展示。

运行：python scripts/method.py
每日 fetch_news 主流程会自动调用。
"""

import json
from pathlib import Path
from urllib.parse import urlparse, unquote

from cluster import SIMILARITY
from ideas import FETCH_LIMIT as IDEA_FETCH_LIMIT, HALF_LIFE_DAYS as IDEA_HALF_LIFE, SITE_BOOST as IDEA_BOOST
from ideas import SOURCE_MODULES as IDEA_SOURCES, WEIGHTS as IDEA_WEIGHTS
from common import (
    atomic_write_text,
    category_en,
    SCORE_BANDS,
    RANK_RULES,
    HIGHLIGHT_SCORE,
    DEEPSEEK_MODEL,
    load_config,
)

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = Path(__file__).resolve().parent / "feeds.yaml"
RULES_PATH = ROOT / "data" / "radar" / "rules.json"

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


def site_home(url):
    """「网站」链接的落点：站点首页，而不是 RSS XML（浏览器打开只会显示源码）。"""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if "news.google.com" in host:
        label = site_label(url)
        if label != "news.google.com":
            return f"https://{label}/"
        # 关键词聚合：RSS 搜索换成网页版搜索结果
        return url.replace("/rss/search", "/search", 1)
    if not parsed.netloc:
        return url
    return f"{parsed.scheme or 'https'}://{parsed.netloc}/"


def feed_link_cell(feed):
    """表格中的「网站」列：站点标识链到网站首页，附 RSS 原始地址。

    feeds.yaml 可用 homepage 覆盖首页（hnrss.org、feeds.bbci.co.uk 这类纯 RSS 域名）。
    """
    url = (feed.get("url") or "").strip()
    homepage = (feed.get("homepage") or "").strip()
    if not url and not homepage:
        return "—"
    label = site_label(homepage or url)
    cell = f"[{label}]({homepage or site_home(url)})"
    if url:
        cell += f" · [RSS]({url})"
    return cell


SCORE_BANDS_EN = {
    "9-10": "Major global events (major AI model/product releases such as new GPT, Kimi or DeepSeek versions, major geopolitical events, important international conferences such as WAIC, acquisitions or policies that reshape an industry)",
    "7-8": "Industry news with broad impact, major policies in important countries, significant moves by well-known companies, highly discussed community stories",
    "5-6": "General industry news and regional events",
    "1-4": "Minor updates, marketing articles, pure opinion commentary and local news with limited impact",
}
RANK_RULES_EN = {
    0: "Community picks (top Hacker News stories and the day's hottest Reddit AI posts) reflect what the tech community is sharing: popular stories (for example HN 500+ points) about major topics deserve significantly higher scores; memes, spam and unrelated entertainment still receive low scores.",
    1: "For duplicate reports of the same event, select only the most authoritative report.",
    2: "Prioritize importance without forcing equal numbers in each category.",
}


IDEA_WEIGHT_NAMES = {"money": ("金额与支持者", "Money & backers"), "stars": ("收藏与星标", "Saves & stars"),
                     "upvotes": ("点赞", "Upvotes"), "comments": ("评论", "Comments")}
IDEA_SOURCE_CATEGORY = {"show_hn": ("作品展示", "Show HN posts"), "github": ("新仓库", "New repositories"),
                        "v2ex": ("分享创造", "Shared creations"), "hackaday": ("硬件巧思", "Hardware hacks"),
                        "sspai": ("工具与方法", "Tools & methods")}


def _pair(zh, en):
    return {"zh": str(zh), "en": str(en)}


def _row(zh, en, value=None, desc=None, kind="value", chips=None):
    return {"label": _pair(zh, en), "desc": desc or _pair("", ""),
            "kind": kind, "value": value or _pair("", ""), "chips": chips or []}


def build_rules(config):
    """仅导出公开规则和真实配置，不包含后台过滤内容。"""
    from trends.config import TOPICS
    settings = config.get("settings") or {}
    group = lambda zh, en, rows: {"title": _pair(zh, en), "rows": rows}
    section = lambda key, steps, zh, en, dz, de, groups: {
        "key": key, "steps": steps, "name": _pair(zh, en), "desc": _pair(dz, de), "groups": groups}
    locked = lambda zh, en: _row(zh, en, kind="locked")
    limits = [("hours_window", 36), ("total_limit", 15), ("per_source_limit", 4),
              ("deep_limit", 8), ("deep_per_source_limit", 2)]
    sections = [
        section("fetch", [0, 1], "获取", "Fetch", "来源、时间窗与上限", "Sources, window and limits", [
            group("运行安排", "Schedule", [
                _row("抓取时间", "Fetch schedule", _pair("每日北京时间 06:00，以及每次推送到 main", "Daily 06:00 Beijing time, and on every push to main")),
                _row("同日重跑", "Same-day reruns", _pair("复用已完成的版面", "Reuse finished sections")),
            ]),
            group("抓取上限", "Limits", [_row(k, k, _pair(str(settings.get(k, default)) + (" h" if k == "hours_window" else ""), str(settings.get(k, default)) + (" h" if k == "hours_window" else ""))) for k, default in limits]),
            group("获取原则", "Fetch principles", [
                locked("仅存储链接和短摘要", "Store link + short summary only"),
                locked("版面失败不阻塞其他版面，错误记录来源名称", "A failed section never blocks the others; errors are logged with the source name"),
            ]),
        ]),
        section("filter", [2], "筛选", "Filter", "关键词与去重", "Keywords and dedupe", [
            group("AI 关键词过滤", "AI keyword filter", [_row("关键词", "Keywords", kind="chips", chips=[_pair(k, k) for k in config.get("ai_keywords", [])], desc=_pair("适用于 ai_filter: true 的来源", "Applies to feeds with ai_filter: true"))]),
            group("去重", "Dedupe", [
                _row("链接指纹", "Seen-link fingerprints", _pair("保留约 30 天", "Kept about 30 days")),
                _row("同一事件", "Same story", _pair(RANK_RULES[1], RANK_RULES_EN[1])),
                _row("合并报道", "Merged reports", _pair(f"标题与摘要 TF-IDF 相似度 ≥ {SIMILARITY}", f"Title + summary TF-IDF similarity ≥ {SIMILARITY}"),
                     desc=_pair("同日候选中报道同一事件的其他来源并入该事件；英文与中文报道分别与事件的英文、中文标题比对，不调用模型",
                                "Other same-day reports of the story join the event; English and Chinese reports are compared with the event's English and Chinese text. No model is used.")),
            ]),
        ]),
        section("analyze", [3, 5], "分析", "Analyze", "评分、趋势与预测", "Scoring, trends and forecasts", [
            group("内容分析", "Content analysis", [
                _row("模型", "Model", _pair(DEEPSEEK_MODEL, DEEPSEEK_MODEL)),
                _row("重要性评分", "Importance bands", kind="list", chips=[{"label": _pair(b, b), "desc": _pair(d, SCORE_BANDS_EN[b])} for b, d in SCORE_BANDS]),
                _row("排序规则", "Ranking rules", kind="list", chips=[{"label": _pair(str(i + 1), str(i + 1)), "desc": _pair(r, RANK_RULES_EN[i])} for i, r in enumerate(RANK_RULES)]),
                _row("重点门槛", "Highlight threshold", _pair(f"≥ {HIGHLIGHT_SCORE}", f"≥ {HIGHLIGHT_SCORE}")),
            ]),
            group("趋势", "Trends", [
                _row("上升信号", "Rising signals", _pair("趋势页 z ≥ 2；首页显示 z > 0 的前 5 项", "Trends: z ≥ 2; home: top 5 with z > 0")),
                _row("基线", "Baseline", _pair("30 天，至少 7 天", "30 days, minimum 7 days")),
                _row("主题", "Topics", kind="chips", chips=[_pair(v["name"], v["name_en"]) for v in TOPICS.values()]),
                _row("创意类别", "Idea categories", _pair("每日新增条数，满 8 天历史后参与", "Daily new ideas per type, once 8 days of history exist")),
                _row("上升原因", "Why it is rising", _pair("模型只依据相关标题写一两句；无模型时不显示", "One or two model-written sentences grounded only in the related headlines; hidden without a model")),
            ]),
            group("创意评分", "Idea scoring", [
                _row("信号权重", "Signal weights", kind="list", chips=[
                    {"label": _pair(f"×{w}", f"×{w}"), "desc": _pair(IDEA_WEIGHT_NAMES[k][0], IDEA_WEIGHT_NAMES[k][1])} for k, w in IDEA_WEIGHTS.items()],
                    desc=_pair("各信号先换算为该来源近 30 天内的百分位，再加权平均；无信号的来源记 50",
                               "Each signal becomes a percentile within its source over 30 days, then a weighted mean; sources without signals score 50")),
                _row("时间衰减", "Time decay", _pair(f"半衰期 {IDEA_HALF_LIFE} 天", f"Half-life {IDEA_HALF_LIFE} days")),
                _row("跨站加分", "Cross-site boost", _pair(f"每多一个站点 +{IDEA_BOOST}", f"+{IDEA_BOOST} for each extra site")),
                _row("模型标注", "Model labels", _pair("类型、为何巧妙、适合谁、上手难度；剔除非创意内容", "Type, why it is clever, who it is for, effort; non-ideas are dropped")),
            ]),
            group("预测", "Forecasts", [
                _row("规则模型", "Rule model", _pair("rules-v1 · 4 个周期", "rules-v1 · 4 horizons")),
                _row("验证方式", "Resolution", _pair("按目标日跨资产市场动量的正负方向验证", "Resolved by the sign of cross-asset market momentum on the target date")),
                locked("校准前不提供概率", "No probabilities until calibrated"),
            ]),
        ]),
        section("publish", [4, 6], "发布", "Publish", "静态站点与边界", "Static site and boundaries", [
            group("网站", "Website", [_row("发布方式", "Publishing", _pair("GitHub Pages 静态站点 · 中文与英文", "Static site on GitHub Pages · Chinese + English"))]),
            group("发布原则", "Publishing principles", [
                locked("内容不构成投资建议", "Not financial advice"),
                locked("不进行自动交易", "No automated trading"),
                locked("API 密钥存于 GitHub Actions secrets，绝不提交", "API key lives in GitHub Actions secrets and is never committed"),
                locked("预测记录不覆盖，结果追加保存", "Forecast records are never overwritten; results are appended"),
            ]),
        ]),
    ]
    names_en = {"第一财经": "Yicai", "财新": "Caixin", "界面新闻": "Jiemian", "华尔街见闻": "Wallstreetcn", "券商研报": "Broker research"}
    sources = []
    for feed in config.get("feeds", []):
        url = feed.get("url") or ""
        homepage = feed.get("homepage") or site_home(url)
        name = feed.get("name", "")
        sources.append({"name": _pair(name, feed.get("name_en") or names_en.get(name, name)),
                        "section": feed.get("section"), "site": site_label(feed.get("homepage") or url),
                        "href": homepage, "rss": url,
                        "category": _pair(feed.get("category", ""), category_en(feed.get("category", ""))),
                        "access": "RSS", "max_items": feed.get("max_items", 10), "ai_filter": bool(feed.get("ai_filter"))})
    for (name, url, category, _), en in zip(MARKET_EXTRA_SOURCES, ["Eastmoney", "Jin10 / Forex Factory", "CNINFO"]):
        sources.append({"name": _pair(name, en), "section": "market", "site": site_label(url), "href": url,
                        "rss": "", "category": _pair(category, {"行情速览": "Market quotes", "宏观与政策": "Macro & policy", "公告与研报": "Filings & research"}[category]),
                        "access": "API", "max_items": None, "ai_filter": False})
    for key, module in IDEA_SOURCES.items():
        url = module.URL.split("?")[0] if module.ACCESS == "API" else module.URL
        sources.append({"name": _pair(module.NAME, getattr(module, "NAME_EN", module.NAME)), "section": "ideas",
                        "site": site_label(url), "href": site_home(url), "rss": module.URL if module.ACCESS == "RSS" else "",
                        "category": _pair(*IDEA_SOURCE_CATEGORY[key]), "access": module.ACCESS,
                        "max_items": IDEA_FETCH_LIMIT, "ai_filter": False})
    return {"sections": sections, "sources": sources}


def write_rules(config, path=RULES_PATH):
    """内容不变时保留文件，避免同日重跑产生提交。"""
    path = Path(path)
    text = json.dumps(build_rules(config), ensure_ascii=False, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        atomic_write_text(path, text)
    return path


if __name__ == "__main__":
    write_rules(load_config(FEEDS_FILE))
