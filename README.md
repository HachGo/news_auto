# news_auto — 每日资讯自动博客

每天定时抓取 AI、国际、市场与深度刊物 RSS，用 DeepSeek 生成中英双语精简摘要，并把结构化新闻、行情和宏观信号聚合为趋势研判页，通过 Hugo + PaperMod 构建成静态博客，托管在 GitHub Pages。

站点地址：<https://hachgo.github.io/news_auto/>

## 工作原理

```
GitHub Actions (每日 UTC 23:00 / 北京 07:00)
  → scripts/fetch_news.py 编排四版面：
    - AI与科技：RSS 抓取 → LLM 排序 + 摘要 → content/ai/YYYY-MM-DD.md
    - 国际资讯：RSS 抓取 → LLM 排序 + 摘要 → content/world/YYYY-MM-DD.md
    - 金融市场与股市：东方财富行情 + 金十日历 + 巨潮公告 + 财经要闻 RSS → content/market/YYYY-MM-DD.md
    - 深度阅读与学习：经济学人 / 科学美国人 / 卫报长读 / 大西洋月刊等 → content/deep/YYYY-MM-DD.md
  → 趋势模块保存每日结构化快照，生成周、月、季度、年度趋势数据 → static/data/trends/
  → 汇总四版面焦点 → 生成首页 content/_index.md
  → 同步生成网站规则页 content/method.md（源清单 + 评分权重）
  → 提交回仓库 → Hugo 构建 → 部署 GitHub Pages
```

## 首次部署配置（必做）

1. **配置 API Key**：仓库 Settings → Secrets and variables → Actions → New repository secret
   - Name: `DEEPSEEK_API_KEY`
   - Value: 你的 DeepSeek API Key（<https://platform.deepseek.com> 获取）
   - 未配置时脚本会降级为直接使用英文 RSS 摘要，不会报错。
2. **开启 GitHub Pages**：仓库 Settings → Pages → Build and deployment → Source 选择 **GitHub Actions**。
3. 推送代码后，到 Actions 页面手动触发一次 **Daily News** workflow（workflow_dispatch）验证。

## 目录结构

| 路径 | 说明 |
|---|---|
| `hugo.toml` | Hugo 站点配置（PaperMod 主题、中文界面、四版面菜单） |
| `themes/PaperMod/` | 主题（git submodule） |
| `content/ai/` | AI与科技版面（每日文章） |
| `content/world/` | 国际资讯版面（每日文章） |
| `content/market/` | 金融市场与股市（行情/宏观/要闻/公告研报） |
| `content/deep/` | 深度阅读与学习（刊物长读） |
| `content/trends/` | 趋势研判版面（科技与市场趋势） |
| `content/_index.md` | 首页今日总览（脚本生成） |
| `content/method.md` | 网站规则（脚本生成，与 feeds/评分/屏蔽词同步） |
| `assets/css/extended/` | 站点扩展样式（首页四版面、深度条目节奏） |
| `scripts/fetch_news.py` | 主入口，编排四版面 + 首页 + 网站规则页 |
| `scripts/method.py` | 网站规则页生成器 |
| `scripts/feeds.yaml` | RSS 源清单（按 section 分组） |
| `scripts/sources/` | 数据抓取器（rss/eastmoney/jin10/cninfo） |
| `scripts/generators/` | 版面生成器（ai/world/market/deep） |
| `scripts/common.py` | 共享工具（seen/LLM/渲染） |
| `data/seen.json` | 已处理文章指纹（自动维护，保留 30 天） |
| `data/trends/` | 趋势每日快照、周期聚合、预测与评估记录 |
| `.github/workflows/daily.yml` | 定时任务 + 构建 + 部署 |

## 自定义

- **增删新闻源**：编辑 `scripts/feeds.yaml` 的 `feeds` 列表；`ai_filter: true` 表示按 `ai_keywords` 关键词过滤。
- **调整条数**：`feeds.yaml` 中 `settings.total_limit`（ai/world 每日上限）、`per_source_limit`（单来源上限）、`deep_limit`（深度版面上限）。
- **调整发布时间**：修改 `.github/workflows/daily.yml` 中的 cron 表达式（UTC 时间）。
- **换模型**：设置环境变量 `DEEPSEEK_MODEL`（默认 `deepseek-v4-pro`，thinking 模式开启）或 `DEEPSEEK_BASE_URL`（任意 OpenAI 兼容接口）。

## 本地开发

```bash
git clone --recurse-submodules https://github.com/HachGo/news_auto.git
cd news_auto
pip install -r scripts/requirements.txt
export DEEPSEEK_API_KEY=sk-xxx   # 可选
python scripts/fetch_news.py     # 生成当日文章
hugo server                       # 需要 Hugo extended >= 0.146
```
