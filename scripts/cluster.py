"""同日新闻聚类：双语“标题 + 摘要”的 TF-IDF 余弦相似度，不依赖模型或外部库。

阈值按 2026-10-03 的真实候选池（124 条）校准：仅用标题时同一报道与无关报道的分数交错；
标题计两次再拼接摘要前 300 字、去掉“ - 来源”后缀后，0.25 能分开两者。数据积累后可再调。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime

from common import has_cjk, strip_html

SIMILARITY = 0.25
SUMMARY_CHARS = 300
# Google News 等聚合源的标题以“ - 来源名”结尾，会把不同报道拉近、同一报道拉远
SOURCE_SUFFIX = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,40}$")
FIELD_BY_SECTION = {"ai": "ai_tech", "world": "world", "market": "finance"}
STOP_WORDS = frozenset("the and for with from that this are was were will has have had its into over after before about not but a an of to in on is at by as it be or".split())


def tokens(text):
    """英文去停用词，连续中文按字符二元组拆分。"""
    text = strip_html(text or "").lower()
    output = [word for word in re.findall(r"[a-z][a-z0-9]+", text)
              if len(word) >= 3 and word not in STOP_WORDS]
    for chunk in re.findall(r"[\u3400-\u9fff]+", text):
        output.extend(chunk[index:index + 2] for index in range(len(chunk) - 1))
    return output


def tfidf_vectors(texts):
    """在给定语料上建立归一化稀疏向量，供新闻与创意去重共用。"""
    counts = [Counter(tokens(text)) for text in texts]
    document_frequency = Counter(token for count in counts for token in count)
    size = len(counts)
    vectors = []
    for count in counts:
        vector = {token: amount * (math.log((1 + size) / (1 + document_frequency[token])) + 1)
                  for token, amount in count.items()}
        norm = math.sqrt(sum(value * value for value in vector.values()))
        vectors.append({token: value / norm for token, value in vector.items()} if norm else {})
    return vectors


def cosine(left, right):
    """归一化向量点积；一个泛词不足以判定同一报道。"""
    shared = left.keys() & right.keys()
    if len(shared) < 2:
        return 0.0
    return sum(left[token] * right[token] for token in shared)


def _text(title, summary):
    """比对文本：标题加权（重复一次）+ 摘要开头；去掉来源后缀。"""
    title = SOURCE_SUFFIX.sub("", strip_html(title or ""))
    return f"{title} {title} {strip_html(summary or '')[:SUMMARY_CHARS]}"


def _texts(item):
    """已选条目的中英文比对文本（brief 标准化条目为 {zh,en} 字典，生成器条目为平铺字段）。"""
    title, summary = item.get("title") or "", item.get("summary") or ""
    if isinstance(title, dict):
        titles = {lang: title.get(lang) or "" for lang in ("en", "zh")}
    else:
        titles = {"en": item.get("title_en") or title, "zh": item.get("title_zh") or title}
    if isinstance(summary, dict):
        summaries = {lang: summary.get(lang) or "" for lang in ("en", "zh")}
    else:
        summaries = {"en": item.get("summary_en") or summary, "zh": item.get("summary_zh") or summary}
    return {lang: _text(titles[lang], summaries[lang]) for lang in ("en", "zh")}


def _report(item):
    title = item.get("title") or ""
    lang = item.get("lang")
    if isinstance(title, dict):
        lang = lang or ("zh" if has_cjk(title.get("zh", "")) else "en")
        title = title.get(lang) or title.get("zh") or title.get("en") or ""
    else:
        lang = lang or ("zh" if has_cjk(title) else "en")
    published = item.get("time") or item.get("published_at")
    return {"source": item.get("source") or "", "lang": lang, "title": strip_html(title),
            "link": item.get("link") or item.get("url") or "",
            "published_at": published.isoformat() if isinstance(published, datetime) else published}


def _timestamp(report):
    try:
        return datetime.fromisoformat(report.get("published_at") or "").timestamp()
    except (ValueError, TypeError):
        return 0


def cluster_events(selected_by_section, candidates_by_section):
    """返回代表条目副本，附加 section、field、fields、reports、report_count、langs。

    入参是各版面的条目列表；支持生成器原始条目或 brief 标准化条目。
    仅候选与已选标题匹配时才附加来源，不从候选中增添新的事件。
    """
    selected = []
    for section, items in selected_by_section.items():
        for item in items:
            field = item.get("field") or FIELD_BY_SECTION[section]
            selected.append({**item, "section": item.get("section") or section, "field": field,
                             "fields": list(item.get("fields") or [field])})
    if not selected:
        return []
    candidates = [candidate for items in candidates_by_section.values() for candidate in items
                  if candidate.get("score", 5) != 1]
    texts = []
    selected_indices = []
    for item in selected:
        indices = {}
        for lang, text in _texts(item).items():
            indices[lang] = len(texts)
            texts.append(text)
        selected_indices.append(indices)
    candidate_indices = []
    for candidate in candidates:
        report = _report(candidate)
        candidate_indices.append((len(texts), report))
        texts.append(_text(report["title"], candidate.get("summary")))
    vectors = tfidf_vectors(texts)
    reports = [list(item.get("reports") or [_report(item)]) for item in selected]
    for vector_index, report in candidate_indices:
        best = max(range(len(selected)), key=lambda index: (
            cosine(vectors[vector_index], vectors[selected_indices[index][report["lang"]]]),
            float(selected[index].get("score", 5)), -index))
        similarity = cosine(vectors[vector_index], vectors[selected_indices[best][report["lang"]]])
        if similarity >= SIMILARITY:
            reports[best].append(report)

    # 连通分量合并已选事件，跨版面匹配使用同语言的译后标题。
    parent = list(range(len(selected)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(selected)):
        for right in range(left + 1, len(selected)):
            same_link = selected[left].get("link") and selected[left].get("link") == selected[right].get("link")
            similarity = max(cosine(vectors[selected_indices[left][lang]], vectors[selected_indices[right][lang]])
                             for lang in ("en", "zh"))
            if same_link or similarity >= SIMILARITY:
                parent[find(right)] = find(left)
    groups = {}
    for index in range(len(selected)):
        groups.setdefault(find(index), []).append(index)
    output = []
    for group in groups.values():
        winner = max(group, key=lambda index: (float(selected[index].get("score", 5)), -index))
        event = dict(selected[winner])
        event["fields"] = list(dict.fromkeys(field for index in [winner] + group for field in selected[index]["fields"]))
        by_link = {}
        representative = next((report for report in reports[winner]
                               if report["link"] == selected[winner].get("link")), _report(selected[winner]))
        for report in [representative] + [report for index in group for report in reports[index]]:
            if report["link"]:
                by_link.setdefault(report["link"], report)
        event["reports"] = sorted(by_link.values(), key=lambda report: (
            report["link"] != representative["link"], -_timestamp(report), report["link"]))
        event["report_count"] = len(event["reports"])
        event["langs"] = {lang: sum(report["lang"] == lang for report in event["reports"]) for lang in ("en", "zh")}
        output.append(event)
    return output
