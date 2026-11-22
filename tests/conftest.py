import sys
from pathlib import Path

import pytest

# 让 tests 能 import scripts 下的模块
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(autouse=True)
def offline_idea_sources(monkeypatch):
    """主流程测试不访问真实创意来源；需要来源的测试显式传入。"""
    import ideas
    monkeypatch.setattr(ideas, "SOURCES", {})


@pytest.fixture(autouse=True)
def offline_price_history(monkeypatch):
    """主流程测试不下载历史日 K；需要行情的测试显式传入 fetcher。"""
    from outlook import history
    monkeypatch.setattr(history, "fetch", lambda asset, start: [])
    monkeypatch.setattr(history, "FETCHERS", ())


@pytest.fixture(autouse=True)
def offline_revolution_sources(monkeypatch):
    """观测台数据源默认离线：抓取失败、沿用缓存；需要数据的测试显式传入 fetcher。"""
    from revolution import sources

    def offline(key, root):
        raise RuntimeError("offline in tests")
    monkeypatch.setattr(sources, "fetch_raw", offline)


@pytest.fixture
def fake_summaries():
    """批量摘要替身：给每条打上可预期的中文标题/摘要，返回成功条数。

    版面生成器现在统一走 common.apply_summaries 批量摘要，测试用它替代真实 LLM。
    """
    def apply(client, items, **kwargs):
        items = list(items)
        for item in items:
            item.update({
                "title_zh": f"中文-{item['title']}",
                "summary_zh": f"摘要-{item['title']}",
            })
        return len(items)

    return apply
