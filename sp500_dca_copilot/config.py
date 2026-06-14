"""
Central configuration for the S&P 500 DCA Co-pilot.
All tunable parameters live here. Secrets come from environment variables.
"""

import os
from pathlib import Path

# Load .env file at import time (so any module importing config gets env vars)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv not installed; env vars must be set externally

# ── Paths ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output" / "reports"
SHILLER_CSV_PATH = DATA_DIR / "shiller_sp500_monthly.csv"
NEWS_FILE_PATH = DATA_DIR / "monthly_news.txt"

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── API Keys (from environment) ────────────────────────────────────
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# ── DeepSeek API ───────────────────────────────────────────────────
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"  # DeepSeek-V3, best cost/performance for monthly cron

# ── FRED Series IDs ────────────────────────────────────────────────
FRED_SERIES = {
    "sp500": "SP500",          # S&P 500 daily close (2016-06-13 onward)
    "usdcny": "DEXCHUS",       # China / U.S. Foreign Exchange Rate (CNY per 1 USD)
    "cpi": "CPIAUCSL",         # Consumer Price Index (monthly, 1982-84=100)
    "unrate": "UNRATE",        # Unemployment Rate (monthly, %)
    "fedfunds": "FEDFUNDS",    # Federal Funds Effective Rate (monthly, %)
    "gdp": "GDP",              # Gross Domestic Product (quarterly, billions)
}

# ── DCA Parameters ─────────────────────────────────────────────────
DEFAULT_MAX_MONTHLY_USD = 1000  # User can override via CLI --amount (this is the MAX)

# ── Smart DCA: PE Zone System ──────────────────────────────────────
# Three valuation zones. Tiers are stored as RATIOS of the user's max amount,
# so amounts scale automatically when the user changes --amount.
#
# Zone logic:
#   1. Determine zone by current CAPE value
#   2. Within zone, pick investment ratio by current drawdown tier
#   3. Actual USD = ratio × user's max_amount
#
# "PE" here refers to CAPE (Shiller Cyclically Adjusted PE).

PE_ZONES = {
    "bubble": {
        "cape_min": 32,          # CAPE >= 32 → 高估值泡沫区
        "label": "高估值泡沫区",
        "state_desc": "估值过高，风险聚集，强制缩减定投积攒子弹。",
        # (max_drawdown_pct, ratio_of_max)
        "tiers": [
            (5,   0.30),   # 回撤 0-5%:   30% of max
            (10,  0.40),   # 回撤 5-10%:  40% of max
            (20,  0.60),   # 回撤 10-20%: 60% of max
            (100, 1.00),   # 回撤 >20%:   100% of max
        ],
    },
    "fair": {
        "cape_min": 24,          # CAPE 24-31 → 合理估值区
        "cape_max": 31,
        "label": "合理估值区",
        "state_desc": "估值合理，按基础纪律机械扣款。",
        "tiers": [
            (5,   0.50),
            (10,  0.60),
            (20,  0.75),
            (100, 1.00),
        ],
    },
    "cheap": {
        "cape_max": 23,          # CAPE <= 23 → 低估值便宜区
        "label": "低估值便宜区",
        "state_desc": "估值极具吸引力，加大基础吸筹力度。",
        "tiers": [
            (5,   0.70),
            (10,  0.85),
            (100, 1.00),
        ],
    },
}

# ── Valuation Thresholds (CAPE percentile vs full Shiller history) ─
# "便宜" (cheap):     ≤ 30th percentile
# "合理" (fair):      30-70th percentile
# "偏贵" (expensive):  > 70th percentile
VALUATION_THRESHOLDS = {
    "cheap": 0.30,     # ≤ 30%
    "expensive": 0.70, # > 70%
}

# ── Historical Crash Reference Data ────────────────────────────────
# Used by the psychological-defense section when user portfolio is negative.
# Drawdowns measured from Shiller monthly real price data.
HISTORICAL_CRASHES = [
    {
        "name": "互联网泡沫破裂 (Dot-com Bust)",
        "period": "2000-03 to 2002-10",
        "peak_to_trough": "-44.1% (real, incl. dividends ~-39.8%)",
        "recovery_time": "~7 years (inflation-adjusted, to 2007)",
        "dca_benefit": "在此期间坚持每月定投的投资者，2007年收益率显著高于在顶点一次性买入者",
    },
    {
        "name": "全球金融危机 (Global Financial Crisis)",
        "period": "2007-10 to 2009-03",
        "peak_to_trough": "-52.0% (real, incl. dividends ~-47.7%)",
        "recovery_time": "~5 years (inflation-adjusted, to 2012)",
        "dca_benefit": "2009年3月低谷时买入的筹码，到2010年底已翻倍；坚持定投者在2012年实现正回报",
    },
    {
        "name": "新冠疫情崩盘 (COVID-19 Crash)",
        "period": "2020-02 to 2020-03",
        "peak_to_trough": "-19.8% (nominal, extremely fast)",
        "recovery_time": "~5 months (史上最快复苏之一)",
        "dca_benefit": "在2020年3-4月坚持定投的投资者，年底即获得显著正收益",
    },
    {
        "name": "加息周期回调 (Fed Tightening Correction)",
        "period": "2022-01 to 2022-10",
        "peak_to_trough": "-19.4% (nominal)",
        "recovery_time": "~15 months (to 2024-01)",
        "dca_benefit": "2022年坚持定投者在2024年实现显著正回报，证明加息周期中纪律的价值",
    },
]

# ── 30-Year Backtest Summary (pre-computed, verified 2026-06-14) ──
BACKTEST_SUMMARY = {
    "period": "1996-2026",
    "fixed_dca": {
        "invested_cny": 450_000,
        "final_value_cny": 2_051_442,
        "xirr": "8.81%",
    },
    "smart_dca": {
        "invested_cny": 596_000,
        "final_value_cny": 2_891_177,
        "xirr": "9.02%",
    },
    "smart_outperformance_cny": 839_736,
    "note": "收益率为价格回报（不含股息），真实总回报约+1.5-2%/年",
}

# ── Report Output ──────────────────────────────────────────────────
REPORT_FILENAME_FORMAT = "{year}-{month:02d}.md"  # e.g. "2026-06.md"
