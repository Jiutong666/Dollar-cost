"""Trace the full Smart DCA calculation chain step by step."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sp500_dca_copilot.data_fetcher import (
    fetch_sp500_latest,
    load_shiller_data,
    calculate_cape_percentile,
    calculate_current_drawdown,
)
from sp500_dca_copilot.config import PE_ZONES

print("=" * 65)
print("  Smart DCA 完整计算链路")
print("=" * 65)
print()

# ── Step 1: S&P 500 price ───────────────────────────────────
sp500 = fetch_sp500_latest()
print("[Step 1] S&P 500 最新价格 (FRED SP500 日频)")
print(f"  {sp500['price']:.2f}  ({sp500['date'].strftime('%Y-%m-%d')})")
print()

# ── Step 2: CAPE / PE ───────────────────────────────────────
df = load_shiller_data()
cape_val = float(df["CAPE"].dropna().iloc[-1])
cape_info = calculate_cape_percentile(cape_val, df)
print("[Step 2] CAPE / PE (Shiller Yale 数据库, 1871-2023)")
print(f"  当前值: {cape_val:.2f}")
print(f"  历史百分位: {cape_info['percentile']}% (中位数 {cape_info['median_cape']})")
print()

# ── Step 3: Drawdown ────────────────────────────────────────
drawdown_info = calculate_current_drawdown(df, current_nominal_price=sp500["price"])
print("[Step 3] 回撤 (FRED 现价 vs Shiller 历史名义前高)")
print(f"  Shiller 期内前高: {drawdown_info['peak_price']:.2f} ({drawdown_info['peak_date'].strftime('%Y-%m')})")
print(f"  FRED 当前价格:   {sp500['price']:.2f}")
print(f"  结论: 历史新高 → 有效回撤 = {drawdown_info['drawdown_pct']}%")
print()

# ── Step 4: PE Zone ─────────────────────────────────────────
bub = PE_ZONES["bubble"]["cape_min"]
fmin = PE_ZONES["fair"]["cape_min"]
fmax = PE_ZONES["fair"]["cape_max"]
chp = PE_ZONES["cheap"]["cape_max"]

print(f"[Step 4] PE 区间判定 (config.py PE_ZONES)")
print(f"  规则: 泡沫区 CAPE >= {bub} | 合理区 CAPE {fmin}-{fmax} | 便宜区 CAPE <= {chp}")
print(f"  CAPE {cape_val:.2f} >= {bub} ?  {cape_val >= bub}")
print(f"  CAPE {cape_val:.2f} <= {chp} ?  {cape_val <= chp}")

if cape_val >= bub:
    zone_key = "bubble"
    zone_name = "泡沫区"
elif cape_val <= chp:
    zone_key = "cheap"
    zone_name = "便宜区"
else:
    zone_key = "fair"
    zone_name = "合理估值区"

print(f"  -> 落入 [{zone_name}]")
print()

# ── Step 5: Tier matching ───────────────────────────────────
dd = drawdown_info["drawdown_pct"]
tiers = sorted(PE_ZONES[zone_key]["tiers"], key=lambda t: t[0])

print(f"[Step 5] 档位匹配 ({zone_name} tiers)")
for max_dd, ratio in tiers:
    hit = dd < max_dd
    mark = "  <-- HIT" if hit else ""
    print(f"  drawdown {dd}% < {max_dd}% ?  {str(hit):5s} -> ratio {ratio:.0%}{mark}")
    if hit:
        chosen_ratio = ratio
        break
print()

# ── Step 6: Final amount ────────────────────────────────────
MAX_USD = 1000
invest = round(chosen_ratio * MAX_USD)
print("[Step 6] 最终金额")
print(f"  {chosen_ratio:.0%} x ${MAX_USD} = ${invest} USD")
print(f"  留存 ${MAX_USD - invest} USD -> Defense Fund")
print()
print("=" * 65)
