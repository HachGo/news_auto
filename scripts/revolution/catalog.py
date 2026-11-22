"""指标目录：每个序列的来源、发布频率、发布滞后、证据类别，以及是否进入 D/B/S/C 指数。

证据类别（kind）——页面上每条线都按它标注：
- observed：真实观测。直接度量所述对象的官方或公司披露数据（如云厂商资本开支、金融状况指数）。
- proxy：代理估算。数据本身是真实观测，但被用来近似一个不可直接观测的概念（如用计算机系统设计业就业近似 AI 采用扩散）。
- research：历史研究示意。研究机构整理或估算的数据，会回溯修订（如 Epoch AI 的训练算力估计）；历史对齐类的分析视图也归此类。
- model：模型预测。本模块生成的预测，均标注基准、回测与上线状态。

发布滞后（lag_days）：观测期结束到数据公开的大致天数，用于时间轴回放时判断「当时能看到什么」。
回放使用最新修订值（非实时版本），页面注明这一点。
"""

from __future__ import annotations

INDICES = {
    "D": {"zh": "采用扩散", "en": "Diffusion",
          "desc": {"zh": "AI 在企业与劳动力市场中的扩散程度。目前只有代理指标，覆盖较弱。",
                   "en": "How far AI is spreading through firms and the labor market. Proxies only for now; coverage is thin."}},
    "B": {"zh": "资本与基建", "en": "Build-out",
          "desc": {"zh": "云厂商资本开支、信息处理设备与软件投资的增速。",
                   "en": "Growth in hyperscaler capex and in investment in information-processing equipment and software."}},
    "S": {"zh": "金融压力", "en": "Stress",
          "desc": {"zh": "金融状况与压力指数，以及半导体板块相对长期趋势的偏离。越高越紧张。",
                   "en": "Financial conditions and stress indices, plus how far semiconductor stocks sit above their long-run trend. Higher means more strain."}},
    "C": {"zh": "能力与算力", "en": "Capability",
          "desc": {"zh": "前沿模型训练算力的年增长与半导体产出增速。",
                   "en": "Year-on-year growth of frontier training compute and of semiconductor output."}},
}
INDEX_ORDER = ["D", "B", "S", "C"]

FREQ_LABEL = {
    "daily": {"zh": "日度", "en": "Daily"},
    "weekly": {"zh": "周度", "en": "Weekly"},
    "monthly": {"zh": "月度", "en": "Monthly"},
    "quarterly": {"zh": "季度", "en": "Quarterly"},
    "event": {"zh": "不定期（按模型发布）", "en": "Irregular (per model release)"},
}
KIND_LABEL = {
    "observed": {"zh": "真实观测", "en": "Observed"},
    "proxy": {"zh": "代理估算", "en": "Proxy"},
    "research": {"zh": "历史研究示意", "en": "Research / illustrative"},
    "model": {"zh": "模型预测", "en": "Model forecast"},
}

FRED = "https://fred.stlouisfed.org/series/"

# 原始序列：抓取单位。fetch 取值 fred / edgar / epoch / yahoo / local（读 history/ 下已有缓存）。
RAW = {
    "NFCI": {"fetch": "fred", "id": "NFCI"},
    "STLFSI4": {"fetch": "fred", "id": "STLFSI4"},
    "HY": {"fetch": "fred", "id": "BAMLH0A0HYM2"},
    "INFO_EQUIP": {"fetch": "fred", "id": "Y033RC1Q027SBEA"},
    "SOFTWARE": {"fetch": "fred", "id": "B985RC1Q027SBEA"},
    "GDP": {"fetch": "fred", "id": "GDP"},
    "CSD_EMP": {"fetch": "fred", "id": "CES6054150001"},
    "SOFTDEV_POSTINGS": {"fetch": "fred", "id": "IHLIDXUSTPSOFTDEVE"},
    "SEMIS_IP": {"fetch": "fred", "id": "IPG3344S"},
    "CAPEX_MSFT": {"fetch": "edgar", "cik": 789019, "tags": ["PaymentsToAcquirePropertyPlantAndEquipment"]},
    # Alphabet 2015 年重组前的历史在 Google Inc. 旧 CIK 下
    "CAPEX_GOOGL": {"fetch": "edgar", "cik": [1652044, 1288776], "tags": ["PaymentsToAcquirePropertyPlantAndEquipment"]},
    # 亚马逊 2017 年起改用 PaymentsToAcquireProductiveAssets（含融资租赁以外的生产性资产购置）
    "CAPEX_AMZN": {"fetch": "edgar", "cik": 1018724, "tags": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]},
    "CAPEX_META": {"fetch": "edgar", "cik": 1326801, "tags": ["PaymentsToAcquirePropertyPlantAndEquipment"]},
    "EPOCH": {"fetch": "epoch"},
    "SOX": {"fetch": "yahoo", "symbol": "^SOX"},
    "VIX": {"fetch": "local", "key": "vix"},
}

CAPEX_COMPANIES = [("CAPEX_MSFT", "Microsoft"), ("CAPEX_GOOGL", "Alphabet"), ("CAPEX_AMZN", "Amazon"), ("CAPEX_META", "Meta")]

# 指标：页面展示与指数计算的单位。transform 在 series.py 中实现。
# index：所属指数（None 表示只展示不入指数）；sign：入指数时的方向（+1 越高指数越高）。
# forecast：成分级预测的周期（按该指标自身频率计）；event：阈值概率问题。
INDICATORS = [
    {"id": "d_csd_emp", "raw": "CSD_EMP", "transform": "yoy", "freq": "monthly", "kind": "proxy", "index": "D", "sign": 1,
     "unit": "%", "lag_days": 7, "forecast": [1, 3],
     "name": {"zh": "计算机系统设计业就业（同比）", "en": "Computer systems design employment (YoY)"},
     "source": {"name": "BLS CES via FRED", "url": FRED + "CES6054150001"},
     "note": {"zh": "代理：AI 落地主要经由软件与系统集成服务，但该行业就业也受一般 IT 周期影响。",
              "en": "Proxy: AI deployment runs largely through software and integration services, but this payroll also tracks the general IT cycle."}},
    {"id": "d_softdev_postings", "raw": "SOFTDEV_POSTINGS", "transform": "level", "freq": "daily", "kind": "proxy", "index": None, "sign": 0,
     "unit": "2020-02-01=100", "lag_days": 3, "forecast": [],
     "name": {"zh": "Indeed 软件开发岗位发布指数", "en": "Indeed software development job postings"},
     "source": {"name": "Indeed Hiring Lab via FRED", "url": FRED + "IHLIDXUSTPSOFTDEVE"},
     "note": {"zh": "只展示、不入指数：AI 既可能增加也可能替代开发岗位，方向无法事先确定。2020 年起才有数据。",
              "en": "Shown, not indexed: AI may add or replace developer roles, so its sign is not known in advance. Data starts in 2020."}},

    {"id": "b_capex", "raw": "CAPEX_TOTAL", "transform": "yoy", "freq": "quarterly", "kind": "observed", "index": "B", "sign": 1,
     "unit": "%", "lag_days": 40, "forecast": [1, 2],
     "name": {"zh": "四大云厂商资本开支（同比）", "en": "Big-four hyperscaler capex (YoY)"},
     "source": {"name": "SEC EDGAR XBRL（10-Q / 10-K 现金流量表）", "url": "https://www.sec.gov/edgar/sec-api-documentation"},
     "note": {"zh": "微软、Alphabet、亚马逊、Meta 的购置物业与设备现金支出，按自然季度相加；单季由年初至今累计值相减得到。各公司口径（是否含融资租赁）不同。",
              "en": "Cash paid for property and equipment by Microsoft, Alphabet, Amazon and Meta, summed by calendar quarter; single quarters are derived from year-to-date filings. Definitions (e.g. finance leases) differ by company."}},
    {"id": "b_info_equip", "raw": "INFO_EQUIP", "transform": "yoy", "freq": "quarterly", "kind": "observed", "index": "B", "sign": 1,
     "unit": "%", "lag_days": 30, "forecast": [1, 2],
     "name": {"zh": "美国信息处理设备投资（同比）", "en": "US investment in information-processing equipment (YoY)"},
     "source": {"name": "BEA NIPA via FRED", "url": FRED + "Y033RC1Q027SBEA"},
     "note": {"zh": "名义值、季调年化。包括服务器、计算机与通信设备，不只是 AI。", "en": "Nominal, seasonally adjusted annual rate. Covers servers, computers and communications gear, not only AI."}},
    {"id": "b_software", "raw": "SOFTWARE", "transform": "yoy", "freq": "quarterly", "kind": "observed", "index": "B", "sign": 1,
     "unit": "%", "lag_days": 30, "forecast": [1, 2],
     "name": {"zh": "美国软件投资（同比）", "en": "US software investment (YoY)"},
     "source": {"name": "BEA NIPA via FRED", "url": FRED + "B985RC1Q027SBEA"},
     "note": {"zh": "名义值、季调年化。", "en": "Nominal, seasonally adjusted annual rate."}},

    {"id": "s_nfci", "raw": "NFCI", "transform": "level", "freq": "weekly", "kind": "observed", "index": "S", "sign": 1,
     "unit": "σ", "lag_days": 5, "forecast": [4, 13], "event": {"h": 13, "above": 0.0},
     "name": {"zh": "芝加哥联储全国金融状况指数 NFCI", "en": "Chicago Fed National Financial Conditions Index (NFCI)"},
     "source": {"name": "Chicago Fed via FRED", "url": FRED + "NFCI"},
     "note": {"zh": "0 为历史平均，正值表示金融状况偏紧。", "en": "Zero is the historical average; positive means tighter than average."}},
    {"id": "s_stlfsi", "raw": "STLFSI4", "transform": "level", "freq": "weekly", "kind": "observed", "index": "S", "sign": 1,
     "unit": "σ", "lag_days": 6, "forecast": [4, 13], "event": {"h": 13, "above": 0.0},
     "name": {"zh": "圣路易斯联储金融压力指数 STLFSI4", "en": "St. Louis Fed Financial Stress Index (STLFSI4)"},
     "source": {"name": "St. Louis Fed via FRED", "url": FRED + "STLFSI4"},
     "note": {"zh": "0 为正常水平，正值表示压力高于平均。", "en": "Zero is normal; positive means above-average stress."}},
    {"id": "s_sox_heat", "raw": "SOX", "transform": "dev3y", "freq": "daily", "kind": "proxy", "index": "S", "sign": 1,
     "unit": "%", "lag_days": 0, "forecast": [],
     "name": {"zh": "费城半导体指数相对三年均线偏离", "en": "PHLX Semiconductor index vs. 3-year average"},
     "source": {"name": "Yahoo Finance ^SOX", "url": "https://finance.yahoo.com/quote/%5ESOX/"},
     "note": {"zh": "代理：没有可免费获取的板块盈利数据，用价格偏离长期均线近似估值过热，不是市盈率。价格类指标不做预测，见资产走势预测。",
              "en": "Proxy: no free sector-earnings feed, so distance from the long-run average stands in for valuation heat. Not a P/E. Prices are not forecast here; see the asset outlook."}},
    {"id": "s_hy", "raw": "HY", "transform": "level", "freq": "daily", "kind": "observed", "index": None, "sign": 0,
     "unit": "pp", "lag_days": 1, "forecast": [],
     "name": {"zh": "美国高收益债期权调整利差", "en": "US high-yield option-adjusted spread"},
     "source": {"name": "ICE BofA via FRED", "url": FRED + "BAMLH0A0HYM2"},
     "note": {"zh": "只展示、不入指数：FRED 只提供最近三年数据，不足以标准化。", "en": "Shown, not indexed: FRED only serves the last three years, too short to standardize."}},
    {"id": "s_vix", "raw": "VIX", "transform": "level", "freq": "daily", "kind": "observed", "index": None, "sign": 0,
     "unit": "pt", "lag_days": 0, "forecast": [],
     "name": {"zh": "VIX 波动率指数", "en": "VIX volatility index"},
     "source": {"name": "Cboe（经资产走势模块缓存）", "url": "https://www.cboe.com/tradable_products/vix/"},
     "note": {"zh": "只展示：NFCI 已包含波动率成分，避免重复计入。", "en": "Shown only: NFCI already includes volatility, so it is not counted twice."}},

    {"id": "c_frontier", "raw": "EPOCH", "transform": "frontier_chg12", "freq": "event", "kind": "research", "index": "C", "sign": 1,
     "unit": "OOM/yr", "lag_days": 0, "forecast": [],
     "name": {"zh": "前沿训练算力年增长（数量级）", "en": "Frontier training compute growth (orders of magnitude per year)"},
     "source": {"name": "Epoch AI · Notable AI Models", "url": "https://epoch.ai/data/notable-ai-models"},
     "note": {"zh": "研究估算：训练算力多为 Epoch AI 根据论文与公开信息估计，置信度不一，数据会回溯补录。不做预测。",
              "en": "Research estimate: most compute figures are Epoch AI estimates from papers and public information, with varying confidence, and are backfilled. Not forecast."}},
    {"id": "c_semis_ip", "raw": "SEMIS_IP", "transform": "yoy", "freq": "monthly", "kind": "proxy", "index": "C", "sign": 1,
     "unit": "%", "lag_days": 17, "forecast": [1, 3],
     "name": {"zh": "美国半导体及电子元件产出（同比）", "en": "US semiconductor and electronic component output (YoY)"},
     "source": {"name": "Federal Reserve G.17 via FRED", "url": FRED + "IPG3344S"},
     "note": {"zh": "代理：算力供给的一部分；全球芯片产能主要在美国以外。", "en": "Proxy for part of compute supply; most global chip capacity sits outside the US."}},
]

# 已规划、尚未接入的数据：页面如实列出，不用其他数据填补
PENDING = [
    {"index": "D", "name": {"zh": "美国人口普查局 BTOS 企业 AI 使用率（双周）", "en": "Census BTOS business AI use rate (biweekly)"},
     "url": "https://www.census.gov/hfp/btos/data", "reason": {"zh": "无稳定的机器可读接口，待接入。", "en": "No stable machine-readable endpoint yet."}},
    {"index": "B", "name": {"zh": "数据中心建设支出（月度）", "en": "Data center construction spending (monthly)"},
     "url": "https://www.census.gov/construction/c30/", "reason": {"zh": "Census 明细表格式待解析。", "en": "Census detail tables still to be parsed."}},
    {"index": "C", "name": {"zh": "数据中心用电（EIA）", "en": "Data center electricity use (EIA)"},
     "url": "https://www.eia.gov/opendata/", "reason": {"zh": "EIA 接口需要 API Key。", "en": "The EIA API requires a key."}},
]

# 历史事件标记：只收日期与事实可核验的事件
EVENTS = [
    {"date": "2000-03-10", "type": "market", "title": {"zh": "纳斯达克见顶，互联网泡沫破裂开始", "en": "Nasdaq peaks; the dot-com bust begins"},
     "url": "https://en.wikipedia.org/wiki/Dot-com_bubble"},
    {"date": "2007-08-09", "type": "market", "title": {"zh": "法国巴黎银行冻结基金赎回，次贷危机蔓延", "en": "BNP Paribas freezes funds as subprime crisis spreads"},
     "url": "https://en.wikipedia.org/wiki/2007%E2%80%932008_financial_crisis"},
    {"date": "2008-09-15", "type": "market", "title": {"zh": "雷曼兄弟破产", "en": "Lehman Brothers collapses"},
     "url": "https://en.wikipedia.org/wiki/Bankruptcy_of_Lehman_Brothers"},
    {"date": "2017-06-12", "type": "model", "title": {"zh": "Transformer 论文发布", "en": "Transformer paper published"},
     "url": "https://arxiv.org/abs/1706.03762"},
    {"date": "2020-03-16", "type": "market", "title": {"zh": "新冠疫情冲击：美股熔断、美联储降息至零", "en": "COVID shock: US circuit breakers, Fed cuts to zero"},
     "url": "https://en.wikipedia.org/wiki/2020_stock_market_crash"},
    {"date": "2020-05-28", "type": "model", "title": {"zh": "GPT-3 论文发布", "en": "GPT-3 paper published"},
     "url": "https://arxiv.org/abs/2005.14165"},
    {"date": "2022-03-16", "type": "policy", "title": {"zh": "美联储开启本轮加息", "en": "Fed begins hiking cycle"},
     "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary20220316a.htm"},
    {"date": "2022-10-07", "type": "policy", "title": {"zh": "美国首轮先进芯片出口管制", "en": "First US advanced-chip export controls"},
     "url": "https://www.bis.doc.gov/index.php/documents/about-bis/newsroom/press-releases/3158-2022-10-07-bis-press-release-advanced-computing-and-semiconductor-manufacturing-controls-final/file"},
    {"date": "2022-11-30", "type": "model", "title": {"zh": "ChatGPT 发布", "en": "ChatGPT launched"},
     "url": "https://openai.com/index/chatgpt/"},
    {"date": "2023-03-10", "type": "market", "title": {"zh": "硅谷银行倒闭", "en": "Silicon Valley Bank fails"},
     "url": "https://en.wikipedia.org/wiki/Collapse_of_Silicon_Valley_Bank"},
    {"date": "2023-03-14", "type": "model", "title": {"zh": "GPT-4 发布", "en": "GPT-4 released"},
     "url": "https://openai.com/index/gpt-4-research/"},
    {"date": "2023-05-24", "type": "capital", "title": {"zh": "英伟达数据中心指引大幅上调", "en": "Nvidia's data-center guidance jumps"},
     "url": "https://en.wikipedia.org/wiki/Nvidia"},
    {"date": "2023-10-17", "type": "policy", "title": {"zh": "美国扩大 AI 芯片出口管制", "en": "US widens AI-chip export controls"},
     "url": "https://en.wikipedia.org/wiki/United_States_New_Export_Controls_on_Advanced_Computing_and_Semiconductors_to_China"},
    {"date": "2024-08-05", "type": "market", "title": {"zh": "日元套息交易平仓引发全球股市急跌", "en": "Yen carry-trade unwind hits global stocks"},
     "url": "https://en.wikipedia.org/wiki/2024_stock_market_crash"},
    {"date": "2025-01-21", "type": "capital", "title": {"zh": "Stargate 数据中心计划宣布", "en": "Stargate data-center project announced"},
     "url": "https://openai.com/index/announcing-the-stargate-project/"},
    {"date": "2025-01-27", "type": "market", "title": {"zh": "DeepSeek-R1 引发 AI 股抛售", "en": "DeepSeek-R1 triggers AI stock sell-off"},
     "url": "https://en.wikipedia.org/wiki/DeepSeek"},
    {"date": "2025-04-02", "type": "policy", "title": {"zh": "美国宣布全面对等关税", "en": "US announces sweeping reciprocal tariffs"},
     "url": "https://en.wikipedia.org/wiki/Liberation_Day_tariffs"},
]
EVENT_TYPES = {
    "model": {"zh": "模型", "en": "Model"},
    "capital": {"zh": "资本", "en": "Capital"},
    "policy": {"zh": "政策", "en": "Policy"},
    "market": {"zh": "市场", "en": "Market"},
}


def indicator(ind_id):
    return next(item for item in INDICATORS if item["id"] == ind_id)
