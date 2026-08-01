"""共享工具：纯函数、seen.json、LLM 客户端、渲染工具。三版面共用。"""

import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
