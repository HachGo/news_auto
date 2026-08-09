"""趋势研判模块。

该包只处理结构化的趋势数据，不参与日报 Markdown 的渲染。
"""

from .pipeline import run

__all__ = ["run"]
