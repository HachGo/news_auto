"""预测覆盖的资产及其历史数据来源。

name 与 sources/eastmoney.py 的 QUOTES 展示名一致，便于和每日快照、行情问题对齐。
predictors 只放有样本外证据的信号（见 docs/superpowers/specs/2026-11-21-trends-forecasts-merge-design.md）：
- tsmom12 / tsmom3：时间序列动量（Moskowitz-Ooi-Pedersen 2012；Hurst-Ooi-Pedersen 2017），预期符号为正。
- rev1w：一周短期反转，A 股证据最强（Yue-Li-Ruan 2023），预期符号为负。
- vix_mr：波动率指数的均值回复，预期符号为负。
"""

GROUPS = {
    "us": {"zh": "美股", "en": "US stocks"},
    "cn": {"zh": "A股", "en": "China A-shares"},
    "hk": {"zh": "港股", "en": "Hong Kong"},
    "commodity": {"zh": "商品", "en": "Commodities"},
    "vol": {"zh": "波动率", "en": "Volatility"},
}

ASSETS = [
    {"key": "spx", "name": "标普500", "group": "us", "yahoo": "^GSPC", "predictors": ["tsmom12", "tsmom3"]},
    {"key": "ixic", "name": "纳斯达克", "group": "us", "yahoo": "^IXIC", "predictors": ["tsmom12", "tsmom3"]},
    {"key": "dji", "name": "道琼斯", "group": "us", "yahoo": "^DJI", "predictors": ["tsmom12", "tsmom3"]},
    {"key": "sse", "name": "上证指数", "group": "cn", "yahoo": "000001.SS", "sina": "sh000001", "eastmoney": "1.000001", "predictors": ["rev1w", "tsmom12"]},
    {"key": "szse", "name": "深证成指", "group": "cn", "yahoo": "399001.SZ", "sina": "sz399001", "eastmoney": "0.399001", "predictors": ["rev1w", "tsmom12"]},
    {"key": "chinext", "name": "创业板指", "group": "cn", "sina": "sz399006", "eastmoney": "0.399006", "predictors": ["rev1w", "tsmom12"]},
    {"key": "hsi", "name": "恒生指数", "group": "hk", "yahoo": "^HSI", "eastmoney": "100.HSI", "predictors": ["tsmom12", "tsmom3"]},
    {"key": "hstech", "name": "恒生科技", "group": "hk", "eastmoney": "124.HSTECH", "predictors": ["tsmom12", "tsmom3"]},
    {"key": "gold", "name": "黄金", "group": "commodity", "yahoo": "GC=F", "predictors": ["tsmom12", "tsmom3"]},
    {"key": "oil", "name": "原油", "group": "commodity", "yahoo": "CL=F", "predictors": ["tsmom12", "tsmom3"]},
    {"key": "vix", "name": "VIX", "group": "vol", "yahoo": "^VIX", "predictors": ["vix_mr"]},
]

# 交易日数：周 5 / 月 21 / 季度 63
HORIZONS = {"week": 5, "month": 21, "quarter": 63}
