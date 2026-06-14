"""
Report generator for the S&P 500 DCA Co-pilot.
Constructs the "Buffett-style" prompt, calls DeepSeek API, and saves the report.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    NEWS_FILE_PATH,
    OUTPUT_DIR,
    REPORT_FILENAME_FORMAT,
    BACKTEST_SUMMARY,
    PE_ZONES,
)
from .data_fetcher import calculate_smart_dca_recommendation

logger = logging.getLogger(__name__)

# ── News Input (optional user supplement) ──────────────────────────


def read_news() -> str:
    """
    Read the optional monthly macro news file provided by the user.
    Returns content string, or empty string if file missing/empty.
    """
    if not NEWS_FILE_PATH.exists():
        logger.info("Optional news file not found — will use FRED macro data only.")
        return ""

    content = NEWS_FILE_PATH.read_text(encoding="utf-8").strip()
    if not content or content.startswith("（请在此文件中粘贴"):
        logger.info("News file is template/empty — will use FRED macro data only.")
        return ""

    logger.info(f"Read {len(content)} chars from user news file.")
    return content


# ── Prompt Construction ────────────────────────────────────────────


def _format_cape_section(cape: Optional[dict]) -> str:
    """Format the CAPE/valuation section of the prompt."""
    if cape is None:
        return "CAPE数据暂不可用（Shiller数据缺失），无法提供估值参考。"

    return (
        f"- 当前Shiller CAPE (周期调整市盈率): {cape['current_cape']}\n"
        f"- 历史百分位: {cape['percentile']}% (数据范围 {cape['data_start']} ~ {cape['data_end']})\n"
        f"- 历史中位数: {cape['median_cape']}，最小值: {cape['min_cape']}，最大值: {cape['max_cape']}\n"
        f"- 估值判定: **{cape['valuation_label']}**"
    )


def _format_fx_section(fx: dict) -> str:
    """Format the exchange rate section."""
    direction = "上行（人民币贬值）" if fx["change_pct"] > 0 else "下行（人民币升值）"
    return (
        f"- 当前 USD/CNY: {fx['current_rate']:.4f} ({fx['current_date'].strftime('%Y-%m-%d')})\n"
        f"- 上月参考: {fx['prev_rate']:.4f} ({fx['prev_date'].strftime('%Y-%m-%d')})\n"
        f"- 月度变化: {fx['change_pct']:+.2f}% → 汇率{direction}"
    )


def _format_macro_section(macro: dict) -> str:
    """Format FRED macro indicators as the primary 'hard data' news source."""
    lines = []
    cpi = macro.get("cpi")
    unrate = macro.get("unrate")
    fedfunds = macro.get("fedfunds")
    gdp = macro.get("gdp")

    if cpi:
        lines.append(
            f"- CPI (消费者价格指数): {cpi['latest_value']} "
            f"({cpi['latest_date'].strftime('%Y-%m')}), "
            f"同比 {cpi['yoy_change_pct']:+.2f}%"
        )
    if unrate:
        lines.append(
            f"- 失业率: {unrate['value']}% ({unrate['date'].strftime('%Y-%m')})"
        )
    if fedfunds:
        lines.append(
            f"- 联邦基金利率: {fedfunds['value']}% ({fedfunds['date'].strftime('%Y-%m')})"
        )
    if gdp:
        qoq = f", 季环比 {gdp['qoq_change_pct']:+.2f}%" if gdp.get("qoq_change_pct") is not None else ""
        lines.append(
            f"- GDP: {gdp['value']:.0f} 十亿美元 ({gdp['date'].strftime('%Y-%m')}){qoq}"
        )

    if not lines:
        return "（宏观指标数据暂不可用）"

    return "\n".join(lines)


def _format_drawdown_section(drawdown: Optional[dict]) -> str:
    """Format the drawdown section for the prompt."""
    if drawdown is None or drawdown.get("drawdown_pct") is None:
        return ""
    if drawdown.get("at_all_time_high"):
        return (
            f"\n当前市场状态：标普500处于**历史新高**水平"
            f"（Shiller数据期内前次高点为 {drawdown['peak_price']:.2f}，"
            f"日期 {drawdown['peak_date'].strftime('%Y-%m-%d')}）。\n"
        )
    return (
        f"\n当前回撤：{drawdown['drawdown_pct']}% "
        f"（从高点 {drawdown['peak_price']:.2f}，"
        f"日期 {drawdown['peak_date'].strftime('%Y-%m-%d')}）\n"
    )


def _format_smart_dca_section(smart_dca: dict, fx_rate: float) -> str:
    """Format the PE Zone Smart DCA recommendation section."""
    invest_usd = smart_dca["invest_usd"]
    invest_cny = invest_usd * fx_rate
    max_usd = smart_dca["max_amount_usd"]
    ratio = smart_dca["ratio"]
    current_cape = smart_dca.get("current_cape")
    saved_usd = smart_dca.get("saved_usd", 0)

    lines = [
        f"- 用户设定月投上限: **${max_usd:.0f} USD**",
        f"- 当前 CAPE (PE): {current_cape:.2f}" if current_cape else "- CAPE: 数据不可用",
        f"- PE 估值区间: **{smart_dca['zone_label']}**",
        f"- 当前回撤: {smart_dca['drawdown_pct']}% ({'历史新高' if smart_dca.get('at_all_time_high') else '回撤中'})",
        f"- 区间策略: {smart_dca['state_desc']}",
        f"- 执行比例: **{ratio:.0%}** × ${max_usd:.0f} = **${invest_usd} USD ≈ ¥{invest_cny:.2f} CNY**",
    ]
    if saved_usd > 0:
        lines.append(f"- 本月留存: ${saved_usd} USD → Defense Fund（等待更低估值机会）")

    return "\n".join(lines)


def _format_crashes_section(crashes: list) -> str:
    """Format historical crash references for psychological defense."""
    lines = []
    for c in crashes:
        lines.append(
            f"- **{c['name']}** ({c['period']})：最大回撤 {c['peak_to_trough']}，"
            f"恢复时间 {c['recovery_time']}。{c['dca_benefit']}"
        )
    return "\n".join(lines)


def build_prompt(market_data: dict, monthly_amount_usd: float) -> str:
    """
    Construct the full "Buffett-style" prompt with all data injected.
    Primary macro data comes from FRED indicators; user news file is optional supplement.
    """
    sp500 = market_data["sp500"]
    fx = market_data["exchange_rate"]
    cape = market_data.get("cape")
    drawdown = market_data.get("drawdown")
    macro = market_data.get("macro_indicators", {})
    crashes = market_data.get("historical_crashes", [])

    # Optional user-provided news supplement
    user_news = read_news()

    # Calculate Smart DCA recommendation
    smart_dca = calculate_smart_dca_recommendation(
        drawdown_info=drawdown,
        cape_info=cape,
        max_amount_usd=monthly_amount_usd,
    )
    invest_usd = smart_dca["invest_usd"]
    invest_cny = invest_usd * fx["current_rate"]
    max_usd = smart_dca["max_amount_usd"]
    max_cny = max_usd * fx["current_rate"]
    ratio = smart_dca["ratio"]

    # Build the macro section: FRED indicators primary, user news as supplement
    macro_block = _format_macro_section(macro)
    if user_news:
        macro_block += f"\n\n【用户补充资讯】\n{user_news}"

    prompt = f"""你是一个极度理性的"标普500定投纪律巴菲特"。你的唯一任务是辅助用户执行一项为期 20-30 年的长期定投计划。你不做任何市场预测，不贩卖焦虑，只基于提供的硬数据进行客观总结，并帮助用户屏蔽噪音、维持纪律。

【本月硬数据】
- S&P 500 最新收盘价: {sp500['price']:.2f} ({sp500['date'].strftime('%Y-%m-%d')})
- S&P 500 数据来源: FRED {sp500['series_id']}
{_format_cape_section(cape)}

【汇率数据】
{_format_fx_section(fx)}
{_format_drawdown_section(drawdown)}

【本月宏观指标（FRED 实时数据）】
{macro_block}

【Smart DCA 定投金额分析（PE 估值区间 + 回撤双因子决策）】
{_format_smart_dca_section(smart_dca, fx['current_rate'])}

【用户定投设置】
- 月投上限: **${max_usd:.0f} USD ≈ ¥{max_cny:.2f} CNY**
- 本月 PE 区间: {smart_dca['zone_label']} → 执行比例 {ratio:.0%} → **${invest_usd} USD ≈ ¥{invest_cny:.2f} CNY**
- 留存现金: ${smart_dca['saved_usd']} USD → Defense Fund
- 投资期限: 20-30 年
- 策略: PE 估值区间 + 回撤双因子 Smart DCA

【Smart DCA 三区规则（比例基于月投上限 ${max_usd:.0f}）】
| PE 区间 | CAPE 范围 | 策略 | 回撤 0-5% | 回撤 5-10% | 回撤 10-20% | 回撤 >20% |
|---------|-----------|------|-----------|------------|-------------|-----------|
| 泡沫区 | CAPE ≥ {PE_ZONES['bubble']['cape_min']} | 强制缩减 | {int(max_usd*0.30)} ({0.30:.0%}) | {int(max_usd*0.40)} ({0.40:.0%}) | {int(max_usd*0.60)} ({0.60:.0%}) | {int(max_usd*1.00)} ({1.00:.0%}) |
| 合理区 | CAPE {PE_ZONES['fair']['cape_min']}-{PE_ZONES['fair']['cape_max']} | 机械扣款 | {int(max_usd*0.50)} ({0.50:.0%}) | {int(max_usd*0.60)} ({0.60:.0%}) | {int(max_usd*0.75)} ({0.75:.0%}) | {int(max_usd*1.00)} ({1.00:.0%}) |
| 便宜区 | CAPE ≤ {PE_ZONES['cheap']['cape_max']} | 加大吸筹 | {int(max_usd*0.70)} ({0.70:.0%}) | {int(max_usd*0.85)} ({0.85:.0%}) | {int(max_usd*1.00)} ({1.00:.0%}) | {int(max_usd*1.00)} ({1.00:.0%}) |
- **核心纪律: 估值越高，投入越少，现金越多；估值越低，投入越多，筹码越多。上限由你设定，系统只调比例。**

【历史回测参考（30年：1996-2026）】
- 固定定投：投入 ¥{BACKTEST_SUMMARY['fixed_dca']['invested_cny']:,} → 终值 ¥{BACKTEST_SUMMARY['fixed_dca']['final_value_cny']:,}，年化 {BACKTEST_SUMMARY['fixed_dca']['xirr']}
- 智能定投（大跌加倍）：投入 ¥{BACKTEST_SUMMARY['smart_dca']['invested_cny']:,} → 终值 ¥{BACKTEST_SUMMARY['smart_dca']['final_value_cny']:,}，年化 {BACKTEST_SUMMARY['smart_dca']['xirr']}
- 注：{BACKTEST_SUMMARY['note']}

【重大历史回撤参考】
{_format_crashes_section(crashes)}

【执行任务】
请严格按照以下四个模块输出报告（Markdown 格式），语气冷静、克制、简明扼要：

---

## 一、本月市场快照

**首先明确写出：S&P 500 当前价格和日期**。然后基于 FRED 宏观指标数据，用不超过 3 句话客观概括当前宏观环境的核心事实（如通胀水平、就业市场、利率环境），不加任何主观推测。

---

## 二、成本与估值参考

1. **筹码估值**：根据 CAPE 历史百分位，说明当前买入的是"偏贵"、"合理"还是"便宜"的筹码。简要说明当前 CAPE 在历史上处于什么位置。

2. **换汇成本**：结合本月 USD/CNY 汇率变化。如果汇率下行（人民币升值），请客观提示当前换汇具有成本优势——同样的 USD 可以换到更少的 CNY，购买力相对下降，但美股的 CNY 成本降低；如果汇率上行（人民币贬值），提示换汇摩擦成本增加，但强调**不应因此中断定投**——长期来看汇率波动的影响远小于复利的力量。

3. **Smart DCA 定投金额决策**：
   - **系统已根据当前 CAPE ({smart_dca.get('current_cape', 'N/A')}) 和 PE 三区规则自动判定为「{smart_dca['zone_label']}」——不需要你重新判断区间，直接用这个结论。**
   - 月投上限 ${max_usd:.0f} USD，当前回撤 {smart_dca['drawdown_pct']}%，触发比例 {ratio:.0%}。
   - 本月执行：**${invest_usd} USD ≈ ¥{invest_cny:.2f} CNY**，留存 ${smart_dca['saved_usd']} USD → Defense Fund。
   - 解释该区间的含义（{smart_dca['state_desc']}），并结合当前 CAPE 百分位说明为什么这个金额是合理的。

---

## 三、定投纪律提示

从两个角度论述：

### 看多视角（Bull Case）
基于当前市场数据和宏观指标，客观陈述支撑继续定投的结构性因素（如：历史上CAPE高位时继续定投的长期结果、股市长期向上的历史规律、当前经济中的积极信号等）。

### 看空视角（Bear Case）
客观陈述当前市场的风险因素和担忧点（如：CAPE偏高、通胀风险、就业市场变化、利率政策不确定性、地缘政治风险等）。

### 纪律总结
综合多空双方观点，给出最终纪律提醒：
- 如果你当前账户为负收益：引用上面历史回撤数据（2000、2008、2020、2022），用具体数据证明"在标普500经历大幅回撤时坚持定投，长期收益更优"，鼓励用户坚持。
- 如果你账户为正收益：提醒不要因短期浮盈而停止投入或随意改变策略。定投的核心价值在于"用时间换空间"，而非择时。
- 如果无法判断：给出中性纪律提醒，强调定投的数学优势。

---

【输出要求】
- 语气冷静、克制、简明扼要。
- 严禁捏造任何输入数据中不存在的宏观指标或财务数据。
- 多空双方都要有，最后落到纪律上。
- 使用 Markdown 格式，便于直接保存为 .md 文件。
- 结尾加一句定投格言（如"别人恐惧我贪婪，别人贪婪我恐惧"风格）。
"""

    return prompt


# ── DeepSeek API Call ──────────────────────────────────────────────


def call_deepseek(prompt: str) -> str:
    """
    Call the DeepSeek API (OpenAI-compatible) to generate the report.
    Returns the generated markdown text.
    Raises RuntimeError if DEEPSEEK_API_KEY is not set.
    """
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "DEEPSEEK_API_KEY environment variable is not set.\n"
            "Get a key at https://platform.deepseek.com/\n"
            "Or use --dry-run to see the prompt without calling the API."
        )

    from openai import OpenAI

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    logger.info(f"Calling DeepSeek API (model: {DEEPSEEK_MODEL})...")
    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {
                "role": "system",
                "content": "你是一个极度理性的长期投资者。你的回答必须基于提供的数据，不添加任何未经证实的信息。使用 Markdown 格式输出。",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=2048,
    )

    text = response.choices[0].message.content
    usage = response.usage
    logger.info(
        f"API response: {len(text)} chars, "
        f"prompt_tokens={usage.prompt_tokens}, "
        f"completion_tokens={usage.completion_tokens}"
    )
    return text


# ── Report Pipeline ────────────────────────────────────────────────


def generate_report(
    market_data: dict,
    monthly_amount_usd: float,
    dry_run: bool = False,
) -> str:
    """
    Full report generation pipeline: build prompt → (optional) call API → return markdown.
    If dry_run=True, returns the prompt text instead of calling the API.
    """
    prompt = build_prompt(market_data, monthly_amount_usd)

    if dry_run:
        logger.info("Dry-run mode: returning prompt without API call.")
        return (
            "# DRY RUN — 以下为发送给 AI 的 Prompt\n\n"
            "```\n"
            + prompt
            + "\n```\n"
        )

    report = call_deepseek(prompt)
    return report


def save_report(markdown: str, report_date: datetime = None) -> Path:
    """
    Save the generated report to output/reports/YYYY-MM.md.
    Returns the path to the saved file.
    """
    if report_date is None:
        report_date = datetime.now()

    filename = REPORT_FILENAME_FORMAT.format(
        year=report_date.year, month=report_date.month
    )
    filepath = OUTPUT_DIR / filename

    header = (
        f"<!-- S&P 500 DCA Co-pilot Report -->\n"
        f"<!-- Generated: {report_date.isoformat()} -->\n"
        f"<!-- This is not financial advice. -->\n\n"
    )

    filepath.write_text(header + markdown, encoding="utf-8")
    logger.info(f"Report saved to {filepath}")
    return filepath
