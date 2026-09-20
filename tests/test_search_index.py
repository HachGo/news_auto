import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HUGO = shutil.which("hugo")
THEME = ROOT / "themes" / "PaperMod" / "layouts"
needs_hugo = pytest.mark.skipif(
    HUGO is None or not THEME.exists(), reason="需要 hugo 与 PaperMod 主题",
)

# 仓库里最老的一批日报之一，用来验证时间窗口确实生效（这个日期只会越来越旧）
OLD_DATE = "2026-07-18"


def _build(work: Path, params: str = ""):
    """按给定 params 覆盖构建一次，返回 (index.json 内容, 字节数)。"""
    work.mkdir(parents=True, exist_ok=True)
    config = work / "override.toml"
    config.write_text("[params]\n" + params, encoding="utf-8")
    out = work / "public"
    subprocess.run(
        [HUGO, "--quiet", "--config", f"hugo.toml,{config}",
         "--destination", str(out), "--baseURL", "https://example.com/news_auto/"],
        cwd=ROOT, check=True, capture_output=True,
    )
    path = out / "index.json"
    return json.loads(path.read_text(encoding="utf-8")), path.stat().st_size


def _median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


@needs_hugo
def test_search_index_truncates_entry_content(tmp_path):
    entries, _ = _build(tmp_path, "searchIndexChars = 120\n")

    assert entries
    assert {"title", "content", "permalink", "summary", "section"} <= set(entries[0])
    lengths = [len(e["content"]) for e in entries]

    # truncate 会补一个省略号；HTML 实体按 1 个字符计数，所以留一点余量
    assert _median(lengths) <= 122
    assert max(lengths) <= 160


@needs_hugo
def test_search_index_keeps_full_text_when_limit_is_large(tmp_path):
    entries, _ = _build(tmp_path, "searchIndexChars = 100000\n")

    assert max(len(e["content"]) for e in entries) > 500


@needs_hugo
def test_truncation_shrinks_the_index_file(tmp_path):
    _, wide = _build(tmp_path / "wide", "searchIndexChars = 100000\n")
    _, narrow = _build(tmp_path / "narrow", "searchIndexChars = 120\n")

    assert narrow < wide * 0.6


@needs_hugo
def test_search_index_respects_days_window(tmp_path):
    everything, _ = _build(tmp_path / "wide", "searchIndexDays = 3650\n")
    recent, _ = _build(tmp_path / "narrow", "searchIndexDays = 3\n")

    assert everything and recent
    assert len(recent) < len(everything)
    assert any(OLD_DATE in e["permalink"] for e in everything)
    assert not any(OLD_DATE in e["permalink"] for e in recent)
