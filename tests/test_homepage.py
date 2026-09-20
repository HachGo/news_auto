import re
import shutil
import subprocess
from pathlib import Path

import pytest

from homepage import build_homepage

ROOT = Path(__file__).resolve().parent.parent
HUGO = shutil.which("hugo")
THEME = ROOT / "themes" / "PaperMod" / "layouts"
needs_hugo = pytest.mark.skipif(
    HUGO is None or not THEME.exists(), reason="需要 hugo 与 PaperMod 主题",
)


def _sections_for(date_str="2026-08-01"):
    return {
        "ai": {"name": "AI与科技", "url": f"/ai/{date_str}/", "status": "ready",
               "items": [{"title_zh": "焦点一", "score": 9, "link": "l1", "source": "S"}],
               "count": 8},
        "world": {"name": "国际资讯", "url": f"/world/{date_str}/", "status": "empty",
                  "items": [], "count": 0},
        "market": {"name": "金融市场与股市", "url": f"/market/{date_str}/", "status": "ready",
                   "items": [{"title_zh": "PMI 49.4", "score": 7, "link": "l3", "source": "S"}],
                   "count": 12,
                   "quotes": [{"name": "上证指数", "price": 3225, "change_pct": 0.82}]},
        "deep": None,
    }


def _hrefs(html):
    """同时兼容 Hugo 默认输出（带引号）与 minify 输出（不带引号）。"""
    return [quoted or bare for quoted, bare in re.findall(r'href=(?:"([^"]*)"|([^\s">]+))', html)]


def test_homepage_links_are_hugo_shortcodes():
    """站内链接必须交给 Hugo 解析；写死 /ai/xxx/ 在子路径部署时会 404。"""
    out = build_homepage(_sections_for(), date_str="2026-08-01")

    hrefs = re.findall(r'href="(\{\{<[^>]+>\}\})"', out)
    assert hrefs
    for href in hrefs:
        assert href.startswith('{{< homehref "/'), href
        assert href.endswith('" >}}'), href
    # 生成内容里不应再出现写死的站内根路径
    assert 'href="/' not in out


def test_homepage_rejects_unsafe_link_targets():
    """含引号/尖括号等会破坏短代码语法的 URL 要退化到首页，而不是注入内容。"""
    sections = {
        "ai": {"name": "AI与科技", "url": '"/><script>alert(1)</script>', "status": "ready",
               "items": [{"title_zh": "X", "score": 1}], "count": 1},
    }
    out = build_homepage(sections, date_str="2026-08-01")

    assert "<script>" not in out
    assert '{{< homehref "/" >}}' in out


def test_homehref_shortcode_contract():
    """短代码本身要能兜底：页面不存在时退回 relURL，而不是让构建失败。"""
    text = (ROOT / "layouts" / "_shortcodes" / "homehref.html").read_text(encoding="utf-8")

    assert "site.GetPage" in text
    assert "relURL" in text
    assert "{{- return" not in text  # shortcode 不支持 return，会直接报构建错误


def test_home_overview_renders_on_first_page_only():
    text = (ROOT / "layouts" / "list.html").read_text(encoding="utf-8")

    assert "{{- if and .Content (or (not .IsHome) (eq $paginator.PageNumber 1)) }}" in text


@needs_hugo
def test_rendered_homepage_links_resolve_under_sub_path(tmp_path):
    """真机构建：子路径部署下首页链接必须带前缀，缺失页面走兜底不报错。"""
    content = tmp_path / "content"
    shutil.copytree(ROOT / "content", content)
    sections = _sections_for("2026-08-01")
    sections["deep"] = {"name": "深度阅读与学习", "url": "/deep/1999-01-01/", "status": "ready",
                        "items": [{"title_zh": "缺失日期", "score": 1}], "count": 1}
    (content / "_index.md").write_text(build_homepage(sections, "2026-08-01"), encoding="utf-8")

    out = tmp_path / "public"
    subprocess.run(
        [HUGO, "--quiet", "--contentDir", str(content), "--destination", str(out),
         "--baseURL", "https://example.com/news_auto/"],
        cwd=ROOT, check=True, capture_output=True,
    )
    hrefs = _hrefs((out / "index.html").read_text(encoding="utf-8"))

    assert "/news_auto/ai/2026-08-01/" in hrefs
    assert "/news_auto/world/" in hrefs                  # status=empty 退回版面列表
    assert "/news_auto/deep/1999-01-01/" in hrefs        # 页面不存在时 relURL 兜底
    assert not [h for h in hrefs if h.startswith("/ai/")]  # 不能残留写死的根路径

    page2 = (out / "page" / "2" / "index.html").read_text(encoding="utf-8")
    assert "home-overview" not in page2


def test_build_homepage_with_all_sections(tmp_path):
    sections = {
        "ai": {
            "name": "AI与科技",
            "url": "/ai/2026-08-01/",
            "items": [{"title_zh": "DeepSeek 发布", "score": 9, "link": "l1", "source": "S"}],
            "count": 8,
        },
        "world": {
            "name": "国际资讯",
            "url": "/world/2026-08-01/",
            "items": [{"title_zh": "休达越境", "score": 8, "link": "l2", "source": "S"}],
            "count": 7,
        },
        "market": {
            "name": "金融市场与股市",
            "url": "/market/2026-08-01/",
            "items": [{"title_zh": "PMI 49.4", "score": 7, "link": "l3", "source": "S"}],
            "count": 12,
            "quotes": [{"name": "上证指数", "price": 3225, "change_pct": 0.82, "amount": 8e11}],
        },
        "deep": {
            "name": "深度阅读与学习",
            "url": "/deep/2026-08-01/",
            "items": [{
                "title_zh": "长读一篇",
                "score": 0,
                "summary_zh": "这是一篇值得慢慢读的深度文章导语。",
                "link": "l4",
                "source": "Economist",
            }],
            "count": 4,
        },
    }
    out = build_homepage(sections, date_str="2026-08-01")
    assert "今日焦点" in out
    assert "DeepSeek 发布" in out
    assert "休达越境" in out
    assert "PMI 49.4" in out
    assert "长读一篇" in out
    assert "/ai/2026-08-01/" in out
    assert "/deep/2026-08-01/" in out
    assert "AI与科技" in out
    assert "focus-ai" in out
    assert "section-grid" in out
    assert "section-card-deep" in out
    assert "上证" in out  # market quote summary
    assert "date: 2026-08-01T00:00:00+0800" in out


def test_build_homepage_degraded_section(tmp_path):
    sections = {
        "ai": {"name": "AI与科技", "url": "/ai/", "items": [{"title_zh": "X", "score": 9, "link": "l", "source": "S"}], "count": 1},
        "world": None,
        "market": None,
        "deep": None,
    }
    out = build_homepage(sections, date_str="2026-08-01")
    assert "今日生成异常" in out
    assert "AI与科技" in out
    assert "深度阅读与学习" in out


def test_market_focus_falls_back_to_quote(tmp_path):
    sections = {
        "market": {
            "name": "金融市场与股市",
            "url": "/market/2026-08-01/",
            "items": [],
            "count": 0,
            "quotes": [{"name": "上证指数", "price": 3225, "change_pct": 0.82, "amount": 8e11}],
        }
    }
    out = build_homepage(sections, date_str="2026-08-01")
    assert "上证指数" in out
