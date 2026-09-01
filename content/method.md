---
title: "网站规则"
url: "/rules/"
date: 2026-09-01T09:49:27+0800
summary: "本站抓取哪些网站，以及如何筛选、评分与排序每日资讯。"
body_class: "section-rules"
ShowToc: true
TocOpen: true
---

> 本页由脚本根据 `scripts/feeds.yaml` 与 `scripts/common.py` 中的公开规则自动生成，列出当前实际抓取的网站与筛选权重。更新源或规则后，重新跑抓取流水线即可同步。上次生成：2026-09-01 09:49 +0800。

## 获取哪些网站

当前共配置 **24** 个 RSS / 新闻源，另加市场专用接口。下表即本站实际拉取的来源（含网站链接），增删改 `scripts/feeds.yaml` 后会自动反映到本页。

### AI与科技

| 来源名称 | 网站 | 分类 | AI 过滤 | 候选上限 |
|---|---|---|---|---|
| TechCrunch AI | [techcrunch.com](https://techcrunch.com/category/artificial-intelligence/feed/) | AI 动态 | 否 | 10 |
| The Verge AI | [theverge.com](https://www.theverge.com/rss/ai-artificial-intelligence/index.xml) | AI 动态 | 否 | 10 |
| VentureBeat AI | [venturebeat.com](https://venturebeat.com/category/ai/feed/) | AI 动态 | 否 | 8 |
| Hacker News Frontpage | [hnrss.org](https://hnrss.org/frontpage) | AI 动态 | 是 | 20 |
| Hacker News Best | [hnrss.org](https://hnrss.org/best) | 社区热点 | 否 | 15 |
| Reddit r/singularity Top | [reddit.com](https://www.reddit.com/r/singularity/top/.rss?t=day) | 社区热点 | 否 | 10 |
| Reddit r/OpenAI Top | [reddit.com](https://www.reddit.com/r/OpenAI/top/.rss?t=day) | 社区热点 | 否 | 8 |
| Reddit r/LocalLLaMA Top | [reddit.com](https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day) | 社区热点 | 否 | 8 |
| MIT Technology Review AI | [technologyreview.com](https://www.technologyreview.com/topic/artificial-intelligence/feed) | AI 动态 | 否 | 6 |

### 国际资讯

| 来源名称 | 网站 | 分类 | AI 过滤 | 候选上限 |
|---|---|---|---|---|
| BBC World | [feeds.bbci.co.uk](https://feeds.bbci.co.uk/news/world/rss.xml) | 国际新闻 | 否 | 10 |
| The Guardian World | [theguardian.com](https://www.theguardian.com/world/rss) | 国际新闻 | 否 | 10 |
| Reuters World (via Google News) | [reuters.com](https://news.google.com/rss/search?q=site:reuters.com%20world&hl=en-US&gl=US&ceid=US:en) | 国际新闻 | 否 | 8 |

### 金融市场与股市

| 来源名称 | 网站 | 分类 | AI 过滤 | 候选上限 |
|---|---|---|---|---|
| 第一财经 | [yicai.com](https://news.google.com/rss/search?q=site:yicai.com&hl=zh-CN&gl=CN&ceid=CN:zh-Hans) | 财经要闻 | 否 | 8 |
| 财新 | [caixin.com](https://news.google.com/rss/search?q=site:caixin.com&hl=zh-CN&gl=CN&ceid=CN:zh-Hans) | 财经要闻 | 否 | 8 |
| 华尔街见闻 | [wallstreetcn.com](https://news.google.com/rss/search?q=site:wallstreetcn.com&hl=zh-CN&gl=CN&ceid=CN:zh-Hans) | 财经要闻 | 否 | 8 |
| 界面新闻 | [jiemian.com](https://news.google.com/rss/search?q=site:jiemian.com+%E8%B4%A2%E7%BB%8F&hl=zh-CN&gl=CN&ceid=CN:zh-Hans) | 财经要闻 | 否 | 6 |
| CNBC Markets | [cnbc.com](https://www.cnbc.com/id/100003114/device/rss/rss.html) | 财经要闻 | 否 | 6 |
| WSJ Markets | [feeds.a.dj.com](https://feeds.a.dj.com/rss/RSSMarketsMain.xml) | 财经要闻 | 否 | 6 |
| 券商研报 | [news.google.com](https://news.google.com/rss/search?q=%E5%88%B8%E5%95%86%E7%A0%94%E6%8A%A5+%E5%AE%8F%E8%A7%82&hl=zh-CN&gl=CN&ceid=CN:zh-Hans) | 研报要点 | 否 | 6 |

### 深度阅读与学习

| 来源名称 | 网站 | 分类 | AI 过滤 | 候选上限 |
|---|---|---|---|---|
| The Economist Latest | [economist.com](https://www.economist.com/latest/rss.xml) | 经济学人 | 否 | 8 |
| The Economist Science & Tech | [economist.com](https://www.economist.com/science-and-technology/rss.xml) | 经济学人 | 否 | 6 |
| The Guardian Long Read | [theguardian.com](https://www.theguardian.com/news/series/the-long-read/rss) | 长读 | 否 | 6 |
| Scientific American | [scientificamerican.com](https://www.scientificamerican.com/platform/syndication/rss/) | 科学美国人 | 否 | 8 |
| The Atlantic | [theatlantic.com](https://www.theatlantic.com/feed/all/) | 大西洋月刊 | 否 | 8 |

### 市场专用数据源（非 RSS）

| 来源 | 网站 | 板块 | 说明 |
|---|---|---|---|
| 东方财富 | [quote.eastmoney.com](https://quote.eastmoney.com/) | 行情速览 | 主要股指 / 商品 / VIX 点位与涨跌幅 |
| 金十数据 / Forex Factory | [jin10.com](https://www.jin10.com/) | 宏观与政策 | 当日重要宏观数据日历 |
| 巨潮资讯 | [cninfo.com.cn](http://www.cninfo.com.cn/) | 公告与研报 | A 股公司公告列表 |

## 筛选与排序规则

### 流水线概览

1. 按版面拉取上表中的 RSS / 专用数据源，过滤时间窗与已读指纹（`data/seen.json`，保留约 30 天）。
2. **AI / 国际**：LLM 重要性排序 → 中文标题与摘要 → 写入当日 markdown。
3. **市场**：行情 + 宏观日历 + 公告 + 财经 RSS（概览截取）→ 摘要要闻。
4. **深度**：来源均衡选刊 → 加长导读 → 刊物式排版。
5. 汇总四版面焦点，生成首页；并刷新本「网站规则」页。
6. 趋势模块保存 AI / 市场的结构化每日快照，按周期聚合并记录可追溯的情景判断；趋势数据不足时不生成高可信度预测。

默认摘要模型：`deepseek-v4-pro`（可通过环境变量 `DEEPSEEK_MODEL` 覆盖）。未配置 API Key 时降级为英文 RSS 原文摘要，排序改为来源轮询。

### 全局参数

| 参数 | 当前值 | 含义 |
|---|---|---|
| `total_limit` | 15 | AI / 国际每日最多精选条数 |
| `per_source_limit` | 4 | AI / 国际单来源最多入选 |
| `hours_window` | 36 | 只取最近 N 小时内发布的条目 |
| `deep_limit` | 8 | 深度版面每日最多条数 |
| `deep_per_source_limit` | 2 | 深度版面单来源最多条数 |

### 各版面选取策略

#### AI与科技（`ai`）

- 配置源数量：9
- 选取策略：LLM 按重要性评分排序（见下方评分标准），取 total_limit 条；失败时降级为来源轮询均衡。
- 摘要形态：短摘要（约 2–3 句 / 120 字内）

#### 国际资讯（`world`）

- 配置源数量：3
- 选取策略：与 AI 版面相同：LLM 重要性排序 + 来源均衡降级。
- 摘要形态：短摘要（约 2–3 句 / 120 字内）

#### 金融市场与股市（`market`）

- 配置源数量：7
- 选取策略：财经要闻取候选前 8 条、研报前 4 条（不做重要性排序，省 token）；行情 / 宏观日历 / 公告走专用接口。
- 摘要形态：财经要闻与研报走短摘要；行情与日历为结构化表格。

#### 深度阅读与学习（`deep`）

- 配置源数量：5
- 选取策略：不参与 LLM 重要性排序；按发布时间取新，来源均衡（deep_limit / deep_per_source_limit）。
- 摘要形态：加长导读（约 3–4 句 / 180 字内），强调为何值得读。

### LLM 重要性评分（AI / 国际）

评分范围 1–10，由模型给出；分数越高越优先入选与进入「今日焦点」。

| 分数段 | 含义 |
|---|---|
| 9-10 | 全球级重大事件（重要 AI 模型/产品发布如 GPT、Kimi、DeepSeek 新版本，重大地缘政治事件，重要国际会议如 WAIC 开幕，行业格局改变的收购/政策） |
| 7-8 | 有广泛影响的行业新闻、重要国家的重大政策、知名公司重要动向、社区高热度讨论 |
| 5-6 | 一般性行业新闻、区域性事件 |
| 1-4 | 琐碎消息、营销软文、纯观点评论、影响面小的本地新闻 |

附加规则：

1. 「社区热点」分类（Hacker News 高分榜、Reddit AI 社区当日最热）代表技术社区正在疯传的内容：热度高（如 HN 500+ points）且话题重大的条目应显著加分；纯梗图、灌水贴、无关娱乐内容仍应打低分。
2. 同一事件的多条重复报道只选最权威的一条。
3. 以重要性优先，不强求各分类数量平衡。
4. 评分 ≥ 9 的条目在正文标记【重点】，并优先进入「今日焦点」。

### AI 关键词过滤

对 `ai_filter: true` 的源（如 Hacker News Frontpage），标题/摘要需命中下列关键词之一才会进入候选（短词按单词边界匹配）：

`AI`, `A.I.`, `artificial intelligence`, `machine learning`, `deep learning`, `neural`, `LLM`, `GPT`, `OpenAI`, `Anthropic`, `Claude`, `Gemini`, `DeepSeek`, `Llama`, `Mistral`, `transformer`, `diffusion model`, `AGI`, `chatbot`, `copilot`

### 去重与降级

- 链接指纹写入 `data/seen.json`，已见条目不再重复入选。
- LLM 排序失败：按来源轮询均衡选取（`select_items`）。
- LLM 摘要失败：使用 RSS 原始英文摘要；若配置了 Key 且该版面全部摘要失败则跳过发布。

### 趋势研判边界

- 趋势只使用 AI 与市场版面的结构化数据，保留来源、交易日期、覆盖率和数据警告。
- 周、月、季度、年度分别设有最低样本要求，覆盖不足时显示数据不足，不用 0 补齐。
- 第一版预测使用可解释规则和情景描述，不输出未经回测校准的精确概率或个股目标价。
- 预测记录不可覆盖，目标周期结束后追加实际结果与复盘状态。内容仅供信息参考，不构成投资建议。

## 如何更新本页

1. 改 `scripts/feeds.yaml`（源、网站、条数、时间窗等）。
2. 改 `scripts/common.py` 中的 `SCORE_BANDS` / `RANK_RULES` / `HIGHLIGHT_SCORE`（公开评分权重）。
3. 运行 `python scripts/fetch_news.py`（或单独 `python scripts/method.py`）。
