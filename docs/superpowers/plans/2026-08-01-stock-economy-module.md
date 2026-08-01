# 股市与经济模块 · 整站按版面分离重构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有单文件 `fetch_news.py` 拆成模块化结构，新增市场与宏观版面（行情/宏观/公告/研报四类），整站重构为 ai/world/market 三大 section + 首页今日总览。

**Architecture:** `scripts/common.py` 承载纯函数与共享工具；`scripts/sources/` 负责数据抓取（rss/eastmoney/jin10/cninfo），每个抓取器独立降级；`scripts/generators/` 负责各版面生成（ai/world/market）；`scripts/fetch_news.py` 为主入口，编排三生成器 + 首页。Hugo 用 section 实现版面分离，首页 `_index.md` 由脚本生成。

**Tech Stack:** Python 3.12、feedparser、requests、beautifulsoup4+lxml、openai(DeepSeek)、PyYAML、pytest；Hugo 0.148 + PaperMod。

**设计规格：** `docs/superpowers/specs/2026-08-01-stock-economy-module-design.md`

---

## 文件结构总览

| 文件 | 职责 | 状态 |
|---|---|---|
| `scripts/common.py` | 纯函数 + seen + LLM 客户端 + 渲染工具，三版面共用 | 新建 |
| `scripts/sources/__init__.py` | 包标识 | 新建 |
| `scripts/sources/rss.py` | RSS 抓取（fetch_feed/fetch_candidates/matches_keywords） | 新建（从 fetch_news.py 抽出） |
| `scripts/sources/eastmoney.py` | 东方财富行情接口 | 新建 |
| `scripts/sources/jin10.py` | 金十宏观日历页面 | 新建 |
| `scripts/sources/cninfo.py` | 巨潮公告列表 | 新建 |
| `scripts/generators/__init__.py` | 包标识 | 新建 |
| `scripts/generators/ai.py` | AI 与科技社区版面生成 | 新建 |
| `scripts/generators/world.py` | 国际与深度版面生成 | 新建 |
| `scripts/generators/market.py` | 市场与宏观版面生成 | 新建 |
| `scripts/homepage.py` | 首页今日总览生成 | 新建 |
| `scripts/fetch_news.py` | 主入口，编排三生成器 + 首页 | 重写 |
| `scripts/feeds.yaml` | RSS 源清单，加 section 分组 + 财经/研报源 | 修改 |
| `scripts/migrate_posts.py` | 旧文章迁移到 ai/world section | 新建 |
| `scripts/requirements.txt` | 加 beautifulsoup4/lxml/pytest | 修改 |
| `hugo.toml` | 菜单 + section + 首页配置 | 修改 |
| `.github/workflows/daily.yml` | 适配多文章提交 | 修改 |
| `tests/` | 单测 + fixtures | 新建 |

---

## Task 1: 测试基础设施与 common.py 纯函数

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `scripts/common.py`
- Modify: `scripts/requirements.txt`

- [ ] **Step 1: 加测试依赖到 requirements.txt**

把 `scripts/requirements.txt` 改为：

```
feedparser>=6.0
requests>=2.31
PyYAML>=6.0
python-dateutil>=2.8
openai>=1.30
beautifulsoup4>=4.12
lxml>=5.0
pytest>=8.0
```

- [ ] **Step 2: 建 tests 包与 conftest**

`tests/__init__.py`（空文件）：

```python
```

`tests/conftest.py`：

```python
import sys
from pathlib import Path

# 让 tests 能 import scripts 下的模块
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
```

- [ ] **Step 3: 写 common.py 纯函数的失败测试**

`tests/test_common_pure.py`：

```python
from datetime import datetime, timezone, timedelta
from common import link_hash, strip_html, entry_time, matches_keywords


def test_link_hash_stable():
    assert link_hash("https://example.com/a") == link_hash("https://example.com/a")
    assert link_hash("https://example.com/a") != link_hash("https://example.com/b")


def test_strip_html_removes_tags_and_unescapes():
    assert strip_html("<p>Hello &amp; <b>world</b></p>") == "Hello & world"


def test_strip_html_collapses_whitespace():
    assert strip_html("  a\n\nb  ") == "a b"


def test_entry_time_parses_published():
    entry = {"published": "Wed, 30 Jul 2026 10:00:00 GMT"}
    dt = entry_time(entry)
    assert dt is not None
    assert dt.year == 2026 and dt.month == 7


def test_entry_time_returns_none_when_no_dates():
    assert entry_time({}) is None


def test_matches_keywords_short_word_boundary():
    # "AI" 不能误匹配 "aid"
    entry = {"title": "Healthcare aid program", "summary": ""}
    assert not matches_keywords(entry, ["AI"])
    entry = {"title": "New AI model released", "summary": ""}
    assert matches_keywords(entry, ["AI"])


def test_matches_keywords_long_substring():
    entry = {"title": "OpenAI announces GPT", "summary": ""}
    assert matches_keywords(entry, ["OpenAI", "transformer"])
```

- [ ] **Step 4: 运行测试验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_common_pure.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'common'`）

- [ ] **Step 5: 创建 common.py，迁移纯函数**

`scripts/common.py`（先放纯函数，后续 task 补充 seen/LLM/渲染）：

```python
"""共享工具：纯函数、seen.json、LLM 客户端、渲染工具。三版面共用。"""

import hashlib
import html
import re
from datetime import datetime, timedelta, timezone

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
```

- [ ] **Step 6: 运行测试验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_common_pure.py -v`
Expected: 7 passed

- [ ] **Step 7: 提交**

```bash
git add scripts/common.py scripts/requirements.txt tests/
git commit -m "feat: add common.py pure utils with tests"
```

---

## Task 2: common.py 的 seen.json 与 LLM 客户端

**Files:**
- Modify: `scripts/common.py`
- Create: `tests/test_common_seen.py`

- [ ] **Step 1: 写 seen 与 LLM 客户端的失败测试**

`tests/test_common_seen.py`：

```python
import json
from pathlib import Path

from common import load_seen, save_seen


def test_load_seen_returns_empty_when_missing(tmp_path):
    assert load_seen(tmp_path / "nope.json") == {}


def test_save_then_load_roundtrip(tmp_path):
    seen_file = tmp_path / "seen.json"
    save_seen(seen_file, {"abc": "2026-08-01T00:00:00+00:00"})
    loaded = load_seen(seen_file)
    assert loaded["abc"] == "2026-08-01T00:00:00+00:00"


def test_save_seen_prunes_old_entries(tmp_path):
    from datetime import datetime, timezone, timedelta
    seen_file = tmp_path / "seen.json"
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    recent = datetime.now(timezone.utc).isoformat()
    save_seen(seen_file, {"old": old, "new": recent})
    loaded = load_seen(seen_file)
    assert "new" in loaded
    assert "old" not in loaded


def test_save_seen_creates_parent_dir(tmp_path):
    seen_file = tmp_path / "sub" / "dir" / "seen.json"
    save_seen(seen_file, {"x": "2026-08-01T00:00:00+00:00"})
    assert seen_file.exists()
```

- [ ] **Step 2: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_common_seen.py -v`
Expected: FAIL（`ImportError: cannot import name 'load_seen'`）

- [ ] **Step 3: 在 common.py 末尾追加 seen 与 LLM 客户端**

在 `scripts/common.py` 顶部 import 区加 `import json, os`，并在文件末尾追加：

```python
import json
import os
import sys
import time
from pathlib import Path

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
```

- [ ] **Step 4: 运行验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_common_seen.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add scripts/common.py tests/test_common_seen.py
git commit -m "feat: add seen.json and LLM client to common"
```

---

## Task 3: sources/rss.py — RSS 抓取

**Files:**
- Create: `scripts/sources/__init__.py`
- Create: `scripts/sources/rss.py`
- Create: `tests/test_rss_source.py`

- [ ] **Step 1: 建 sources 包**

`scripts/sources/__init__.py`（空文件）：

```python
```

- [ ] **Step 2: 写 rss 抓取的失败测试（mock requests）**

`tests/test_rss_source.py`：

```python
from unittest.mock import patch, MagicMock

from sources import rss


SAMPLE_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Test</title>
<item>
  <title>News A</title>
  <link>https://example.com/a</link>
  <description>hello</description>
  <pubDate>Wed, 30 Jul 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title>News B</title>
  <link>https://example.com/b</link>
  <description>ai ai ai</description>
  <pubDate>Wed, 30 Jul 2026 11:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def _mock_resp(content):
    resp = MagicMock()
    resp.status_code = 200
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


def test_fetch_feed_parses_rss():
    with patch("sources.rss.requests.get", return_value=_mock_resp(SAMPLE_RSS)):
        parsed = rss.fetch_feed("https://x")
    assert parsed is not None
    assert len(parsed.entries) == 2


def test_fetch_feed_returns_none_on_failure():
    with patch("sources.rss.requests.get", side_effect=Exception("boom")):
        assert rss.fetch_feed("https://x") is None


def test_fetch_candidates_filters_by_keywords_and_dedup():
    # hours_window 设极大值，避免固定 pubDate 随运行日期被时间窗口过滤
    config = {
        "settings": {"hours_window": 876000},
        "ai_keywords": ["ai"],
        "feeds": [
            {"name": "T", "url": "https://x", "category": "AI 动态",
             "ai_filter": True, "max_items": 10, "section": "ai"},
        ],
    }
    seen = {}
    with patch("sources.rss.requests.get", return_value=_mock_resp(SAMPLE_RSS)):
        cands = rss.fetch_candidates(config, seen)
    # 只有 News B 含 "ai" 关键词通过过滤
    assert len(cands) == 1
    assert cands[0]["title"] == "News B"
    assert cands[0]["section"] == "ai"
```

- [ ] **Step 3: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_rss_source.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'sources.rss'`）

- [ ] **Step 4: 创建 sources/rss.py**

`scripts/sources/rss.py`：

```python
"""RSS 抓取：fetch_feed / fetch_candidates / matches_keywords。

从原 fetch_news.py 抽出，三版面共用。支持 feeds 项里的 section 字段。
"""

import re
import sys
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from common import link_hash, strip_html, entry_time, matches_keywords


def fetch_feed(url, retries=3):
    """抓取并解析 RSS，对 429 限流做指数退避重试。失败返回 None。"""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; news_auto/1.0)"}
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"[warn] 429 rate limited, retry in {wait}s: {url}", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return feedparser.parse(resp.content)
        except Exception as exc:
            print(f"[warn] fetch error ({exc}), attempt {attempt + 1}: {url}", file=sys.stderr)
            time.sleep(5)
    return None


def fetch_candidates(config, seen):
    """按 feeds.yaml 配置抓取所有源，返回候选条目列表（已去重+过滤）。"""
    settings = config.get("settings", {})
    hours_window = settings.get("hours_window", 36)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_window)
    keywords = config.get("ai_keywords", [])

    candidates = []
    run_seen = set()  # 本次运行内去重
    for feed_idx, feed_cfg in enumerate(config.get("feeds", [])):
        name = feed_cfg["name"]
        if feed_idx > 0:
            time.sleep(2)  # 部分站点对连续请求限流
        print(f"[fetch] {name} ...", flush=True)
        parsed = fetch_feed(feed_cfg["url"])
        if parsed is None:
            print(f"[warn] {name} fetch failed, skipped", file=sys.stderr)
            continue

        count = 0
        for entry in parsed.entries:
            if count >= feed_cfg.get("max_items", 10):
                break
            link = entry.get("link")
            title = (entry.get("title") or "").strip()
            if not link or not title:
                continue
            ts = entry_time(entry)
            if ts and ts < cutoff:
                continue
            h = link_hash(link)
            if h in seen or h in run_seen:
                continue
            run_seen.add(h)
            if feed_cfg.get("ai_filter") and not matches_keywords(entry, keywords):
                continue
            candidates.append(
                {
                    "title": title,
                    "link": link,
                    "summary": strip_html(entry.get("summary", ""))[:600],
                    "source": name,
                    "category": feed_cfg.get("category", "资讯"),
                    "section": feed_cfg.get("section", "ai"),
                    "time": ts or datetime.now(timezone.utc),
                }
            )
            count += 1
        print(f"[fetch] {name}: {count} new items", flush=True)
    return candidates
```

- [ ] **Step 5: 运行验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_rss_source.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add scripts/sources/ tests/test_rss_source.py
git commit -m "feat: add sources/rss.py with tests"
```

---

## Task 4: common.py 的 LLM 排序/摘要/渲染工具

**Files:**
- Modify: `scripts/common.py`
- Create: `tests/test_common_llm_render.py`

- [ ] **Step 1: 写 LLM 与渲染的失败测试（mock LLM client）**

`tests/test_common_llm_render.py`：

```python
from unittest.mock import MagicMock

from common import summarize, rank_and_select, select_deep, render_item, render_sectioned


def _client_returning(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = resp
    return client


def test_summarize_returns_zh_fields():
    client = _client_returning('{"title_zh": "中文标题", "summary_zh": "中文摘要"}')
    out = summarize(client, {"title": "x", "summary": "y"})
    assert out == {"title_zh": "中文标题", "summary_zh": "中文摘要"}


def test_summarize_returns_none_on_bad_json():
    client = _client_returning("not json")
    assert summarize(client, {"title": "x", "summary": "y"}) is None


def test_summarize_returns_none_when_no_client():
    assert summarize(None, {"title": "x", "summary": "y"}) is None


def test_rank_and_select_uses_llm_indices():
    cands = [
        {"title": f"t{i}", "link": f"l{i}", "summary": "s", "source": "S",
         "category": "AI 动态", "time": None} for i in range(5)
    ]
    client = _client_returning('{"selected": [{"index": 2, "score": 9}, {"index": 0, "score": 7}]}')
    picked = rank_and_select(client, cands, {"settings": {"total_limit": 2}})
    assert len(picked) == 2
    assert picked[0]["score"] == 9
    assert picked[0]["title"] == "t2"


def test_rank_and_select_fallback_when_no_client():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    cands = [
        {"title": f"t{i}", "link": f"l{i}", "summary": "s", "source": "S",
         "category": "AI 动态", "time": now} for i in range(5)
    ]
    picked = rank_and_select(None, cands, {"settings": {"total_limit": 2, "per_source_limit": 4}})
    assert len(picked) == 2


def test_select_deep_balances_sources():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    cands = [
        {"title": "a1", "source": "A", "category": "深度精选", "time": now},
        {"title": "a2", "source": "A", "category": "深度精选", "time": now},
        {"title": "b1", "source": "B", "category": "深度精选", "time": now},
    ]
    picked = select_deep(cands, {"settings": {"deep_limit": 3, "deep_per_source_limit": 1}})
    sources = [p["source"] for p in picked]
    assert sources.count("A") == 1
    assert sources.count("B") == 1


def test_render_item_with_zh_title():
    item = {"title_zh": "中文", "title": "Eng", "summary_zh": "摘要", "source": "S", "link": "https://x"}
    block = render_item(item, 1)
    assert "1. 中文" in block[0]
    assert "> Eng" in block
    assert "来源：[S](https://x)" in block


def test_render_item_highlights_high_score():
    item = {"title": "Eng", "summary": "s", "source": "S", "link": "https://x", "score": 9}
    block = render_item(item, 1)
    assert "【重点】" in block[0]


def test_render_sectioned_has_focus_and_categories():
    # 3 条目、focus_count=1：1 条进焦点区，2 条进分类区，两个分类标题都会出现
    items = [
        {"title_zh": "焦点", "title": "e1", "summary_zh": "s", "source": "S", "link": "l1",
         "category": "国际新闻", "score": 9},
        {"title_zh": "AI条", "title": "e2", "summary_zh": "s", "source": "S", "link": "l2",
         "category": "AI 动态", "score": 5},
        {"title_zh": "社区条", "title": "e3", "summary_zh": "s", "source": "S", "link": "l3",
         "category": "社区热点", "score": 3},
    ]
    out = render_sectioned(items, "每日资讯 2026-08-01", summary="今日 3 条", focus_count=1)
    assert "今日焦点" in out
    assert "AI 动态" in out
    assert "社区热点" in out
```

- [ ] **Step 2: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_common_llm_render.py -v`
Expected: FAIL（`ImportError: cannot import name 'summarize'`）

- [ ] **Step 3: 在 common.py 追加 LLM 排序/摘要/渲染函数**

在 `scripts/common.py` 末尾追加：

```python
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
```

- [ ] **Step 4: 运行验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_common_llm_render.py -v`
Expected: 9 passed

- [ ] **Step 5: 提交**

```bash
git add scripts/common.py tests/test_common_llm_render.py
git commit -m "feat: add LLM rank/summarize/render to common"
```

---

## Task 5: feeds.yaml 加 section 分组与财经/研报源

**Files:**
- Modify: `scripts/feeds.yaml`

- [ ] **Step 1: 重写 feeds.yaml，加 section 字段与新增源**

`scripts/feeds.yaml`（完整替换）：

```yaml
# RSS 源清单
# section: 归属版面（ai / world / market）
# category: 展示分类
# ai_filter: true 时按 ai_keywords 关键词过滤条目
# max_items: 单个源最多取多少条候选

settings:
  total_limit: 15          # 每版面每日最多精选条数
  per_source_limit: 4      # 单来源最多入选条数
  hours_window: 36         # 只取最近 N 小时内发布的条目
  deep_limit: 6            # 「深度精选」每日最多条数（world 版面）
  deep_per_source_limit: 2 # 「深度精选」单来源最多条数

feeds:
  # ---------- AI 与科技社区（section: ai） ----------
  - name: TechCrunch AI
    url: https://techcrunch.com/category/artificial-intelligence/feed/
    section: ai
    category: AI 动态
    ai_filter: false
    max_items: 10

  - name: The Verge AI
    url: https://www.theverge.com/rss/ai-artificial-intelligence/index.xml
    section: ai
    category: AI 动态
    ai_filter: false
    max_items: 10

  - name: VentureBeat AI
    url: https://venturebeat.com/category/ai/feed/
    section: ai
    category: AI 动态
    ai_filter: false
    max_items: 8

  - name: Hacker News Frontpage
    url: https://hnrss.org/frontpage
    section: ai
    category: AI 动态
    ai_filter: true
    max_items: 20

  - name: Hacker News Best
    url: https://hnrss.org/best
    section: ai
    category: 社区热点
    ai_filter: false
    max_items: 15

  - name: Reddit r/singularity Top
    url: https://www.reddit.com/r/singularity/top/.rss?t=day
    section: ai
    category: 社区热点
    ai_filter: false
    max_items: 10

  - name: Reddit r/OpenAI Top
    url: https://www.reddit.com/r/OpenAI/top/.rss?t=day
    section: ai
    category: 社区热点
    ai_filter: false
    max_items: 8

  - name: Reddit r/LocalLLaMA Top
    url: https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day
    section: ai
    category: 社区热点
    ai_filter: false
    max_items: 8

  - name: MIT Technology Review AI
    url: https://www.technologyreview.com/topic/artificial-intelligence/feed
    section: ai
    category: AI 动态
    ai_filter: false
    max_items: 6

  # ---------- 国际与深度（section: world） ----------
  - name: BBC World
    url: https://feeds.bbci.co.uk/news/world/rss.xml
    section: world
    category: 国际新闻
    ai_filter: false
    max_items: 10

  - name: The Guardian World
    url: https://www.theguardian.com/world/rss
    section: world
    category: 国际新闻
    ai_filter: false
    max_items: 10

  - name: Reuters World (via Google News)
    url: https://news.google.com/rss/search?q=site:reuters.com%20world&hl=en-US&gl=US&ceid=US:en
    section: world
    category: 国际新闻
    ai_filter: false
    max_items: 8

  - name: The Economist Latest
    url: https://www.economist.com/latest/rss.xml
    section: world
    category: 深度精选
    ai_filter: false
    max_items: 8

  - name: The Economist Science & Tech
    url: https://www.economist.com/science-and-technology/rss.xml
    section: world
    category: 深度精选
    ai_filter: false
    max_items: 6

  - name: The Guardian Long Read
    url: https://www.theguardian.com/news/series/the-long-read/rss
    section: world
    category: 深度精选
    ai_filter: false
    max_items: 6

  - name: Scientific American
    url: https://www.scientificamerican.com/platform/syndication/rss/
    section: world
    category: 深度精选
    ai_filter: false
    max_items: 8

  # ---------- 市场与宏观 · 财经要闻（section: market） ----------
  # 走 RSS 的财经要闻源（这些站点的可用 RSS；不可用则由抓取失败占位）
  - name: 第一财经要闻
    url: https://rsshub.app/yicai/news
    section: market
    category: 财经要闻
    ai_filter: false
    max_items: 10

  - name: 财新财经
    url: https://rsshub.app/caixin/latest
    section: market
    category: 财经要闻
    ai_filter: false
    max_items: 10

  - name: 华尔街见闻
    url: https://rsshub.app/wallstreetcn/news/global
    section: market
    category: 财经要闻
    ai_filter: false
    max_items: 10

  # ---------- 市场与宏观 · 研报（section: market, 走 RSS 聚合） ----------
  - name: 慧博研报精选
    url: https://rsshub.app/hibor/report
    section: market
    category: 研报要点
    ai_filter: false
    max_items: 6

# AI 关键词（仅对 ai_filter: true 的源生效，不区分大小写）
ai_keywords:
  - AI
  - A.I.
  - artificial intelligence
  - machine learning
  - deep learning
  - neural
  - LLM
  - GPT
  - OpenAI
  - Anthropic
  - Claude
  - Gemini
  - DeepSeek
  - Llama
  - Mistral
  - transformer
  - diffusion model
  - AGI
  - chatbot
  - copilot
```

> 说明：财经要闻/研报的 RSS 用 RSSHub 公开路由（`rsshub.app`）。若某路由不可用，rss.fetch_candidates 会跳过该源并打印 warn，不阻塞市场版面其他子板块。

- [ ] **Step 2: 验证配置可加载**

Run: `cd /mnt/d/project/github/news_auto && python -c "import yaml; c=yaml.safe_load(open('scripts/feeds.yaml')); print(len(c['feeds']), 'feeds'); print(set(f['section'] for f in c['feeds']))"`
Expected: 输出 `20 feeds` 和 `{'ai', 'world', 'market'}`

- [ ] **Step 3: 提交**

```bash
git add scripts/feeds.yaml
git commit -m "feat: add section grouping and finance/research feeds"
```

---

## Task 6: generators/ai.py — AI 与科技社区版面

**Files:**
- Create: `scripts/generators/__init__.py`
- Create: `scripts/generators/ai.py`
- Create: `tests/test_gen_ai.py`

- [ ] **Step 1: 建 generators 包**

`scripts/generators/__init__.py`（空文件）：

```python
```

- [ ] **Step 2: 写 ai 生成器失败测试（mock rss + LLM）**

`tests/test_gen_ai.py`：

```python
from unittest.mock import patch, MagicMock

from generators import ai


def _client_returning(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = resp
    return client


def test_generate_writes_sectioned_post(tmp_path):
    config = {
        "settings": {"total_limit": 5, "per_source_limit": 4, "hours_window": 240, "deep_limit": 6, "deep_per_source_limit": 2},
        "ai_keywords": ["ai"],
        "feeds": [{"name": "T", "url": "https://x", "section": "ai", "category": "AI 动态", "ai_filter": False, "max_items": 10}],
    }
    candidates = [
        {"title": "AI news", "link": "https://e/1", "summary": "s", "source": "T",
         "category": "AI 动态", "section": "ai", "time": None},
    ]
    client = _client_returning('{"selected": [{"index": 0, "score": 9}]}')

    with patch("generators.ai.rss.fetch_candidates", return_value=candidates), \
         patch("generators.ai.summarize", return_value={"title_zh": "中文", "summary_zh": "摘要"}):
        path = ai.generate(config, {}, client, date_str="2026-08-01", posts_dir=tmp_path)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "title:" in text
    assert "今日焦点" in text


def test_generate_empty_candidates_skips(tmp_path):
    config = {"settings": {}, "ai_keywords": [], "feeds": []}
    with patch("generators.ai.rss.fetch_candidates", return_value=[]):
        path = ai.generate(config, {}, None, date_str="2026-08-01", posts_dir=tmp_path)
    assert path is None
```

- [ ] **Step 3: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_gen_ai.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'generators.ai'`）

- [ ] **Step 4: 创建 generators/ai.py**

`scripts/generators/ai.py`：

```python
"""AI 与科技社区版面生成器。

从 feeds.yaml 拉取 section=ai 的 RSS 候选，LLM 排序 + 摘要，渲染为
content/ai/YYYY-MM-DD.md。
"""

import sys
from pathlib import Path

from common import rank_and_select, summarize, render_sectioned
from sources import rss


def generate(config, seen, client, date_str, posts_dir=None):
    """生成 AI 版面文章。无候选时返回 None。"""
    ai_config = _filter_section(config, "ai")
    candidates = rss.fetch_candidates(ai_config, seen)
    if not candidates:
        print("[info] AI 版面无新条目，跳过")
        return None

    selected = rank_and_select(client, candidates, config)

    ok = 0
    for item in selected:
        result = summarize(client, item)
        if result:
            item.update(result)
            ok += 1

    if client is not None and ok == 0 and selected:
        print("[error] AI 版面 LLM 全失败，跳过发布", file=sys.stderr)
        return None

    posts_dir = Path(posts_dir) if posts_dir else Path("content/ai")
    posts_dir.mkdir(parents=True, exist_ok=True)
    path = posts_dir / f"{date_str}.md"
    path.write_text(
        render_sectioned(selected, f"AI 与科技社区 {date_str}", f"今日 {len(selected)} 条 AI 动态与社区热点。"),
        encoding="utf-8",
    )
    print(f"[info] AI 版面已生成 {path}")
    # 返回焦点条目供首页用
    return {"path": path, "items": selected}


def _filter_section(config, section):
    """返回只含指定 section feeds 的 config 副本。"""
    return {
        "settings": config.get("settings", {}),
        "ai_keywords": config.get("ai_keywords", []),
        "feeds": [f for f in config.get("feeds", []) if f.get("section") == section],
    }
```

- [ ] **Step 5: 运行验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_gen_ai.py -v`
Expected: 2 passed

- [ ] **Step 6: 提交**

```bash
git add scripts/generators/ tests/test_gen_ai.py
git commit -m "feat: add ai section generator"
```

---

## Task 7: generators/world.py — 国际与深度版面

**Files:**
- Create: `scripts/generators/world.py`
- Create: `tests/test_gen_world.py`

- [ ] **Step 1: 写 world 生成器失败测试**

`tests/test_gen_world.py`：

```python
from unittest.mock import patch, MagicMock

from generators import world
from common import DEEP_CATEGORY


def _client(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = resp
    return client


def test_generate_separates_deep_and_regular(tmp_path):
    config = {
        "settings": {"total_limit": 5, "per_source_limit": 4, "hours_window": 240,
                      "deep_limit": 6, "deep_per_source_limit": 2},
        "ai_keywords": [], "feeds": [],
    }
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    candidates = [
        {"title": "国际", "link": "l1", "summary": "s", "source": "BBC",
         "category": "国际新闻", "section": "world", "time": now},
        {"title": "深度", "link": "l2", "summary": "s", "source": "Economist",
         "category": DEEP_CATEGORY, "section": "world", "time": now},
    ]
    # patch rank_and_select 直接返回常规条目（不打分），让 render 走无-score 分支，
    # 这样「国际新闻」「深度精选」分类标题才会出现。
    with patch("generators.world.rss.fetch_candidates", return_value=candidates), \
         patch("generators.world.rank_and_select", side_effect=lambda c, cs, cfg: [x for x in cs]), \
         patch("generators.world.summarize", return_value={"title_zh": "中", "summary_zh": "摘"}):
        path = world.generate(config, {}, None, date_str="2026-08-01", posts_dir=tmp_path)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "国际新闻" in text
    assert "深度精选" in text


def test_generate_empty_skips(tmp_path):
    with patch("generators.world.rss.fetch_candidates", return_value=[]):
        path = world.generate({"settings": {}, "ai_keywords": [], "feeds": []}, {}, None, "2026-08-01", tmp_path)
    assert path is None
```

- [ ] **Step 2: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_gen_world.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'generators.world'`）

- [ ] **Step 3: 创建 generators/world.py**

`scripts/generators/world.py`：

```python
"""国际与深度版面生成器。

国际新闻走 LLM 排序，深度精选走来源均衡（select_deep），二者合并渲染。
"""

import sys
from pathlib import Path

from common import rank_and_select, select_deep, summarize, render_sectioned, DEEP_CATEGORY
from sources import rss


def generate(config, seen, client, date_str, posts_dir=None):
    world_config = _filter_section(config, "world")
    candidates = rss.fetch_candidates(world_config, seen)
    if not candidates:
        print("[info] 国际版面无新条目，跳过")
        return None

    deep_candidates = [c for c in candidates if c["category"] == DEEP_CATEGORY]
    regular_candidates = [c for c in candidates if c["category"] != DEEP_CATEGORY]

    selected = rank_and_select(client, regular_candidates, config)
    deep_selected = select_deep(deep_candidates, config)
    selected.extend(deep_selected)

    ok = 0
    for item in selected:
        result = summarize(client, item)
        if result:
            item.update(result)
            ok += 1

    if client is not None and ok == 0 and selected:
        print("[error] 国际版面 LLM 全失败，跳过发布", file=sys.stderr)
        return None

    posts_dir = Path(posts_dir) if posts_dir else Path("content/world")
    posts_dir.mkdir(parents=True, exist_ok=True)
    path = posts_dir / f"{date_str}.md"
    path.write_text(
        render_sectioned(selected, f"国际与深度 {date_str}", f"今日 {len(selected)} 条国际新闻与深度报道。"),
        encoding="utf-8",
    )
    print(f"[info] 国际版面已生成 {path}")
    return {"path": path, "items": selected}


def _filter_section(config, section):
    return {
        "settings": config.get("settings", {}),
        "ai_keywords": config.get("ai_keywords", []),
        "feeds": [f for f in config.get("feeds", []) if f.get("section") == section],
    }
```

- [ ] **Step 4: 运行验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_gen_world.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add scripts/generators/world.py tests/test_gen_world.py
git commit -m "feat: add world section generator"
```

---

## Task 8: sources/eastmoney.py — 行情速览

**Files:**
- Create: `scripts/sources/eastmoney.py`
- Create: `tests/fixtures/eastmoney_sh.json`
- Create: `tests/test_eastmoney.py`

- [ ] **Step 1: 获取真实响应作为 fixture**

A股已验证可用。抓取并保存样本：

```bash
mkdir -p tests/fixtures
curl -s --max-time 25 "https://push2.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f43,f44,f45,f46,f47,f48,f170,f58" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://quote.eastmoney.com/" \
  -o tests/fixtures/eastmoney_sh.json
# 验证非空
cat tests/fixtures/eastmoney_sh.json
```

Expected: 一行 JSON，含 `{"rc":0,"data":{"f43":...,"f170":...,"f58":"上证指数"}}`。若抓取失败（HTTP 000），重试 2-3 次；持续失败则手工写入下面的最小样本：

```json
{"rc":0,"rt":4,"data":{"f43":383226,"f44":384709,"f45":382237,"f46":383354,"f47":597529427,"f48":1187681546393.3,"f170":72,"f58":"上证指数"}}
```

- [ ] **Step 2: 写 eastmoney 解析失败测试**

`tests/test_eastmoney.py`：

```python
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from sources import eastmoney

FIX = Path(__file__).parent / "fixtures" / "eastmoney_sh.json"


def _mock_resp(content):
    resp = MagicMock()
    resp.status_code = 200
    resp.content = content.encode() if isinstance(content, str) else content
    resp.raise_for_status = MagicMock()
    return resp


def test_parse_sh_index():
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    item = eastmoney._parse_one(raw, "上证指数")
    assert item["name"] == "上证指数"
    assert item["price"] == 3832.26  # f43/100
    assert item["change_pct"] == 0.72  # f170/100
    assert item["amount"] == 1187681546393.3  # f48 成交额


def test_fetch_quotes_returns_list(monkeypatch):
    # 用 fixture 替代网络
    raw = FIX.read_bytes()
    monkeypatch.setattr(eastmoney, "fetch_feed_json", lambda url: json.loads(raw))
    quotes = eastmoney.fetch_quotes()
    assert isinstance(quotes, list)
    assert quotes[0]["price"] > 0


def test_fetch_quotes_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(eastmoney, "fetch_feed_json", lambda url: None)
    assert eastmoney.fetch_quotes() is None


def test_fetch_quotes_partial_failure(monkeypatch):
    # 上证成功，其余失败：部分成功应返回只含成功的列表，不整体失败
    raw = json.loads(FIX.read_bytes())

    def fake_json(url):
        if "1.000001" in url:  # 上证 secid
            return raw
        return None

    monkeypatch.setattr(eastmoney, "fetch_feed_json", fake_json)
    quotes = eastmoney.fetch_quotes()
    assert isinstance(quotes, list)
    assert len(quotes) == 1
    assert quotes[0]["name"] == "上证指数"
```

- [ ] **Step 3: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_eastmoney.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'sources.eastmoney'`）

- [ ] **Step 4: 创建 sources/eastmoney.py**

`scripts/sources/eastmoney.py`：

```python
"""东方财富 push2 行情接口。

字段：f43=最新价(*100), f44=最高, f45=最低, f46=今开, f47=成交量, f48=成交额, f170=涨跌幅(*100), f58=名称。

A股已验证 secid：1.000001(上证) 0.399001(深证) 0.399006(创业板)
海外指数 secid 待 fixture 确认；若某 secid 返回 data:null 则跳过（降级）。
"""

import sys
import time

import requests

# 行情清单：name -> secid
QUOTES = [
    ("上证指数", "1.000001"),
    ("深证成指", "0.399001"),
    ("创业板指", "0.399006"),
    ("恒生指数", "100.HSI"),
    ("恒生科技", "100.HSTECH"),
    ("标普500", "100.SPX"),
    ("纳斯达克", "100.NDX"),
    ("道琼斯", "100.DJIA"),
    ("黄金", "122.XAU"),
    ("原油", "122.SC0"),
    ("VIX", "100.VIX"),
]

FIELDS = "f43,f44,f45,f46,f47,f48,f170,f58"
URL_TMPL = "https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=" + FIELDS


def fetch_feed_json(url, retries=3):
    """抓取单条行情 JSON。失败返回 None。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; news_auto/1.0)",
        "Referer": "https://quote.eastmoney.com/",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[warn] eastmoney fetch error ({exc}), attempt {attempt+1}: {url}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def _parse_one(raw, fallback_name):
    """解析单条行情 JSON 为展示字典。"""
    if not raw or raw.get("rc") != 0:
        return None
    data = raw.get("data") or {}
    if not data:
        return None
    return {
        "name": data.get("f58") or fallback_name,
        "price": (data.get("f43") or 0) / 100,
        "change_pct": (data.get("f170") or 0) / 100,
        "amount": data.get("f48"),
    }


def fetch_quotes():
    """抓取全部行情。全部失败返回 None；部分失败返回已成功的列表。"""
    out = []
    for name, secid in QUOTES:
        raw = fetch_feed_json(URL_TMPL.format(secid=secid))
        item = _parse_one(raw, name)
        if item:
            out.append(item)
        else:
            print(f"[warn] {name} 行情获取失败，跳过", file=sys.stderr)
    return out if out else None
```

- [ ] **Step 5: 运行验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_eastmoney.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
git add scripts/sources/eastmoney.py tests/fixtures/eastmoney_sh.json tests/test_eastmoney.py
git commit -m "feat: add eastmoney quotes source with fixtures"
```

---

## Task 9: sources/jin10.py — 宏观日历

**Files:**
- Create: `tests/fixtures/jin10_calendar.html`
- Create: `scripts/sources/jin10.py`
- Create: `tests/test_jin10.py`

- [ ] **Step 1: 获取金十日历页面 fixture**

金十经济日历通过前端 JS 加载，直接 HTML 抓取拿不到结构化数据。改用其公开 JSON 接口：

```bash
curl -s --max-time 25 "https://flash-api.jin10.com/get_econ_calendar" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://www.jin10.com/" \
  -o tests/fixtures/jin10_calendar.json
head -c 800 tests/fixtures/jin10_calendar.json; echo
```

若该接口不可用（HTTP 4xx 或空），则金十日历降级为占位——抓取器返回 `None` 即可，不影响其他子板块。fixture 用最小样本：

```bash
cat > tests/fixtures/jin10_calendar.json <<'EOF'
[{"country":"中国","current_actual":"49.4","previous":"49.5","consensus":"49.5","title":"7月制造业PMI","pub_time":"2026-07-31T09:00:00+08:00"}]
EOF
```

- [ ] **Step 2: 写 jin10 解析失败测试**

`tests/test_jin10.py`：

```python
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from sources import jin10

FIX = Path(__file__).parent / "fixtures" / "jin10_calendar.json"


def test_parse_calendar_filters_today(monkeypatch):
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: raw)
    items = jin10.fetch_calendar(date(2026, 7, 31))
    assert len(items) >= 1
    assert items[0]["title"] == "7月制造业PMI"
    assert items[0]["actual"] == "49.4"


def test_fetch_calendar_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: None)
    assert jin10.fetch_calendar(date(2026, 7, 31)) is None


def test_fetch_calendar_empty_returns_empty_list(monkeypatch):
    monkeypatch.setattr(jin10, "fetch_calendar_json", lambda: [])
    assert jin10.fetch_calendar(date(2026, 7, 31)) == []
```

- [ ] **Step 3: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_jin10.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'sources.jin10'`）

- [ ] **Step 4: 创建 sources/jin10.py**

`scripts/sources/jin10.py`：

```python
"""金十宏观经济日历。走 flash-api JSON 接口。失败返回 None（降级占位）。"""

import sys
import time
from datetime import datetime

import requests


URL = "https://flash-api.jin10.com/get_econ_calendar"


def fetch_calendar_json(retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; news_auto/1.0)",
        "Referer": "https://www.jin10.com/",
        "x-app-id": "SO1EJGPM1L",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(URL, headers=headers, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[warn] jin10 fetch error ({exc}), attempt {attempt+1}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def fetch_calendar(today):
    """返回当日公布的数据项列表。无数据返回空列表，抓取失败返回 None。"""
    raw = fetch_calendar_json()
    if raw is None:
        return None
    today_str = today.isoformat()
    out = []
    for item in raw or []:
        pub = item.get("pub_time") or item.get("publication_time") or ""
        if not pub.startswith(today_str):
            continue
        out.append({
            "title": item.get("title") or item.get("event") or "",
            "actual": item.get("current_actual") or item.get("actual") or "",
            "previous": item.get("previous") or "",
            "consensus": item.get("consensus") or "",
            "country": item.get("country") or "",
        })
    return out
```

- [ ] **Step 5: 运行验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_jin10.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add scripts/sources/jin10.py tests/fixtures/jin10_calendar.json tests/test_jin10.py
git commit -m "feat: add jin10 macro calendar source"
```

---

## Task 10: sources/cninfo.py — 公告摘要

**Files:**
- Create: `tests/fixtures/cninfo_announcements.json`
- Create: `scripts/sources/cninfo.py`
- Create: `tests/test_cninfo.py`

- [ ] **Step 1: 获取巨潮公告 fixture**

已验证 POST API 可用：

```bash
curl -s --max-time 25 "http://www.cninfo.com.cn/new/hisAnnouncement/query" \
  -X POST -H "User-Agent: Mozilla/5.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "stock=&tabName=fulltext&pageSize=10&pageNum=1&column=szse&category=category_ndbg_szsh" \
  -o tests/fixtures/cninfo_announcements.json
head -c 600 tests/fixtures/cninfo_announcements.json; echo
```

Expected: 含 `announcements` 数组。若失败，写入最小样本：

```bash
cat > tests/fixtures/cninfo_announcements.json <<'EOF'
{"totalAnnouncement":1,"announcements":[{"secCode":"600641","secName":"先导基电","announcementTitle":"2025年年度报告","announcementTime":1785513600000,"adjunctUrl":"finalpage/2026-08-01/1225452105.PDF","adjunctType":"PDF"}]}
EOF
```

- [ ] **Step 2: 写 cninfo 解析失败测试**

`tests/test_cninfo.py`：

```python
import json
from pathlib import Path
from unittest.mock import patch

from sources import cninfo

FIX = Path(__file__).parent / "fixtures" / "cninfo_announcements.json"


def test_parse_announcements(monkeypatch):
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    monkeypatch.setattr(cninfo, "fetch_announcements_json", lambda **kw: raw)
    items = cninfo.fetch_announcements(limit=5)
    assert len(items) >= 1
    assert items[0]["sec_name"] == "先导基电"
    assert items[0]["title"] == "2025年年度报告"
    assert items[0]["url"].endswith(".PDF")


def test_fetch_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(cninfo, "fetch_announcements_json", lambda **kw: None)
    assert cninfo.fetch_announcements() is None


def test_fetch_respects_limit(monkeypatch):
    raw = {"announcements": [{"secName": f"c{i}", "announcementTitle": f"t{i}", "adjunctUrl": f"u{i}.PDF", "announcementTime": 1785513600000} for i in range(10)]}
    monkeypatch.setattr(cninfo, "fetch_announcements_json", lambda **kw: raw)
    items = cninfo.fetch_announcements(limit=3)
    assert len(items) == 3
```

- [ ] **Step 3: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_cninfo.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'sources.cninfo'`）

- [ ] **Step 4: 创建 sources/cninfo.py**

`scripts/sources/cninfo.py`：

```python
"""巨潮资讯网公告列表。走 POST hisAnnouncement/query 接口，取年报/重大事项。失败返回 None。"""

import sys
import time
from datetime import datetime, timezone

import requests

URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"

# category_ndbg_szsh = 年报；可按需扩展 category 为重大事项/停复牌


def fetch_announcements_json(limit=10, category="category_ndbg_szsh", retries=3):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; news_auto/1.0)",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "stock": "",
        "tabName": "fulltext",
        "pageSize": str(limit),
        "pageNum": "1",
        "column": "szse",
        "category": category,
    }
    for attempt in range(retries):
        try:
            resp = requests.post(URL, headers=headers, data=data, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[warn] cninfo fetch error ({exc}), attempt {attempt+1}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


def fetch_announcements(limit=10):
    """返回公告摘要列表。抓取失败返回 None。"""
    raw = fetch_announcements_json(limit=limit)
    if raw is None:
        return None
    out = []
    for a in (raw.get("announcements") or [])[:limit]:
        ts = a.get("announcementTime")
        pub = ""
        if isinstance(ts, (int, float)):
            pub = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append({
            "sec_code": a.get("secCode") or "",
            "sec_name": a.get("secName") or "",
            "title": a.get("announcementTitle") or "",
            "url": "http://www.cninfo.com.cn/" + (a.get("adjunctUrl") or ""),
            "pub_date": pub,
        })
    return out
```

- [ ] **Step 5: 运行验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_cninfo.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add scripts/sources/cninfo.py tests/fixtures/cninfo_announcements.json tests/test_cninfo.py
git commit -m "feat: add cninfo announcements source"
```

---

## Task 11: generators/market.py — 市场与宏观版面

**Files:**
- Create: `scripts/generators/market.py`
- Create: `tests/test_gen_market.py`

- [ ] **Step 1: 写市场生成器失败测试（mock 全部 source）**

`tests/test_gen_market.py`：

```python
from unittest.mock import patch, MagicMock

from generators import market


def _client(content):
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = resp
    return client


def test_generate_renders_all_four_blocks(tmp_path):
    from datetime import date
    config = {"settings": {"hours_window": 240, "total_limit": 5, "per_source_limit": 4},
              "ai_keywords": [], "feeds": [{"name": "T", "url": "x", "section": "market",
              "category": "财经要闻", "ai_filter": False, "max_items": 5}]}
    candidates = [{"title": "央行降准", "link": "l", "summary": "s", "source": "T",
                   "category": "财经要闻", "section": "market", "time": None}]
    quotes = [{"name": "上证指数", "price": 3225.43, "change_pct": 0.82, "amount": 8e11}]
    calendar = [{"title": "7月PMI", "actual": "49.4", "previous": "49.5", "consensus": "49.5", "country": "中国"}]
    announces = [{"sec_code": "600641", "sec_name": "先导基电", "title": "年报", "url": "http://x/a.PDF", "pub_date": "2026-08-01"}]

    with patch("generators.market.rss.fetch_candidates", return_value=candidates), \
         patch("generators.market.summarize", return_value={"title_zh": "央行降准", "summary_zh": "摘要"}), \
         patch("generators.market.eastmoney.fetch_quotes", return_value=quotes), \
         patch("generators.market.jin10.fetch_calendar", return_value=calendar), \
         patch("generators.market.cninfo.fetch_announcements", return_value=announces):
        path = market.generate(config, {}, _client('{}'), date_str="2026-08-01", posts_dir=tmp_path)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "行情速览" in text
    assert "上证指数" in text
    assert "宏观与政策" in text
    assert "7月PMI" in text
    assert "财经要闻" in text
    assert "公告" in text or "研报" in text


def test_generate_handles_source_failures(tmp_path):
    from datetime import date
    config = {"settings": {"hours_window": 240, "total_limit": 5, "per_source_limit": 4},
              "ai_keywords": [], "feeds": []}
    # 三个抓取源都失败返回 None，财经要闻也无
    with patch("generators.market.rss.fetch_candidates", return_value=[]), \
         patch("generators.market.eastmoney.fetch_quotes", return_value=None), \
         patch("generators.market.jin10.fetch_calendar", return_value=None), \
         patch("generators.market.cninfo.fetch_announcements", return_value=None):
        path = market.generate(config, {}, None, date_str="2026-08-01", posts_dir=tmp_path)
    # 全失败也应有占位文章
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "数据获取失败" in text
```

- [ ] **Step 2: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_gen_market.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'generators.market'`）

- [ ] **Step 3: 创建 generators/market.py**

`scripts/generators/market.py`：

```python
"""市场与宏观版面生成器。

四子板块：行情速览 / 宏观与政策 / 财经要闻 / 公告与研报。
各子板块独立 try/except，失败渲染占位块，不连坐。
行情/日历/公告不经 LLM；财经要闻/研报经 LLM 摘要。
"""

import sys
from datetime import date, datetime
from pathlib import Path

from common import summarize, CST
from sources import rss, eastmoney, jin10, cninfo

FAIL_BLOCK = "📊 数据获取失败，请稍后查看原文。"


def generate(config, seen, client, date_str, posts_dir=None):
    today = _parse_date(date_str)
    quotes = _safe(eastmoney.fetch_quotes, "行情速览")
    calendar = _safe(lambda: jin10.fetch_calendar(today), "宏观日历")
    announces = _safe(lambda: cninfo.fetch_announcements(limit=8), "公告")

    # 财经要闻 + 研报走 RSS
    market_config = _filter_section(config, "market")
    candidates = rss.fetch_candidates(market_config, seen)
    news_items, research_items = [], []
    for c in candidates:
        if c.get("category") == "研报要点":
            research_items.append(c)
        else:
            news_items.append(c)
    # 概览即可：财经要闻取前 8 条、研报取前 4 条（不做 LLM 重要性排序，省 token）
    news_items = news_items[:8]
    research_items = research_items[:4]

    for item in news_items + research_items:
        result = summarize(client, item)
        if result:
            item.update(result)

    posts_dir = Path(posts_dir) if posts_dir else Path("content/market")
    posts_dir.mkdir(parents=True, exist_ok=True)
    path = posts_dir / f"{date_str}.md"
    path.write_text(_render(date_str, quotes, calendar, announces, news_items, research_items),
                    encoding="utf-8")
    print(f"[info] 市场版面已生成 {path}")
    return {"path": path, "items": news_items, "quotes": quotes,
            "calendar": calendar, "news_items": news_items,
            "announces": announces,
            "all_rss_items": news_items + research_items}  # 用于 seen 去重


def _safe(fn, label):
    try:
        return fn()
    except Exception as exc:
        print(f"[warn] {label} 生成异常: {exc}", file=sys.stderr)
        return None


def _render(date_str, quotes, calendar, announces, news_items, research_items):
    lines = [
        "---",
        f'title: "市场与宏观 {date_str}"',
        f"date: {datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')}",
        'tags: ["每日简报"]',
        f'summary: "今日行情速览 + {len(news_items)} 条财经要闻。"',
        "---",
        "",
    ]
    # 行情速览
    lines.append("## 行情速览")
    lines.append("")
    if quotes:
        lines.append("| 指数 | 点位 | 涨跌幅 |")
        lines.append("|---|---|---|")
        for q in quotes:
            arrow = "▲" if q["change_pct"] >= 0 else "▼"
            lines.append(f"| {q['name']} | {q['price']:.2f} | {arrow}{abs(q['change_pct']):.2f}% |")
        sh = next((q for q in quotes if "上证" in q["name"]), None)
        if sh and sh.get("amount"):
            lines.append("")
            lines.append(f"沪市成交额：{sh['amount']/1e8:.0f} 亿元")
    else:
        lines.append(FAIL_BLOCK)
    lines.append("")

    # 宏观与政策
    lines.append("## 宏观与政策")
    lines.append("")
    if calendar:
        lines.append("| 指标 | 预期 | 前值 | 公布值 |")
        lines.append("|---|---|---|---|")
        for c in calendar:
            lines.append(f"| {c['title']} | {c.get('consensus') or '—'} | {c.get('previous') or '—'} | {c.get('actual') or '—'} |")
    else:
        lines.append(FAIL_BLOCK)
    lines.append("")

    # 财经要闻
    lines.append("## 财经要闻")
    lines.append("")
    if news_items:
        for n, item in enumerate(news_items, 1):
            lines.extend(_render_item(item, n))
    else:
        lines.append(FAIL_BLOCK)
    lines.append("")

    # 公告与研报
    lines.append("## 公告与研报")
    lines.append("")
    if announces:
        lines.append("**公司公告**（巨潮）")
        lines.append("")
        for a in announces:
            lines.append(f"- {a['sec_name']}：[{a['title']}]({a['url']})")
        lines.append("")
    else:
        lines.append("公告：")
        lines.append(FAIL_BLOCK)
        lines.append("")
    if research_items:
        lines.append("**研报要点**")
        lines.append("")
        for n, item in enumerate(research_items, 1):
            lines.extend(_render_item(item, n))

    return "\n".join(lines)


def _render_item(item, num):
    block = []
    title_zh = item.get("title_zh") or item["title"]
    block.append(f"### {num}. {title_zh}")
    block.append("")
    summary_zh = item.get("summary_zh") or item.get("summary", "")[:200]
    if summary_zh:
        block.append(summary_zh)
        block.append("")
    block.append(f"来源：[{item['source']}]({item['link']})")
    block.append("")
    return block


def _filter_section(config, section):
    return {
        "settings": config.get("settings", {}),
        "ai_keywords": config.get("ai_keywords", []),
        "feeds": [f for f in config.get("feeds", []) if f.get("section") == section],
    }


def _parse_date(date_str):
    return date.fromisoformat(date_str)
```

- [ ] **Step 4: 运行验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_gen_market.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add scripts/generators/market.py tests/test_gen_market.py
git commit -m "feat: add market section generator with degraded fallbacks"
```

---

## Task 12: homepage.py — 首页今日总览

**Files:**
- Create: `scripts/homepage.py`
- Create: `tests/test_homepage.py`

- [ ] **Step 1: 写首页生成失败测试**

`tests/test_homepage.py`：

```python
from pathlib import Path

from homepage import build_homepage


def test_build_homepage_with_all_sections(tmp_path):
    sections = {
        "ai": {
            "name": "AI 与科技社区",
            "url": "/ai/2026-08-01/",
            "items": [{"title_zh": "DeepSeek 发布", "score": 9, "link": "l1", "source": "S"}],
            "count": 8,
        },
        "world": {
            "name": "国际与深度",
            "url": "/world/2026-08-01/",
            "items": [{"title_zh": "休达越境", "score": 8, "link": "l2", "source": "S"}],
            "count": 7,
        },
        "market": {
            "name": "市场与宏观",
            "url": "/market/2026-08-01/",
            "items": [{"title_zh": "PMI 49.4", "score": 7, "link": "l3", "source": "S"}],
            "count": 12,
            "quotes": [{"name": "上证", "price": 3225, "change_pct": 0.82, "amount": 8e11}],
        },
    }
    out = build_homepage(sections, date_str="2026-08-01")
    assert "今日焦点" in out
    assert "DeepSeek 发布" in out
    assert "休达越境" in out
    assert "PMI 49.4" in out
    assert "/ai/2026-08-01/" in out
    assert "AI 与科技社区" in out


def test_build_homepage_degraded_section(tmp_path):
    sections = {
        "ai": {"name": "AI 与科技社区", "url": "/ai/", "items": [{"title_zh": "X", "score": 9, "link": "l", "source": "S"}], "count": 1},
        "world": None,  # 失败
        "market": None,  # 失败
    }
    out = build_homepage(sections, date_str="2026-08-01")
    assert "今日生成异常" in out
    assert "AI 与科技社区" in out


def test_market_focus_falls_back_to_quote(tmp_path):
    sections = {
        "market": {
            "name": "市场与宏观",
            "url": "/market/2026-08-01/",
            "items": [],  # 无财经要闻
            "count": 0,
            "quotes": [{"name": "上证指数", "price": 3225, "change_pct": 0.82, "amount": 8e11}],
        }
    }
    out = build_homepage(sections, date_str="2026-08-01")
    assert "上证指数" in out
```

- [ ] **Step 2: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_homepage.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'homepage'`）

- [ ] **Step 3: 创建 scripts/homepage.py**

`scripts/homepage.py`：

```python
"""首页今日总览生成。

跨版面取今日焦点 3 条（AI/国际/市场各一），下方各版面摘要卡片。
市场焦点：优先财经要闻最高分；无要闻取行情首条指数。
"""

from datetime import datetime
from pathlib import Path

from common import CST

SECTION_NAMES = {
    "ai": "AI 与科技社区",
    "world": "国际与深度",
    "market": "市场与宏观",
}


def build_homepage(sections, date_str):
    lines = [
        "---",
        'title: "首页"',
        'layout: "home"',
        f"date: {datetime.now(CST).strftime('%Y-%m-%dT%H:%M:%S%z')}",
        'summary: "今日三大版面总览。"',
        "---",
        "",
        "## 今日焦点",
        "",
    ]
    focus_items = []
    for key in ("ai", "world", "market"):
        sec = sections.get(key)
        if not sec:
            continue
        item = _pick_focus(sec, key)
        if item:
            focus_items.append((sec["name"], item))

    if focus_items:
        for name, item in focus_items:
            title = item.get("title_zh") or item.get("title", "")
            lines.append(f"- **{title}** 〔{name}〕")
    else:
        lines.append("- 今日暂无焦点条目")
    lines.append("")

    lines.append("## 各版面")
    lines.append("")
    for key in ("ai", "world", "market"):
        sec = sections.get(key)
        name = SECTION_NAMES[key]
        if sec:
            lines.append(f"### {name}")
            lines.append("")
            lines.append(f"今日 {sec.get('count', 0)} 条 · {_one_liner(sec, key)}")
            lines.append(f"[查看全文 →]({sec['url']})")
            lines.append("")
        else:
            lines.append(f"### {name}")
            lines.append("")
            lines.append(f"今日生成异常，[查看历史 →](/{key}/)")
            lines.append("")

    return "\n".join(lines)


def _pick_focus(sec, key):
    items = sec.get("items") or []
    if key == "market" and not items:
        quotes = sec.get("quotes") or []
        if quotes:
            q = quotes[0]
            return {"title": f"{q['name']} {q['price']:.2f} ({q['change_pct']:+.2f}%)"}
        return None
    if not items:
        return None
    ranked = sorted(items, key=lambda x: x.get("score", 0), reverse=True)
    return ranked[0]


def _one_liner(sec, key):
    items = sec.get("items") or []
    if not items:
        if key == "market":
            quotes = sec.get("quotes") or []
            if quotes:
                return f"焦点：{quotes[0]['name']} {quotes[0]['change_pct']:+.2f}%"
        return "今日无要闻"
    titles = [i.get("title_zh") or i.get("title", "") for i in items[:2]]
    return "焦点：" + "、".join(titles) + "…"
```

- [ ] **Step 4: 运行验证通过**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_homepage.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add scripts/homepage.py tests/test_homepage.py
git commit -m "feat: add homepage overview generator"
```

---

## Task 13: 重写 fetch_news.py 主入口

**Files:**
- Modify: `scripts/fetch_news.py`（整体重写）
- Modify: `scripts/common.py`（补 `load_config`）

- [ ] **Step 1: 在 common.py 补 load_config**

在 `scripts/common.py` 顶部 import 区加 `import yaml`（若 Task 4 已加则跳过），并在文件末尾追加：

```python
import yaml


def load_config(path=None):
    path = Path(path) if path else ROOT / "scripts" / "feeds.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
```

补测试 `tests/test_common_config.py`：

```python
from pathlib import Path
from common import load_config


def test_load_config_returns_dict(tmp_path):
    cfg = tmp_path / "f.yaml"
    cfg.write_text("settings:\n  total_limit: 3\nfeeds: []\n", encoding="utf-8")
    out = load_config(cfg)
    assert out["settings"]["total_limit"] == 3
    assert out["feeds"] == []
```

Run: `python -m pytest tests/test_common_config.py -v` → 1 passed

- [ ] **Step 2: 重写主入口**

`scripts/fetch_news.py`（完整替换）：

```python
#!/usr/bin/env python3
"""每日资讯抓取主入口。

编排三大版面生成（ai/world/market）+ 首页今日总览，更新 seen.json。
任一版面异常被捕获，不阻塞其他版面。
"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from common import load_config, load_seen, save_seen, build_llm_client, link_hash
from generators import ai, world, market
from homepage import build_homepage

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = Path(__file__).resolve().parent / "feeds.yaml"
SEEN_FILE = ROOT / "data" / "seen.json"
CONTENT_DIR = ROOT / "content"
CST = timezone(timedelta(hours=8))


def main():
    config = load_config(FEEDS_FILE)
    seen = load_seen(SEEN_FILE)
    client = build_llm_client()

    date_str = datetime.now(CST).strftime("%Y-%m-%d")
    sections = {}

    for key, gen in (("ai", ai), ("world", world), ("market", market)):
        try:
            result = gen.generate(config, seen, client, date_str,
                                  posts_dir=CONTENT_DIR / key)
            if result:
                sections[key] = _to_section_summary(key, result, date_str)
        except Exception as exc:
            print(f"[error] {key} 版面生成失败: {exc}", file=sys.stderr)
            sections[key] = None

    # 首页
    try:
        homepage_md = build_homepage(sections, date_str)
        (CONTENT_DIR / "_index.md").write_text(homepage_md, encoding="utf-8")
        print(f"[info] 首页已生成")
    except Exception as exc:
        print(f"[error] 首页生成失败: {exc}", file=sys.stderr)

    # 更新 seen
    now_iso = datetime.now(timezone.utc).isoformat()
    for key in sections:
        sec = sections.get(key)
        if not sec:
            continue
        for item in sec.get("_raw_items", []):
            seen[link_hash(item["link"])] = now_iso
    save_seen(SEEN_FILE, seen)
    print("[info] seen.json 已更新")


def _to_section_summary(key, result, date_str):
    """把生成器返回值转成首页摘要用的字典。

    items: 用于首页焦点选取（market 只含财经要闻，带 score）。
    _raw_items: 用于 seen 去重（market 含财经要闻+研报，都需去重）。
    """
    names = {"ai": "AI 与科技社区", "world": "国际与深度", "market": "市场与宏观"}
    items = result.get("items") or []
    raw = result.get("all_rss_items") or items
    return {
        "name": names[key],
        "url": f"/{key}/{date_str}/",
        "items": items,
        "count": len(items),
        "quotes": result.get("quotes") if key == "market" else None,
        "_raw_items": raw,
    }


if __name__ == "__main__":
    main()
```

> 注意：`import yaml` 已在 Step 1 加入 common.py。Step 3 的测试用 `monkeypatch.setattr(fetch_news, "load_config", ...)` 直接替换，故 main 内调用的 `load_config` 是 fetch_news 模块命名空间里的引用——确保 `fetch_news.py` 顶部 `from common import ... load_config` 已包含。

- [ ] **Step 3: 写主流程整合测试（mock 三生成器，固定日期）**

`tests/test_main_flow.py`：

```python
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

import fetch_news

CST = timezone(timedelta(hours=8))
FIXED = datetime(2026, 8, 1, 8, 0, 0, tzinfo=CST)


class FakeDateTime:
    @classmethod
    def now(cls, tz=None):
        return FIXED


def test_main_writes_all_sections_and_home(tmp_path, monkeypatch):
    # 固定日期，避免测试依赖运行当天
    monkeypatch.setattr(fetch_news, "datetime", FakeDateTime)
    monkeypatch.setattr(fetch_news, "CONTENT_DIR", tmp_path)
    monkeypatch.setattr(fetch_news, "SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(fetch_news, "load_config", lambda *a, **k: {"settings": {}, "ai_keywords": [], "feeds": []})
    monkeypatch.setattr(fetch_news, "load_seen", lambda *a, **k: {})
    monkeypatch.setattr(fetch_news, "save_seen", lambda *a, **k: None)
    monkeypatch.setattr(fetch_news, "build_llm_client", lambda: None)

    def fake_gen(config, seen, client, date_str, posts_dir):
        (posts_dir).mkdir(parents=True, exist_ok=True)
        path = posts_dir / f"{date_str}.md
        path.write_text("---\ntitle: x\n---\nbody", encoding="utf-8")
        return {"path": path, "items": [{"title_zh": "焦点", "score": 9, "link": "l", "source": "S"}]}

    with patch.object(fetch_news.ai, "generate", side_effect=fake_gen), \
         patch.object(fetch_news.world, "generate", side_effect=fake_gen), \
         patch.object(fetch_news.market, "generate", side_effect=fake_gen):
        fetch_news.main()

    assert (tmp_path / "ai" / "2026-08-01.md").exists()
    assert (tmp_path / "world" / "2026-08-01.md").exists()
    assert (tmp_path / "market" / "2026-08-01.md").exists()
    assert (tmp_path / "_index.md").exists()
    assert "今日焦点" in (tmp_path / "_index.md").read_text(encoding="utf-8")


def test_main_continues_on_section_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_news, "datetime", FakeDateTime)
    monkeypatch.setattr(fetch_news, "CONTENT_DIR", tmp_path)
    monkeypatch.setattr(fetch_news, "SEEN_FILE", tmp_path / "seen.json")
    monkeypatch.setattr(fetch_news, "load_config", lambda *a, **k: {"settings": {}, "feeds": []})
    monkeypatch.setattr(fetch_news, "load_seen", lambda *a, **k: {})
    monkeypatch.setattr(fetch_news, "save_seen", lambda *a, **k: None)
    monkeypatch.setattr(fetch_news, "build_llm_client", lambda: None)

    def boom(*a, **k):
        raise RuntimeError("boom")

    def ok(config, seen, client, date_str, posts_dir):
        posts_dir.mkdir(parents=True, exist_ok=True)
        (posts_dir / f"{date_str}.md").write_text("---\ntitle: x\n---\nbody", encoding="utf-8")
        return {"path": posts_dir / f"{date_str}.md", "items": [{"title_zh": "x", "score": 9, "link": "l", "source": "S"}]}

    with patch.object(fetch_news.ai, "generate", side_effect=boom), \
         patch.object(fetch_news.world, "generate", side_effect=ok), \
         patch.object(fetch_news.market, "generate", side_effect=ok):
        fetch_news.main()  # 不应抛异常
    assert (tmp_path / "_index.md").exists()
```

- [ ] **Step 4: 运行测试**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_main_flow.py -v`
Expected: 2 passed

- [ ] **Step 5: 运行全量测试**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add scripts/fetch_news.py scripts/common.py tests/test_common_config.py tests/test_main_flow.py
git commit -m "feat: rewrite fetch_news.py to orchestrate 3 sections + homepage"
```

---

## Task 14: Hugo 配置

**Files:**
- Modify: `hugo.toml`

- [ ] **Step 1: 更新菜单与首页配置**

在 `hugo.toml` 的 `[menu]` 段替换为：

```toml
[menu]
  [[menu.main]]
    identifier = "ai"
    name = "AI"
    url = "/ai/"
    weight = 10
  [[menu.main]]
    identifier = "world"
    name = "国际"
    url = "/world/"
    weight = 20
  [[menu.main]]
    identifier = "market"
    name = "市场"
    url = "/market/"
    weight = 30
  [[menu.main]]
    identifier = "archives"
    name = "归档"
    url = "/archives/"
    weight = 40
  [[menu.main]]
    identifier = "search"
    name = "搜索"
    url = "/search/"
    weight = 50
```

`[params.homeInfoParams]` 的 Content 改为：

```toml
  [params.homeInfoParams]
    Title = "每日资讯"
    Content = "三大版面每日自动汇总：AI 与科技社区、国际与深度、市场与宏观。"
```

- [ ] **Step 2: 验证 Hugo 配置语法**

Run: `cd /mnt/d/project/github/news_auto && hugo config 2>&1 | head -20` （需 Hugo extended ≥ 0.146）
Expected: 无 TOML 解析错误，输出配置。

若本地无 Hugo，跳过此步并在 Task 16 验证。

- [ ] **Step 3: 提交**

```bash
git add hugo.toml
git commit -m "feat: update hugo menu for 3 sections"
```

---

## Task 15: 迁移脚本与旧文章迁移

**Files:**
- Create: `scripts/migrate_posts.py`
- Create: `tests/test_migrate.py`
- Delete: `content/posts/`

- [ ] **Step 1: 写迁移失败测试**

`tests/test_migrate.py`：

```python
from pathlib import Path

from migrate_posts import split_post, SECTION_MAP


def test_split_post_routes_by_category(tmp_path):
    src = tmp_path / "2026-07-31.md"
    src.write_text("""---
title: "每日资讯 2026-07-31"
date: 2026-07-31T08:04:07+0800
tags: ["每日简报"]
summary: "x"
---

## 今日焦点

### 1. 焦点条

摘要

来源：[BBC](https://bbc)

## AI 动态

### 1. AI 新闻

来源：[T](https://t)

## 国际新闻

### 1. 国际新闻

来源：[BBC](https://bbc)
""", encoding="utf-8")

    result = split_post(src)
    assert "ai" in result and "world" in result
    assert "AI 动态" in result["ai"]
    assert "国际新闻" in result["world"]
    # 今日焦点放进 ai（早期文章 AI 为主体）
    assert "今日焦点" in result["ai"]


def test_split_post_only_world_section(tmp_path):
    src = tmp_path / "2026-07-18.md"
    src.write_text("""---
title: "每日资讯 2026-07-18"
date: 2026-07-18T16:54:00+0800
---

## 今日焦点

x

## 国际新闻

y
""", encoding="utf-8")

    result = split_post(src)
    assert "world" in result
    assert "ai" not in result  # 无 AI 章节
```

- [ ] **Step 2: 运行验证失败**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_migrate.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'migrate_posts'`）

- [ ] **Step 3: 创建 scripts/migrate_posts.py**

`scripts/migrate_posts.py`：

```python
#!/usr/bin/env python3
"""把 content/posts/*.md 按章节迁移到 content/ai/ 和 content/world/。

章节归类：
  AI 动态、社区热点 → ai
  国际新闻、深度精选 → world
  今日焦点 → 放入 ai（早期文章 AI 为主体；若该篇无 AI 章节则放 world）
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "content" / "posts"
AI_DIR = ROOT / "content" / "ai"
WORLD_DIR = ROOT / "content" / "world"

SECTION_MAP = {
    "AI 动态": "ai",
    "社区热点": "ai",
    "国际新闻": "world",
    "深度精选": "world",
}

HEADING_RE = re.compile(r"^## (.+)$", re.M)


def split_post(src_path):
    """把单篇文章按 ## 章节拆分到 ai/world 两个 markdown 字符串。"""
    text = src_path.read_text(encoding="utf-8")
    # 拆 frontmatter 和正文
    m = re.match(r"(---\n.*?\n---\n)(.*)", text, re.S)
    if not m:
        return {}
    fm, body = m.group(1), m.group(2)

    # 按二级标题切章节
    parts = re.split(r"(?=^## )", body, flags=re.M)
    buckets = {"ai": [], "world": []}
    focus = None  # 今日焦点章节，待决定去向

    for part in parts:
        hm = re.match(r"^## (.+)$", part, re.M)
        if not hm:
            continue
        heading = hm.group(1).strip()
        if heading == "今日焦点":
            focus = part
            continue
        section = SECTION_MAP.get(heading)
        if section:
            buckets[section].append(part)

    # 决定今日焦点去向：有 AI 章节则放 ai，否则 world
    if focus is not None:
        target = "ai" if buckets["ai"] else "world"
        buckets[target].insert(0, focus)

    result = {}
    for sec, parts_list in buckets.items():
        if not parts_list:
            continue
        new_fm = _rewrite_frontmatter(fm, src_path, sec)
        result[sec] = new_fm + "\n".join(parts_list)
    return result


def _rewrite_frontmatter(fm, src_path, section):
    """调整 frontmatter 的 title 适配新版面名。"""
    date = src_path.stem  # YYYY-MM-DD
    names = {"ai": "AI 与科技社区", "world": "国际与深度"}
    return re.sub(
        r'title: ".*?"',
        f'title: "{names[section]} {date}"',
        fm,
        count=1,
    )


def migrate():
    if not POSTS_DIR.exists():
        print("[info] 无 content/posts 目录，跳过迁移")
        return
    AI_DIR.mkdir(parents=True, exist_ok=True)
    WORLD_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for src in sorted(POSTS_DIR.glob("*.md")):
        result = split_post(src)
        for sec, content in result.items():
            target_dir = AI_DIR if sec == "ai" else WORLD_DIR
            (target_dir / src.name).write_text(content, encoding="utf-8")
            count += 1
        print(f"[migrate] {src.name} → {list(result.keys())}")
    print(f"[info] 迁移完成，写入 {count} 个文件")


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 4: 运行迁移测试**

Run: `cd /mnt/d/project/github/news_auto && python -m pytest tests/test_migrate.py -v`
Expected: 2 passed

- [ ] **Step 5: 执行实际迁移**

```bash
cd /mnt/d/project/github/news_auto
# 先备份
cp -r content/posts /tmp/posts_backup
# 运行迁移
python scripts/migrate_posts.py
# 验证迁移结果
ls content/ai/ | head
ls content/world/ | head
```

Expected: `content/ai/` 和 `content/world/` 下出现迁移后的 `.md` 文件。

- [ ] **Step 6: 删除旧 posts 目录并补 _index.md**

```bash
rm -rf content/posts
# 为各 section 创建 _index.md
for s in ai world market; do
  printf -- '---\ntitle: "%s"\n---\n' "$([ $s = ai ] && echo 'AI 与科技社区' || ([ $s = world ] && echo '国际与深度' || echo '市场与宏观'))" > content/$s/_index.md
done
cat content/ai/_index.md
```

- [ ] **Step 7: 提交**

```bash
git add scripts/migrate_posts.py tests/test_migrate.py content/
git rm -r content/posts 2>/dev/null || true
git add -A content/
git commit -m "feat: migrate posts to ai/world sections, add section indexes"
```

---

## Task 16: 更新 workflow 与 README

**Files:**
- Modify: `.github/workflows/daily.yml`
- Modify: `README.md`

- [ ] **Step 1: 更新 workflow 的 git add 路径**

在 `.github/workflows/daily.yml` 的「Commit new content」步骤，把：

```bash
          git add content/posts data/seen.json
```

改为：

```bash
          git add content/ai content/world content/market content/_index.md data/seen.json
```

其余步骤不变。

- [ ] **Step 2: 更新 README 目录结构与自定义说明**

把 `README.md` 的目录结构表更新为：

```markdown
| 路径 | 说明 |
|---|---|
| `hugo.toml` | Hugo 站点配置（PaperMod 主题、中文界面、三大版面菜单） |
| `themes/PaperMod/` | 主题（git submodule） |
| `content/ai/` | AI 与科技社区版面（每日文章） |
| `content/world/` | 国际与深度版面（每日文章） |
| `content/market/` | 市场与宏观版面（行情/宏观/要闻/公告研报） |
| `content/_index.md` | 首页今日总览（脚本生成） |
| `scripts/fetch_news.py` | 主入口，编排三版面 + 首页 |
| `scripts/feeds.yaml` | RSS 源清单（按 section 分组） |
| `scripts/sources/` | 数据抓取器（rss/eastmoney/jin10/cninfo） |
| `scripts/generators/` | 版面生成器（ai/world/market） |
| `scripts/common.py` | 共享工具（seen/LLM/渲染） |
| `data/seen.json` | 已处理文章指纹（自动维护，保留 30 天） |
| `.github/workflows/daily.yml` | 定时任务 + 构建 + 部署 |
```

「工作原理」段更新为：

```markdown
GitHub Actions (每日 UTC 23:00 / 北京 07:00)
  → scripts/fetch_news.py 编排三大版面：
    - AI 与科技社区：RSS 抓取 → LLM 排序 + 摘要 → content/ai/YYYY-MM-DD.md
    - 国际与深度：RSS 抓取 → LLM 排序 + 深度精选 → content/world/YYYY-MM-DD.md
    - 市场与宏观：东方财富行情 + 金十日历 + 巨潮公告 + 财经要闻 RSS → content/market/YYYY-MM-DD.md
  → 汇总三版面焦点 → 生成首页 content/_index.md
  → 提交回仓库 → Hugo 构建 → 部署 GitHub Pages
```

- [ ] **Step 3: 提交**

```bash
git add .github/workflows/daily.yml README.md
git commit -m "docs: update workflow paths and README for 3 sections"
```

---

## Task 17: 端到端验证

**Files:** 无（验证步骤）

- [ ] **Step 1: 安装依赖**

```bash
cd /mnt/d/project/github/news_auto
pip install -r scripts/requirements.txt
```

- [ ] **Step 2: 运行全量测试**

Run: `python -m pytest -v`
Expected: 全部通过

- [ ] **Step 3: 干跑抓取脚本（可不带 API key，验证降级路径）**

```bash
cd /mnt/d/project/github/news_auto
python scripts/fetch_news.py
```

Expected: 输出 `[fetch] ...` 日志、`[info] ... 版面已生成`、`[info] 首页已生成`。即使部分抓取失败，也应生成三版面 + 首页文件（市场版面含占位块）。

检查生成结果：

```bash
ls content/ai/ content/world/ content/market/
head -30 content/market/$(date +%Y-%m-%d).md
head -20 content/_index.md
```

- [ ] **Step 4: 本地 Hugo 构建验证（如有 Hugo）**

```bash
hugo --minify --baseURL "http://localhost:1313/"
ls public/ai public/world public/market 2>/dev/null
```

Expected: 各 section 目录生成，首页 `public/index.html` 含今日焦点。

- [ ] **Step 5: 提交验证产物**

```bash
git add content/ data/seen.json
git commit -m "chore: daily news 2026-08-01 (3 sections)"
```

---

## 完成标准

- [ ] 全量 `pytest` 通过
- [ ] `python scripts/fetch_news.py` 能生成三版面 + 首页（含降级占位）
- [ ] Hugo 能构建出 `/ai/` `/world/` `/market/` 三个 section 列表页 + 首页
- [ ] 导航菜单含 AI / 国际 / 市场
- [ ] 旧文章已迁移到 `content/ai/` 和 `content/world/`，`content/posts/` 已删除
- [ ] 单个抓取源失败时不影响其他版面/子板块
