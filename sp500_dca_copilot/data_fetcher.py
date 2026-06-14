"""
Data pipeline for the S&P 500 DCA Co-pilot.
Combines FRED API (real-time S&P 500, USD/CNY) with Shiller CSV (CAPE, history).
"""

import io
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

from .config import (
    FRED_API_KEY,
    FRED_SERIES,
    SHILLER_CSV_PATH,
    VALUATION_THRESHOLDS,
    HISTORICAL_CRASHES,
    PE_ZONES,
)

logger = logging.getLogger(__name__)

# ── FRED API ───────────────────────────────────────────────────────

FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


def _fetch_fred(series_id: str, limit: int = 60, sort: str = "desc") -> pd.DataFrame:
    """
    Fetch observations for a FRED series.
    Returns DataFrame with columns: date (datetime), value (float).
    Raises RuntimeError if API call fails.
    """
    if not FRED_API_KEY:
        raise RuntimeError(
            "FRED_API_KEY environment variable is not set. "
            "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
        )

    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "sort_order": sort,
        "limit": limit,
    }
    resp = requests.get(FRED_BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "observations" not in data:
        raise RuntimeError(f"FRED returned unexpected format for {series_id}: {data}")

    records = []
    for obs in data["observations"]:
        if obs["value"] == ".":  # FRED uses "." for missing values
            continue
        records.append({"date": pd.to_datetime(obs["date"]), "value": float(obs["value"])})

    if not records:
        raise RuntimeError(f"No valid observations returned for FRED series {series_id}")

    df = pd.DataFrame(records)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def fetch_sp500_latest() -> dict:
    """
    Fetch the latest S&P 500 price from FRED.
    Returns dict with keys: date, price, series_id.
    """
    df = _fetch_fred(FRED_SERIES["sp500"], limit=5, sort="desc")
    latest = df.iloc[-1]
    logger.info(f"S&P 500: {latest['value']:.2f} on {latest['date'].strftime('%Y-%m-%d')}")
    return {
        "date": latest["date"],
        "price": latest["value"],
        "series_id": FRED_SERIES["sp500"],
    }


def fetch_exchange_rate() -> dict:
    """
    Fetch the latest USD/CNY exchange rate from FRED, plus the rate from ~30 days ago.
    Returns dict: current_rate, current_date, prev_rate, prev_date, change_pct.
    Positive change_pct = USD strengthened vs CNY (more CNY per USD).
    """
    # Fetch last 60 days to safely get the ~30-day-ago value
    df = _fetch_fred(FRED_SERIES["usdcny"], limit=60, sort="desc")
    df = df.sort_values("date").reset_index(drop=True)

    if len(df) < 2:
        raise RuntimeError("Not enough exchange rate data from FRED")

    current = df.iloc[-1]
    # Find the observation closest to 30 days before the current one
    target_date = current["date"] - timedelta(days=30)
    # Exclude the current row itself
    candidates = df[df["date"] < current["date"]].copy()
    if candidates.empty:
        prev = df.iloc[-2]
    else:
        # Pick the row closest to target_date
        candidates["date_diff"] = abs((candidates["date"] - target_date).dt.days)
        prev = candidates.loc[candidates["date_diff"].idxmin()]

    change_pct = ((current["value"] - prev["value"]) / prev["value"]) * 100

    logger.info(
        f"USD/CNY: {current['value']:.4f} ({(current['date']).strftime('%Y-%m-%d')}) "
        f"vs {prev['value']:.4f} ({prev['date'].strftime('%Y-%m-%d')}), "
        f"change: {change_pct:+.2f}%"
    )

    return {
        "current_rate": current["value"],
        "current_date": current["date"],
        "prev_rate": prev["value"],
        "prev_date": prev["date"],
        "change_pct": round(change_pct, 2),
    }


def fetch_macro_indicators() -> dict:
    """
    Fetch key macro indicators from FRED: CPI (YoY inflation), unemployment rate,
    federal funds rate, and GDP. Returns a dict ready for the report prompt.
    """
    indicators = {}

    # ── CPI (YoY inflation rate) ──────────────────────────────────
    try:
        df_cpi = _fetch_fred(FRED_SERIES["cpi"], limit=24, sort="desc")
        df_cpi = df_cpi.sort_values("date").reset_index(drop=True)
        latest_cpi = df_cpi.iloc[-1]
        # Find CPI from 12 months ago
        target_date = latest_cpi["date"] - timedelta(days=365)
        df_cpi["date_diff"] = abs((df_cpi["date"] - target_date).dt.days)
        cpi_prev = df_cpi.loc[df_cpi["date_diff"].idxmin()]
        cpi_yoy = ((latest_cpi["value"] - cpi_prev["value"]) / cpi_prev["value"]) * 100
        indicators["cpi"] = {
            "latest_value": round(latest_cpi["value"], 1),
            "latest_date": latest_cpi["date"],
            "yoy_change_pct": round(cpi_yoy, 2),
            "prev_year_value": round(cpi_prev["value"], 1),
        }
        logger.info(f"CPI: {latest_cpi['value']} (YoY: {cpi_yoy:+.2f}%)")
    except Exception as e:
        logger.warning(f"Failed to fetch CPI: {e}")
        indicators["cpi"] = None

    # ── Unemployment Rate ─────────────────────────────────────────
    try:
        df_unrate = _fetch_fred(FRED_SERIES["unrate"], limit=3, sort="desc")
        df_unrate = df_unrate.sort_values("date").reset_index(drop=True)
        latest = df_unrate.iloc[-1]
        indicators["unrate"] = {
            "value": latest["value"],
            "date": latest["date"],
        }
        logger.info(f"Unemployment Rate: {latest['value']}%")
    except Exception as e:
        logger.warning(f"Failed to fetch UNRATE: {e}")
        indicators["unrate"] = None

    # ── Federal Funds Rate ────────────────────────────────────────
    try:
        df_fed = _fetch_fred(FRED_SERIES["fedfunds"], limit=3, sort="desc")
        df_fed = df_fed.sort_values("date").reset_index(drop=True)
        latest = df_fed.iloc[-1]
        indicators["fedfunds"] = {
            "value": latest["value"],
            "date": latest["date"],
        }
        logger.info(f"Fed Funds Rate: {latest['value']}%")
    except Exception as e:
        logger.warning(f"Failed to fetch FEDFUNDS: {e}")
        indicators["fedfunds"] = None

    # ── GDP (quarterly) ───────────────────────────────────────────
    try:
        df_gdp = _fetch_fred(FRED_SERIES["gdp"], limit=6, sort="desc")
        df_gdp = df_gdp.sort_values("date").reset_index(drop=True)
        latest = df_gdp.iloc[-1]
        # Try to get previous quarter for QoQ change
        prev_q = df_gdp.iloc[-2] if len(df_gdp) >= 2 else None
        gdp_qoq = None
        if prev_q is not None:
            gdp_qoq = ((latest["value"] - prev_q["value"]) / prev_q["value"]) * 100
        indicators["gdp"] = {
            "value": latest["value"],
            "date": latest["date"],
            "qoq_change_pct": round(gdp_qoq, 2) if gdp_qoq is not None else None,
        }
        logger.info(f"GDP: {latest['value']:.1f}B (QoQ: {gdp_qoq:+.2f}%)" if gdp_qoq else f"GDP: {latest['value']:.1f}B")
    except Exception as e:
        logger.warning(f"Failed to fetch GDP: {e}")
        indicators["gdp"] = None

    return indicators


# ── Shiller CSV (CAPE / PE Ratio) ──────────────────────────────────

# Column names for the processed Shiller CSV (matches download_shiller_data.py output)
SHILLER_COLUMNS = [
    "Date",           # Fractional year (e.g. 2026.46)
    "SP500_Price",    # Nominal S&P 500 price
    "Dividend",       # Nominal dividend
    "Earnings",       # Nominal earnings
    "CPI",            # Consumer Price Index
    "Long_Rate",      # Long-term interest rate
    "Real_Price",     # Inflation-adjusted S&P 500 price
    "Real_Dividend",  # Inflation-adjusted dividend
    "Real_Earnings",  # Inflation-adjusted earnings
    "CAPE",           # Cyclically Adjusted PE Ratio (Shiller PE)
]


def load_shiller_data() -> pd.DataFrame:
    """
    Load Shiller monthly data from CSV.
    If the CSV doesn't exist, raises FileNotFoundError with instructions.
    Returns DataFrame with standardized columns.
    """
    if not SHILLER_CSV_PATH.exists():
        raise FileNotFoundError(
            f"Shiller data not found at {SHILLER_CSV_PATH}.\n"
            "Please download it first. Options:\n"
            "  1. Run: python -m sp500_dca_copilot.download_shiller_data\n"
            "  2. Or manually download from http://www.econ.yale.edu/~shiller/data/ie_data.xls\n"
            "     and save the processed CSV to that path."
        )

    df = pd.read_csv(SHILLER_CSV_PATH)

    # Standardize column names (handle variations)
    col_map = {}
    for col in df.columns:
        col_lower = col.strip().lower().replace(" ", "_").replace(".", "_")
        for std in SHILLER_COLUMNS:
            if std.lower().replace(" ", "_").replace(".", "_") == col_lower:
                col_map[col] = std
                break
    if col_map:
        df = df.rename(columns=col_map)

    # Add a proper datetime column from fractional year
    if "Date" in df.columns and "date" not in df.columns:
        df["date"] = df["Date"].apply(_fractional_year_to_datetime)

    df = df.sort_values("date").reset_index(drop=True)
    logger.info(f"Loaded Shiller data: {len(df)} rows, {df['date'].min()} to {df['date'].max()}")
    return df


def _fractional_year_to_datetime(year_frac: float) -> datetime:
    """
    Convert Shiller fractional year to datetime.
    Shiller format: 2023.09 means September 2023 (NOT 9% through the year).
    The fractional part encodes the month directly: .01=Jan, .02=Feb, ..., .12=Dec.
    """
    year = int(year_frac)
    month = int(round((year_frac - year) * 100))
    month = max(1, min(12, month))
    return datetime(year, month, 15)


def calculate_cape_percentile(current_cape: float, shiller_df: pd.DataFrame) -> dict:
    """
    Calculate where the current CAPE falls in the historical distribution.
    Returns dict with current_cape, percentile, median, min, max, and valuation label.
    """
    cape_series = shiller_df["CAPE"].dropna()
    if cape_series.empty:
        raise ValueError("No valid CAPE data in Shiller CSV")

    percentile = (cape_series < current_cape).sum() / len(cape_series)

    if percentile <= VALUATION_THRESHOLDS["cheap"]:
        valuation = "便宜 (Undervalued)"
    elif percentile <= VALUATION_THRESHOLDS["expensive"]:
        valuation = "合理 (Fairly Valued)"
    else:
        valuation = "偏贵 (Expensive)"

    logger.info(
        f"CAPE: {current_cape:.2f} (percentile: {percentile:.1%}, "
        f"median: {cape_series.median():.2f}) → {valuation}"
    )

    return {
        "current_cape": round(current_cape, 2),
        "percentile": round(percentile * 100, 1),
        "median_cape": round(cape_series.median(), 2),
        "min_cape": round(cape_series.min(), 2),
        "max_cape": round(cape_series.max(), 2),
        "valuation_label": valuation,
        "data_start": shiller_df["date"].min().strftime("%Y-%m"),
        "data_end": shiller_df["date"].max().strftime("%Y-%m"),
    }


def calculate_current_drawdown(
    shiller_df: pd.DataFrame,
    current_nominal_price: float | None = None,
) -> dict:
    """
    Calculate the current drawdown from the all-time nominal high.
    Uses Shiller data for the historical peak, and the current FRED price
    (if provided) as the current reference point.
    Returns dict with drawdown_pct, peak_date, peak_price, current_price.
    """
    if "SP500_Price" not in shiller_df.columns:
        return {"drawdown_pct": None, "note": "Price data unavailable"}

    prices = shiller_df[["SP500_Price", "date"]].dropna()
    if prices.empty:
        return {"drawdown_pct": None, "note": "No price data"}

    # Find the all-time high from Shiller nominal price history
    peak_idx = prices["SP500_Price"].idxmax()
    peak_row = prices.loc[peak_idx]
    peak_price = peak_row["SP500_Price"]
    peak_date = peak_row["date"]

    # Use FRED current price if available, otherwise fall back to last Shiller price
    if current_nominal_price is not None:
        current_price = current_nominal_price
        current_date_str = "FRED (latest)"
    else:
        current_price = prices.iloc[-1]["SP500_Price"]
        current_date_str = prices.iloc[-1]["date"].strftime("%Y-%m-%d")

    drawdown_pct = (current_price - peak_price) / peak_price * 100

    # If current price exceeds historical peak, we're at a new ATH
    at_new_ath = current_price >= peak_price

    if at_new_ath:
        gain_from_peak = (current_price - peak_price) / peak_price * 100
        logger.info(
            f"Market at new all-time high: {current_price:.2f} [FRED], "
            f"+{gain_from_peak:.1f}% above Shiller-era peak "
            f"({peak_price:.2f} on {peak_date.strftime('%Y-%m-%d')})"
        )
        effective_drawdown = 0.0  # No drawdown when at ATH
    else:
        logger.info(
            f"Current drawdown from historical nominal ATH: {drawdown_pct:.1f}% "
            f"(historical peak: {peak_price:.2f} on {peak_date.strftime('%Y-%m-%d')}, "
            f"current: {current_price:.2f} [{current_date_str}])"
        )
        effective_drawdown = abs(drawdown_pct)  # Store as positive number

    return {
        "drawdown_pct": round(effective_drawdown, 1),
        "peak_date": peak_date,
        "peak_price": round(peak_price, 2),
        "current_price": round(current_price, 2),
        "at_all_time_high": at_new_ath,
    }


def get_crash_reference() -> list:
    """Return pre-computed historical crash data for psychological defense."""
    return HISTORICAL_CRASHES


def calculate_smart_dca_recommendation(
    drawdown_info: dict | None,
    cape_info: dict | None,
    max_amount_usd: float,
) -> dict:
    """
    PE Zone-based Smart DCA recommendation.

    Three valuation zones (CAPE = Shiller Cyclically Adjusted PE):
      - PE >= 26:  "泡沫区" — reduce to build cash reserves
      - PE 19-25:  "合理区" — mechanical execution
      - PE <= 18:  "便宜区" — increase base allocation

    Within each zone, drawdown determines the investment ratio.
    Actual USD = ratio × user's max_amount_usd.

    Returns dict with zone, invest_usd, ratio, state_desc, reasoning.
    """
    # ── Get current CAPE (PE) value and drawdown ─────────────────
    current_cape = None
    cape_percentile = None
    if cape_info:
        current_cape = cape_info.get("current_cape")
        cape_percentile = cape_info.get("percentile")

    drawdown_pct = 0.0
    at_ath = True
    if drawdown_info and drawdown_info.get("drawdown_pct") is not None:
        drawdown_pct = drawdown_info["drawdown_pct"]
        at_ath = drawdown_info.get("at_all_time_high", False)

    # ── Step 1: Determine PE zone ────────────────────────────────
    zone_key = "fair"       # default
    zone_config = None

    if current_cape is not None:
        bubble_cfg = PE_ZONES["bubble"]
        cheap_cfg = PE_ZONES["cheap"]
        fair_cfg = PE_ZONES["fair"]

        if current_cape >= bubble_cfg["cape_min"]:
            zone_key = "bubble"
            zone_config = bubble_cfg
        elif current_cape <= cheap_cfg["cape_max"]:
            zone_key = "cheap"
            zone_config = cheap_cfg
        else:
            zone_key = "fair"
            zone_config = fair_cfg
    else:
        zone_config = PE_ZONES["fair"]

    # ── Step 2: Within zone, pick ratio by drawdown tier ─────────
    tiers_sorted = sorted(zone_config["tiers"], key=lambda t: t[0])
    ratio = tiers_sorted[0][1]  # default ratio
    tier_desc = ""

    for i, (max_dd, r) in enumerate(tiers_sorted):
        if drawdown_pct < max_dd:
            ratio = r
            if i == 0:
                tier_desc = f"回撤 {drawdown_pct}%（< {max_dd}%）→ {ratio:.0%} of max"
            else:
                prev_max_dd = tiers_sorted[i - 1][0]
                tier_desc = f"回撤 {drawdown_pct}%（{prev_max_dd}%-{max_dd}%）→ {ratio:.0%} of max"
            break

    # Scale to actual USD
    invest_usd = round(ratio * max_amount_usd)
    saved_usd = max_amount_usd - invest_usd

    # Build reasoning
    pe_threshold_str = (
        f"≥ {zone_config['cape_min']}" if zone_key == "bubble"
        else f"≤ {zone_config['cape_max']}" if zone_key == "cheap"
        else f"{zone_config['cape_min']}-{zone_config['cape_max']}"
    )
    reasons = [
        f"当前 CAPE = {current_cape:.2f}（{zone_config['label']}，PE {pe_threshold_str}）" if current_cape else "CAPE 数据不可用",
        f"{zone_config['state_desc']}",
        f"{tier_desc}",
        f"本月执行 ${invest_usd} USD（上限 ${max_amount_usd:.0f} 的 {ratio:.0%}）",
    ]
    if saved_usd > 0:
        reasons.append(f"留存 ${saved_usd} USD 进入 Defense Fund 现金储备")

    reasoning = "。".join(r.rstrip("。") for r in reasons) + "。"

    logger.info(
        f"Smart DCA: CAPE={current_cape}, zone={zone_config['label']}, "
        f"drawdown={drawdown_pct}%, ratio={ratio:.0%}, → ${invest_usd} USD"
    )

    return {
        "zone_key": zone_key,
        "zone_label": zone_config["label"],
        "state_desc": zone_config["state_desc"],
        "current_cape": current_cape,
        "cape_percentile": cape_percentile,
        "drawdown_pct": drawdown_pct,
        "at_all_time_high": at_ath,
        "max_amount_usd": max_amount_usd,
        "ratio": ratio,
        "invest_usd": invest_usd,
        "saved_usd": saved_usd,
        "reasoning": reasoning,
    }


# ── Aggregation ────────────────────────────────────────────────────


def get_market_state() -> dict:
    """
    Aggregate all market data into a single dict for the report generator.
    This is the primary entry point for the data pipeline.
    """
    # 1. S&P 500 latest price
    sp500 = fetch_sp500_latest()

    # 2. Exchange rate
    fx = fetch_exchange_rate()

    # 3. Shiller data (CAPE, percentile, drawdown)
    try:
        shiller_df = load_shiller_data()
        latest_shiller = shiller_df.iloc[-1]
        current_cape = float(latest_shiller["CAPE"])
        cape_info = calculate_cape_percentile(current_cape, shiller_df)
        drawdown_info = calculate_current_drawdown(shiller_df, current_nominal_price=sp500["price"])
        shiller_available = True
    except FileNotFoundError as e:
        logger.warning(f"Shiller data unavailable: {e}")
        cape_info = None
        drawdown_info = None
        shiller_available = False

    # 4. Macro indicators (CPI, unemployment, Fed rate, GDP)
    macro = fetch_macro_indicators()

    # 5. Historical crash reference
    crashes = get_crash_reference()

    return {
        "generated_at": datetime.now().isoformat(),
        "sp500": sp500,
        "exchange_rate": fx,
        "cape": cape_info,
        "drawdown": drawdown_info,
        "shiller_available": shiller_available,
        "macro_indicators": macro,
        "historical_crashes": crashes,
    }
