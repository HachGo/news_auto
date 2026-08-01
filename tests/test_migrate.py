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
