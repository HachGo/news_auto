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
