"""趋势模块的版本化配置。

权重集中在这里，避免散落在计算代码中。改动权重时应同步提升
METRIC_VERSION，并在历史快照中保留该版本。
"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = 1
PIPELINE_VERSION = "trend-v1"
METRIC_VERSION = "metric-v1"
TAXONOMY_VERSION = "taxonomy-v1"

TOPICS = {
    "foundation_models": {
        "name": "基础模型",
        "keywords": ["大模型", "基础模型", "foundation model", "LLM", "GPT", "DeepSeek", "Claude", "Gemini", "Qwen", "Kimi"],
    },
    "chips_compute": {
        "name": "芯片与算力",
        "keywords": ["芯片", "GPU", "NPU", "算力", "数据中心", "存储", "HBM", "半导体", "Nvidia", "AMD", "TSMC"],
    },
    "applications": {
        "name": "AI 应用与商业化",
        "keywords": ["AI应用", "人工智能应用", "agent", "智能体", "copilot", "商业化", "企业采用", "推理成本"],
    },
    "open_source": {
        "name": "开源生态",
        "keywords": ["开源", "open source", "open-weight", "开放权重", "Hugging Face", "llama.cpp", "模型权重"],
    },
    "funding_ma": {
        "name": "融资与并购",
        "keywords": ["融资", "并购", "收购", "IPO", "估值", "venture capital", "funding", "acquisition"],
    },
    "policy_safety": {
        "name": "政策、安全与监管",
        "keywords": ["监管", "政策", "安全", "安全性", "风险", "合规", "法案", "regulation", "safety", "security"],
    },
}

SOURCE_QUALITY = {
    "官方": 1.0,
    "公告": 0.95,
    "主流媒体": 0.85,
    "研究机构": 0.8,
    "社区": 0.55,
    "聚合": 0.45,
}

MARKET_COMPONENT_WEIGHTS = {
    "cross_asset_momentum": 0.30,
    "volatility": 0.20,
    "liquidity": 0.20,
    "macro_risk": 0.15,
    "news_risk": 0.15,
}

PERIOD_REQUIREMENTS = {
    "week": {"days": 7, "min_news_days": 5, "min_market_sessions": 3},
    "month": {"days": 30, "min_news_days": 21, "min_market_sessions": 15},
    "quarter": {"days": 91, "min_news_days": 56, "min_market_sessions": 45},
    "year": {"days": 365, "min_news_days": 274, "min_market_sessions": 180},
}


@dataclass(frozen=True)
class DataQuality:
    status: str
    ratio: float
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"status": self.status, "ratio": round(self.ratio, 4), "warnings": list(self.warnings)}
