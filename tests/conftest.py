import sys
from pathlib import Path

import pytest

# 让 tests 能 import scripts 下的模块
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


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
