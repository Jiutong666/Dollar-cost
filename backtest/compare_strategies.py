"""
30-Year Backtest: Smart DCA (PE Zone) vs Fixed DCA ($1000/month)

Compares two strategies from 1996-06 to 2023-09 (~27 years of Shiller data):
  - Fixed DCA: Invest $1000 every month, rain or shine
  - Smart DCA: Adjust monthly investment by CAPE zone + drawdown

Both strategies reinvest dividends. Uninvested cash in Smart DCA earns 3% risk-free.
"""

import sys
from pathlib import Path

import pandas as pd
import numpy as np

# Add project root so we can import config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sp500_dca_copilot.config import PE_ZONES

# ── Configuration ──────────────────────────────────────────────────
MAX_MONTHLY_USD = 1000          # Smart DCA upper limit
FIXED_MONTHLY_USD = 750         # Fixed DCA baseline (user's actual plan)
RISK_FREE_RATE = 0.03           # 3% annual for idle cash
START_DATE = "1996-06-01"
END_DATE = "2023-09-01"         # Last date in Shiller data
SHILLER_CSV = Path(__file__).resolve().parent.parent / "data" / "shiller_sp500_monthly.csv"

# ── PE Zone Override ───────────────────────────────────────────────
PE_OVERRIDE = {
    "bubble_cape_min": 32,       # CAPE >= ? → 泡沫区
    "fair_cape_min": 24,         # CAPE >= ? → 合理区
    "fair_cape_max": 31,         # CAPE <= ? → 合理区
    "cheap_cape_max": 23,        # CAPE <= ? → 便宜区
}

# ── Helper: PE Zone logic (mirrors data_fetcher.py) ─────────────────

def get_zone_and_ratio(cape: float, drawdown_pct: float) -> tuple:
    """Determine PE zone and investment ratio for a given CAPE and drawdown."""
    bubble_min = PE_OVERRIDE["bubble_cape_min"]
    fair_min = PE_OVERRIDE["fair_cape_min"]
    fair_max = PE_OVERRIDE["fair_cape_max"]
    cheap_max = PE_OVERRIDE["cheap_cape_max"]

    if cape >= bubble_min:
        zone_cfg = PE_ZONES["bubble"]
        zone_cfg = dict(zone_cfg, cape_min=bubble_min)  # override for display
        zone_name = "泡沫区"
    elif cape <= cheap_max:
        zone_cfg = PE_ZONES["cheap"]
        zone_cfg = dict(zone_cfg, cape_max=cheap_max)
        zone_name = "便宜区"
    else:
        zone_cfg = PE_ZONES["fair"]
        zone_cfg = dict(zone_cfg, cape_min=fair_min, cape_max=fair_max)
        zone_name = "合理区"

    tiers = sorted(zone_cfg["tiers"], key=lambda t: t[0])
    ratio = tiers[0][1]  # default
    for max_dd, r in tiers:
        if drawdown_pct < max_dd:
            ratio = r
            break

    return zone_name, ratio


# ── Load and prepare data ──────────────────────────────────────────

print("Loading Shiller data...")
df = pd.read_csv(SHILLER_CSV)

# Convert fractional year to datetime
def frac_year_to_dt(y):
    year = int(y)
    month = int(round((y - year) * 100))
    month = max(1, min(12, month))
    return pd.Timestamp(year=year, month=month, day=15)

df["date"] = df["Date"].apply(frac_year_to_dt)
df = df.sort_values("date").reset_index(drop=True)

# Filter to backtest period
mask = (df["date"] >= START_DATE) & (df["date"] <= END_DATE)
df_bt = df[mask].copy()
print(f"Backtest period: {df_bt['date'].iloc[0].strftime('%Y-%m')} to {df_bt['date'].iloc[-1].strftime('%Y-%m')}")
print(f"Total months: {len(df_bt)}")

# ── Run simulation ─────────────────────────────────────────────────

# Fixed DCA state
fixed_shares = 0.0
fixed_invested = 0.0

# Smart DCA state
smart_shares = 0.0
smart_invested = 0.0
smart_cash = 0.0              # Uninvested cash (earns risk-free)

# Track monthly history for analysis
history = []
ath_price = 0.0

for idx, row in df_bt.iterrows():
    price = row["SP500_Price"]
    cape = row["CAPE"]
    dividend_annual = row["Dividend"] if not pd.isna(row["Dividend"]) else 0.0
    date = row["date"]

    # Skip if essential data is missing
    if pd.isna(price) or price <= 0:
        continue
    if pd.isna(cape):
        continue  # Skip months without CAPE (early data has 'NA')

    # ── Update ATH and calculate drawdown ──────────────────────
    if price > ath_price:
        ath_price = price
    drawdown_pct = (price - ath_price) / ath_price * 100  # negative = drawdown
    drawdown_abs = abs(min(0, drawdown_pct))              # 0% at ATH, positive in drawdown

    # ── Fixed DCA: always $750 (user's actual plan) ──────────
    invest_fixed = FIXED_MONTHLY_USD
    fixed_shares += invest_fixed / price
    fixed_invested += invest_fixed

    # ── Smart DCA: zone-based, max $1000 ─────────────────────
    zone, ratio = get_zone_and_ratio(cape, drawdown_abs)
    invest_smart = round(ratio * MAX_MONTHLY_USD)
    saved_this_month = FIXED_MONTHLY_USD - invest_smart  # vs $750 baseline

    smart_shares += invest_smart / price
    smart_invested += invest_smart
    smart_cash += saved_this_month

    # Monthly interest on idle cash (simple monthly compounding)
    smart_cash *= (1 + RISK_FREE_RATE / 12)

    # ── Dividend reinvestment (for both) ──────────────────────
    monthly_div_per_share = dividend_annual / 12
    if monthly_div_per_share > 0 and price > 0:
        fixed_div_shares = (fixed_shares * monthly_div_per_share) / price
        fixed_shares += fixed_div_shares

        smart_div_shares = (smart_shares * monthly_div_per_share) / price
        smart_shares += smart_div_shares

    # ── Record monthly state ────────────────────────────────
    history.append({
        "date": date,
        "price": price,
        "cape": cape,
        "drawdown_pct": round(drawdown_pct, 1),
        "zone": zone,
        "ratio": ratio,
        "invest_fixed": invest_fixed,
        "invest_smart": invest_smart,
        "saved_smart": saved_this_month,
        "fixed_shares": round(fixed_shares, 4),
        "smart_shares": round(smart_shares, 4),
        "fixed_value": round(fixed_shares * price, 2),
        "smart_value": round(smart_shares * price + smart_cash, 2),
        "smart_cash": round(smart_cash, 2),
    })

# ── Final Results ──────────────────────────────────────────────────

final_price = df_bt["SP500_Price"].iloc[-1]
fixed_final_value = fixed_shares * final_price
smart_final_value = smart_shares * final_price + smart_cash

# Calculate CAGR (money-weighted, roughly)
years = len(history) / 12.0

# XIRR approximation: total return / total years
def approx_cagr(total_invested: float, final_value: float, years: float) -> float:
    """Approximate CAGR (money-weighted). Uses simple IRR calculation."""
    if total_invested <= 0 or final_value <= 0:
        return 0.0
    # Total return on capital
    total_return = (final_value - total_invested) / total_invested
    # Annualized (geometric, assuming ~half the money was invested for the full period on average)
    return (1 + total_return) ** (1 / years) - 1

fixed_cagr = approx_cagr(fixed_invested, fixed_final_value, years)
smart_cagr = approx_cagr(smart_invested, smart_final_value, years)

print()
print("=" * 65)
print("  30-Year Backtest: Smart DCA (PE Zone) vs Fixed DCA")
print(f"  Period: {history[0]['date'].strftime('%Y-%m')} → {history[-1]['date'].strftime('%Y-%m')} ({years:.1f} years)")
print(f"  Smart max: ${MAX_MONTHLY_USD}, Fixed baseline: ${FIXED_MONTHLY_USD}")
print("=" * 65)
print()
print(f"{'Metric':<35} {'Fixed DCA':>14} {'Smart DCA':>14}")
print("-" * 65)
print(f"{'Total Invested':<35} ${fixed_invested:>13,.0f} ${smart_invested:>13,.0f}")
print(f"{'Final Cash Balance':<35} ${0:>13,.0f} ${smart_cash:>13,.0f}")
print(f"{'Total Shares Owned':<35} {fixed_shares:>14.2f} {smart_shares:>14.2f}")
print(f"{'Final Portfolio Value':<35} ${fixed_final_value:>13,.0f} ${smart_final_value:>13,.0f}")
print(f"{'Approx. CAGR':<35} {fixed_cagr:>13.2%} {smart_cagr:>13.2%}")
print()

# Difference
diff_value = smart_final_value - fixed_final_value
diff_invested = smart_invested - fixed_invested
print(f"{'Smart DCA outperformance':<35} ${diff_value:>13,.0f}")
print(f"{'Smart DCA saved (not invested)':<35} ${abs(diff_invested):>13,.0f}")
if smart_invested > 0:
    efficiency = (smart_final_value / smart_invested) / (fixed_final_value / fixed_invested)
    print(f"{'Capital efficiency ratio':<35} {efficiency:>14.2f}x (Smart $1 = Fixed ${efficiency:.2f})")
print()

# ── Zone Distribution ──────────────────────────────────────────────

hist_df = pd.DataFrame(history)
print("─" * 65)
print("  Zone Distribution (months spent in each zone)")
print("─" * 65)
zone_counts = hist_df["zone"].value_counts()
for z in ["泡沫区", "合理区", "便宜区"]:
    count = zone_counts.get(z, 0)
    pct = count / len(hist_df) * 100
    avg_ratio = hist_df[hist_df["zone"] == z]["ratio"].mean() if count > 0 else 0
    print(f"  {z}: {count} months ({pct:.1f}%), avg invest ratio: {avg_ratio:.1%}")
print()

# ── Key Crash Periods ──────────────────────────────────────────────

print("─" * 65)
print("  Performance During Key Crashes")
print("─" * 65)

crashes = [
    ("2000-03", "2002-10", "互联网泡沫 (Dot-com)"),
    ("2007-10", "2009-03", "全球金融危机 (GFC)"),
    ("2020-02", "2020-03", "新冠疫情 (COVID-19)"),
]

for start, end, name in crashes:
    crash = hist_df[(hist_df["date"] >= start) & (hist_df["date"] <= end)]
    if len(crash) == 0:
        continue
    peak_price = crash["price"].max()
    trough_price = crash["price"].min()
    crash_dd = (trough_price - peak_price) / peak_price * 100

    fixed_bought = crash["invest_fixed"].sum()
    smart_bought = crash["invest_smart"].sum()
    fixed_shares_crash = crash[crash["price"] == trough_price]["fixed_shares"].iloc[-1] if len(crash) > 0 else 0

    # Shares bought during crash
    smart_shares_bought = (crash["invest_smart"] / crash["price"]).sum()
    fixed_shares_bought = (crash["invest_fixed"] / crash["price"]).sum()

    print(f"  {name} ({start} to {end}):")
    print(f"    Max drawdown: {crash_dd:.1f}%")
    print(f"    Fixed bought: ${fixed_bought:,.0f} → {fixed_shares_bought:.2f} shares")
    print(f"    Smart bought: ${smart_bought:,.0f} → {smart_shares_bought:.2f} shares")
    print(f"    Smart extra shares: {smart_shares_bought - fixed_shares_bought:+.2f}")
    print()

# ── Save detailed monthly CSV ──────────────────────────────────────

out_dir = Path(__file__).resolve().parent
hist_df.to_csv(out_dir / "backtest_monthly.csv", index=False)
print(f"Monthly history saved to: {out_dir / 'backtest_monthly.csv'}")
print("=" * 65)
