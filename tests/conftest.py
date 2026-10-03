import sys
from pathlib import Path

# 让 tests 能 import scripts 下的模块
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


import pytest


@pytest.fixture(autouse=True)
def offline_idea_sources(monkeypatch):
    """主流程测试不访问真实创意来源；需要来源的测试显式传入。"""
    import ideas
    monkeypatch.setattr(ideas, "SOURCES", {})
