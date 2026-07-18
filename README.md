# news_auto — 每日 AI 与国际资讯自动博客

每天定时抓取国际新闻与 AI 领域 RSS 源，用 DeepSeek 生成中英双语精简摘要，通过 Hugo + PaperMod 构建成静态博客，托管在 GitHub Pages。

站点地址：<https://hachgo.github.io/news_auto/>

## 工作原理

```
GitHub Actions (每日 UTC 23:00 / 北京 07:00)
  → scripts/fetch_news.py 抓取 RSS → 去重 (data/seen.json)
  → DeepSeek 翻译 + 摘要 → 生成 content/posts/YYYY-MM-DD.md
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
| `hugo.toml` | Hugo 站点配置（PaperMod 主题、中文界面） |
| `themes/PaperMod/` | 主题（git submodule） |
| `content/posts/` | 每日自动生成的资讯文章 |
| `scripts/fetch_news.py` | 抓取 + 摘要 + 生成 Markdown 主流程 |
| `scripts/feeds.yaml` | RSS 源清单与筛选配置（可自由增删源） |
| `data/seen.json` | 已处理文章指纹，防止重复（自动维护，保留 30 天） |
| `.github/workflows/daily.yml` | 定时任务 + 构建 + 部署 |

## 自定义

- **增删新闻源**：编辑 `scripts/feeds.yaml` 的 `feeds` 列表；`ai_filter: true` 表示按 `ai_keywords` 关键词过滤。
- **调整条数**：`feeds.yaml` 中 `settings.total_limit`（每日总条数）、`per_source_limit`（单来源上限）。
- **调整发布时间**：修改 `.github/workflows/daily.yml` 中的 cron 表达式（UTC 时间）。
- **换模型**：设置环境变量 `DEEPSEEK_MODEL`（默认 `deepseek-chat`）或 `DEEPSEEK_BASE_URL`（任意 OpenAI 兼容接口）。

## 本地开发

```bash
git clone --recurse-submodules https://github.com/HachGo/news_auto.git
cd news_auto
pip install -r scripts/requirements.txt
export DEEPSEEK_API_KEY=sk-xxx   # 可选
python scripts/fetch_news.py     # 生成当日文章
hugo server                       # 需要 Hugo extended >= 0.146
```
