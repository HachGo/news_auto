---
title: "方法"
url: "/method/"
date: 2026-08-09T11:39:05+0800
summary: "本站如何抓取、筛选与排序每日资讯：流水线、评分权重与来源清单。"
body_class: "section-method"
ShowToc: true
TocOpen: true
---

> 本页由脚本根据 `scripts/feeds.yaml` 与 `scripts/common.py` 中的评分规则自动生成。更新源或权重后，重新跑抓取流水线即可同步。上次生成：2026-08-09 11:39 +0800。

## 流水线概览

1. 按版面拉取 RSS / 专用数据源，过滤时间窗与已读指纹（`data/seen.json`，保留约 30 天）。
2. **AI / 国际**：LLM 重要性排序 → 中文标题与摘要 → 写入当日 markdown。
3. **市场**：行情 + 宏观日历 + 公告 + 财经 RSS（概览截取）→ 摘要要闻。
4. **深度**：来源均衡选刊 → 加长导读 → 刊物式排版。
5. 汇总四版面焦点，生成首页；并刷新本「方法」页。

默认摘要模型：`deepseek-v4-pro`（可通过环境变量 `DEEPSEEK_MODEL` 覆盖）。未配置 API Key 时降级为英文 RSS 原文摘要，排序改为来源轮询。

## 全局参数

| 参数 | 当前值 | 含义 |
|---|---|---|
| `total_limit` | 15 | AI / 国际每日最多精选条数 |
| `per_source_limit` | 4 | AI / 国际单来源最多入选 |
| `hours_window` | 36 | 只取最近 N 小时内发布的条目 |
| `deep_limit` | 8 | 深度版面每日最多条数 |
| `deep_per_source_limit` | 2 | 深度版面单来源最多条数 |

## 各版面筛选逻辑

### AI与科技（`ai`）

- RSS / 配置源数量：9
- 选取策略：LLM 按重要性评分排序（见下方评分标准），取 total_limit 条；失败时降级为来源轮询均衡。
- 摘要形态：短摘要（约 2–3 句 / 120 字内）

### 国际资讯（`world`）

- RSS / 配置源数量：3
- 选取策略：与 AI 版面相同：LLM 重要性排序 + 来源均衡降级。
- 摘要形态：短摘要（约 2–3 句 / 120 字内）

### 金融市场与股市（`market`）

- RSS / 配置源数量：7
- 选取策略：财经要闻取候选前 8 条、研报前 4 条（不做重要性排序，省 token）；行情 / 宏观日历 / 公告走专用接口。
- 摘要形态：财经要闻与研报走短摘要；行情与日历为结构化表格。

### 深度阅读与学习（`deep`）

- RSS / 配置源数量：5
- 选取策略：不参与 LLM 重要性排序；按发布时间取新，来源均衡（deep_limit / deep_per_source_limit）。
- 摘要形态：加长导读（约 3–4 句 / 180 字内），强调为何值得读。

## LLM 重要性评分（AI / 国际）

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

## AI 关键词过滤

对 `ai_filter: true` 的源（如 Hacker News Frontpage），标题/摘要需命中下列关键词之一才会进入候选（短词按单词边界匹配）：

`AI`, `A.I.`, `artificial intelligence`, `machine learning`, `deep learning`, `neural`, `LLM`, `GPT`, `OpenAI`, `Anthropic`, `Claude`, `Gemini`, `DeepSeek`, `Llama`, `Mistral`, `transformer`, `diffusion model`, `AGI`, `chatbot`, `copilot`

## 新闻源清单

下表直接来自 `scripts/feeds.yaml`，增删改源后重新生成即可更新本页。

### AI与科技

| 来源 | 分类 | AI 过滤 | 候选上限 |
|---|---|---|---|
| TechCrunch AI | AI 动态 | 否 | 10 |
| The Verge AI | AI 动态 | 否 | 10 |
| VentureBeat AI | AI 动态 | 否 | 8 |
| Hacker News Frontpage | AI 动态 | 是 | 20 |
| Hacker News Best | 社区热点 | 否 | 15 |
| Reddit r/singularity Top | 社区热点 | 否 | 10 |
| Reddit r/OpenAI Top | 社区热点 | 否 | 8 |
| Reddit r/LocalLLaMA Top | 社区热点 | 否 | 8 |
| MIT Technology Review AI | AI 动态 | 否 | 6 |

### 国际资讯

| 来源 | 分类 | AI 过滤 | 候选上限 |
|---|---|---|---|
| BBC World | 国际新闻 | 否 | 10 |
| The Guardian World | 国际新闻 | 否 | 10 |
| Reuters World (via Google News) | 国际新闻 | 否 | 8 |

### 金融市场与股市

| 来源 | 分类 | AI 过滤 | 候选上限 |
|---|---|---|---|
| 第一财经 | 财经要闻 | 否 | 8 |
| 财新 | 财经要闻 | 否 | 8 |
| 华尔街见闻 | 财经要闻 | 否 | 8 |
| 界面新闻 | 财经要闻 | 否 | 6 |
| CNBC Markets | 财经要闻 | 否 | 6 |
| WSJ Markets | 财经要闻 | 否 | 6 |
| 券商研报 | 研报要点 | 否 | 6 |

### 深度阅读与学习

| 来源 | 分类 | AI 过滤 | 候选上限 |
|---|---|---|---|
| The Economist Latest | 经济学人 | 否 | 8 |
| The Economist Science & Tech | 经济学人 | 否 | 6 |
| The Guardian Long Read | 长读 | 否 | 6 |
| Scientific American | 科学美国人 | 否 | 8 |
| The Atlantic | 大西洋月刊 | 否 | 8 |

### 市场专用数据源（非 RSS）

| 来源 | 板块 | 说明 |
|---|---|---|
| 东方财富 | 行情速览 | 主要股指 / 商品 / VIX 点位与涨跌幅 |
| 金十数据 / Forex Factory | 宏观与政策 | 当日重要宏观数据日历 |
| 巨潮资讯 | 公告与研报 | A 股公司公告列表 |

## 去重与降级

- 链接指纹写入 `data/seen.json`，已见条目不再重复入选。
- LLM 排序失败：按来源轮询均衡选取（`select_items`）。
- LLM 摘要失败：使用 RSS 原始英文摘要；若配置了 Key 且该版面全部摘要失败则跳过发布。

## 如何更新本页

1. 改 `scripts/feeds.yaml`（源、条数、时间窗等）。
2. 改 `scripts/common.py` 中的 `SCORE_BANDS` / `RANK_RULES` / `HIGHLIGHT_SCORE`（评分权重）。
3. 运行 `python scripts/fetch_news.py`（或单独 `python scripts/method.py`）。
