"""
S&P 500 DCA Co-pilot — Monthly Report Entry Point

Usage:
    python -m sp500_dca_copilot.main [--amount 750] [--dry-run] [--no-ai]

Cron example (runs 1st of each month at 9am):
    0 9 1 * * cd /path/to/Dollar-cost && python -m sp500_dca_copilot.main >> output/cron.log 2>&1
"""

import argparse
import logging
import sys
from datetime import datetime

from .config import DEFAULT_MAX_MONTHLY_USD
from .data_fetcher import get_market_state, calculate_smart_dca_recommendation
from .report_generator import generate_report, save_report, read_news

# ── Logging ────────────────────────────────────────────────────────


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ── CLI ────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="S&P 500 DCA Co-pilot — Monthly Report Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m sp500_dca_copilot.main                    # Full run with $750 default
  python -m sp500_dca_copilot.main --amount 1000       # Custom amount $1,000
  python -m sp500_dca_copilot.main --dry-run           # Print prompt without API call
  python -m sp500_dca_copilot.main --no-ai             # Data-only summary, no AI
        """,
    )
    parser.add_argument(
        "--amount",
        type=float,
        default=DEFAULT_MAX_MONTHLY_USD,
        help=f"Maximum monthly investment in USD — Smart DCA scales down from this (default: {DEFAULT_MAX_MONTHLY_USD})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the assembled prompt without calling the AI API",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Skip AI call entirely; output a data-only summary to stdout",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


# ── Main ───────────────────────────────────────────────────────────


BANNER = r"""
  ██████╗  ██████╗ ██╗      ██╗      █████╗ ██████╗
  ██╔══██╗██╔═══██╗██║      ██║     ██╔══██╗██╔══██╗
  ██║  ██║██║   ██║██║      ██║     ███████║██████╔╝
  ██║  ██║██║   ██║██║      ██║     ██╔══██║██╔══██╗
  ██████╔╝╚██████╔╝███████╗ ███████╗██║  ██║██║  ██║
  ╚═════╝  ╚═════╝ ╚══════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝
         S&P 500 DCA · 定投纪律助手 · v1.0
"""


def main() -> None:
    args = parse_args()
    setup_logging(verbose=args.verbose)
    logger = logging.getLogger(__name__)

    import sys
    print(BANNER, file=sys.stderr)
    logger.info(f"Max monthly investment: ${args.amount:.2f} USD")

    # ── Step 1: .env loaded by config.py at import time ─────────

    # ── Step 2: Fetch market data ───────────────────────────────
    logger.info("Fetching market data...")
    try:
        market_data = get_market_state()
    except Exception as e:
        logger.error(f"Failed to fetch market data: {e}")
        sys.exit(1)

    # Print data summary
    sp500 = market_data["sp500"]
    fx = market_data["exchange_rate"]
    cape = market_data.get("cape")
    drawdown = market_data.get("drawdown")
    macro = market_data.get("macro_indicators", {})

    print()
    print("══╡ 数据摘要 ╞" + "═" * 46)
    print(f"  S&P 500: {sp500['price']:.2f} ({sp500['date'].strftime('%Y-%m-%d')})")
    print(f"  USD/CNY:  {fx['current_rate']:.4f} (变化: {fx['change_pct']:+.2f}%)")
    if cape:
        print(f"  CAPE:     {cape['current_cape']} (历史百分位: {cape['percentile']}% → {cape['valuation_label']})")
    else:
        print(f"  CAPE:     不可用 (Shiller 数据缺失)")
    if drawdown and drawdown.get("drawdown_pct") is not None:
        if drawdown.get("at_all_time_high"):
            print(f"  市场状态: 历史新高 (Shiller数据期内前高: {drawdown['peak_date'].strftime('%Y-%m-%d')}, {drawdown['peak_price']:.2f})")
        else:
            print(f"  当前回撤: {drawdown['drawdown_pct']}% (前高: {drawdown['peak_date'].strftime('%Y-%m-%d')})")
    # Macro indicators
    cpi = macro.get("cpi")
    unrate = macro.get("unrate")
    fedfunds = macro.get("fedfunds")
    if cpi:
        print(f"  CPI (同比): {cpi['yoy_change_pct']:+.2f}% ({cpi['latest_date'].strftime('%Y-%m')})")
    if unrate:
        print(f"  失业率:     {unrate['value']}% ({unrate['date'].strftime('%Y-%m')})")
    if fedfunds:
        print(f"  联邦利率:   {fedfunds['value']}% ({fedfunds['date'].strftime('%Y-%m')})")
    # Smart DCA (PE Zone + Drawdown)
    dca = calculate_smart_dca_recommendation(drawdown, cape, args.amount)
    invest_usd = dca["invest_usd"]
    invest_cny = invest_usd * fx["current_rate"]
    saved = dca.get("saved_usd", 0)
    print(f"  ---")
    print(f"  月投上限:  ${dca['max_amount_usd']:.0f} USD")
    print(f"  PE 区间:   {dca['zone_label']} (CAPE {dca.get('current_cape', 'N/A')})")
    print(f"  当前回撤:  {dca['drawdown_pct']}%")
    print(f"  执行比例:  {dca['ratio']:.0%} → ${invest_usd} USD ≈ ¥{invest_cny:.2f} CNY")
    if saved > 0:
        print(f"  本月留存:  ${saved:.0f} USD → Defense Fund")
    print(f"  区间策略:  {dca['state_desc']}")
    print(f"  ---")
    print("═" * 56)

    # ── Step 3: Handle --no-ai mode ─────────────────────────────
    if args.no_ai:
        print()
        print("--no-ai 模式：跳过 AI 调用，以上为数据摘要。")
        print("提示：在 data/monthly_news.txt 中放入补充资讯（可选），FRED 宏观指标已自动获取。")
        # Still save a minimal data report
        report_date = datetime.now()
        from .config import REPORT_FILENAME_FORMAT, OUTPUT_DIR
        from pathlib import Path
        filename = REPORT_FILENAME_FORMAT.format(year=report_date.year, month=report_date.month)
        filepath = OUTPUT_DIR / filename
        lines = [
            f"# S&P 500 定投月报 — {report_date.strftime('%Y年%m月')}",
            "",
            "## 数据摘要（无 AI 总结）",
            "",
            f"- S&P 500: **{sp500['price']:.2f}** ({sp500['date'].strftime('%Y-%m-%d')})",
            f"- USD/CNY: **{fx['current_rate']:.4f}** (月变化: {fx['change_pct']:+.2f}%)",
        ]
        if cape:
            lines.append(f"- CAPE: **{cape['current_cape']}** (历史百分位: {cape['percentile']}%，{cape['valuation_label']})")
        if cpi:
            lines.append(f"- CPI (同比): **{cpi['yoy_change_pct']:+.2f}%** ({cpi['latest_date'].strftime('%Y-%m')})")
        if unrate:
            lines.append(f"- 失业率: **{unrate['value']}%** ({unrate['date'].strftime('%Y-%m')})")
        if fedfunds:
            lines.append(f"- 联邦基金利率: **{fedfunds['value']}%** ({fedfunds['date'].strftime('%Y-%m')})")
        lines.extend([
            f"- 月投上限: **${dca['max_amount_usd']:.0f} USD**",
            f"- PE 区间: **{dca['zone_label']}** → 执行比例 {dca['ratio']:.0%}",
            f"- 本月执行: **${invest_usd} USD ≈ ¥{invest_cny:.2f} CNY**",
            f"- 本月留存: **${saved} USD → Defense Fund**" if saved > 0 else f"- 本月全额投入（无留存）",
            "",
            "> ⚠️ 此报告未经 AI 总结，仅供参考。请运行不含 `--no-ai` 的命令生成完整报告。",
        ])
        filepath.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n数据摘要已保存至: {filepath}")
        return

    # ── Step 4: Generate report ─────────────────────────────────
    logger.info("Generating report...")
    try:
        report = generate_report(
            market_data=market_data,
            monthly_amount_usd=args.amount,
            dry_run=args.dry_run,
        )
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)

    # ── Step 5: Save and output ─────────────────────────────────
    if args.dry_run:
        print()
        print(report)
        print()
        print("══╡ DRY RUN COMPLETE ╞" + "═" * 42)
        print("以上为组装好的 Prompt，未调用 AI API。")
        print("移除 --dry-run 参数以生成完整报告。")
        return

    report_date = datetime.now()
    filepath = save_report(report, report_date)

    print()
    print(report)
    print()
    print(f"══╡ 报告已保存 ╞" + "═" * 46)
    print(f"  {filepath}")
    print("═" * 56)


if __name__ == "__main__":
    main()
