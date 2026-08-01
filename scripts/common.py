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
