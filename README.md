<p align="center">
  <pre>
  ██████╗  ██████╗ ██╗      ██╗      █████╗ ██████╗
  ██╔══██╗██╔═══██╗██║      ██║     ██╔══██╗██╔══██╗
  ██║  ██║██║   ██║██║      ██║     ███████║██████╔╝
  ██║  ██║██║   ██║██║      ██║     ██╔══██║██╔══██╗
  ██████╔╝╚██████╔╝███████╗ ███████╗██║  ██║██║  ██║
  ╚═════╝  ╚═════╝ ╚══════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝
  </pre>
  <b>S&P 500 DCA 定投纪律助手</b>
  <br>
  <sub>不预测 · 不焦虑 · 不捏造 · 不择时</sub>
</p>

一个极度理性的标普 500 定投辅助工具。不预测市场，不贩卖焦虑，只基于硬数据生成月度定投报告。

> *"别人贪婪时我恐惧，别人恐惧时我贪婪。"*
> 但更重要的是：**持续定投，按纪律执行。**

---

## 目录

- [设计哲学](#设计哲学)
- [快速开始](#快速开始)
- [命令参考](#命令参考)
- [Smart DCA 系统](#smart-dca-系统)
- [回测模块](#回测模块)
- [定时任务](#定时任务)
- [架构与数据流](#架构与数据流)
- [配置参考](#配置参考)
- [数据来源](#数据来源)
- [文件结构](#文件结构)
- [免责声明](#免责声明)

---

## 设计哲学

| 原则 | 说明 |
|------|------|
| **不预测** | 系统不判断市场方向，只根据 PE 估值和回撤调整投入比例 |
| **不焦虑** | 牛熊双方论点都呈现，但最终落到纪律执行 |
| **不捏造** | 所有数据来自 FRED / Shiller，AI 只做总结不编造 |
| **不择时** | Smart DCA 每月必须投入，最低比例 30%，永不停投 |

---

## 快速开始

### 前置条件

- Python 3.10+
- 两个免费 API Key

### 1. 克隆并安装

```bash
git clone https://github.com/Jiutong666/Dollar-cost.git
cd Dollar-cost
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env`：

```ini
FRED_API_KEY=your_fred_key_here        # https://fred.stlouisfed.org/docs/api/api_key.html
DEEPSEEK_API_KEY=sk-your_key_here      # https://platform.deepseek.com/
```

### 3. 下载历史估值数据

```bash
python -m sp500_dca_copilot.download_shiller_data
```

从 Robert Shiller (Yale) 下载 1871 年至今的 S&P 500 月度数据（CAPE、价格、股息、盈利）。

### 4. 生成首份报告

```bash
python -m sp500_dca_copilot.main
```

报告输出到 `output/reports/YYYY-MM.md`。

---

## 命令参考

### 主系统 `sp500_dca_copilot.main`

```bash
# 完整 AI 报告 (默认月投上限 $1000)
python -m sp500_dca_copilot.main

# 自定义月投上限
python -m sp500_dca_copilot.main --amount 2000

# 调试：打印构建好的 Prompt，不调用 AI API
python -m sp500_dca_copilot.main --dry-run

# 纯数据摘要：跳过 AI，只输出 FRED 指标 + Smart DCA 结论
python -m sp500_dca_copilot.main --no-ai

# 详细日志
python -m sp500_dca_copilot.main --verbose
```

### Shiller 数据管理

```bash
# 下载 / 更新 Shiller 数据
python -m sp500_dca_copilot.download_shiller_data

# 指定输出路径，保留原始 .xls
python -m sp500_dca_copilot.download_shiller_data --output data/my_copy.csv --keep-xls
```

### 回测模块

```bash
# Smart DCA vs Fixed DCA 27 年对比
python backtest/compare_strategies.py

# 查看实时计算链路（调试用）
python backtest/trace_calculation.py
```

---

## Smart DCA 系统

### PE 三区规则

月投上限由用户通过 `--amount` 设定（默认 $1000）。系统根据 **CAPE（Shiller PE）** 划分为三个估值区间，每个区间内再按**回撤幅度**决定投入比例。

| PE 区间 | CAPE 范围 | 策略 | 回撤 0-5% | 回撤 5-10% | 回撤 10-20% | 回撤 >20% |
|---------|-----------|------|:---------:|:----------:|:-----------:|:---------:|
| 泡沫区 | CAPE ≥ 32 | 强制缩减，积攒子弹 | **30%** | 40% | 60% | 100% |
| 合理区 | CAPE 24-31 | 机械扣款，保持纪律 | **50%** | 60% | 75% | 100% |
| 便宜区 | CAPE ≤ 23 | 加大吸筹，加速积累 | **70%** | 85% | 100% | 100% |

> 比例基于月投上限自动计算。例如上限 $1000，合理区 + 0% 回撤 → 50% × $1000 = **$500**。

### 计算链路

```
Step 1  FRED SP500 日频        →  当前 S&P 500 价格
Step 2  Shiller Yale 数据库     →  CAPE 值 + 历史百分位
Step 3  FRED vs Shiller 前高    →  当前回撤 %
Step 4  PE_ZONES 规则匹配       →  泡沫区 / 合理区 / 便宜区
Step 5  区间内 tiers 匹配       →  投入比例
Step 6  比例 × 月投上限          →  本月执行金额 + 留存金额
```

运行 `python backtest/trace_calculation.py` 可查看当前数据的完整计算过程。

### Defense Fund

Smart DCA 投入低于 $750 基线时，差额进入 **Defense Fund（现金储备）**。这笔钱不是闲置——它提供了：

- **流动性缓冲**：应急支出无需卖股
- **崩盘抄底权**：市场大幅回撤时，Defense Fund 可在规则外额外部署
- **心理安全感**：知道手上有现金，更能坚持纪律

---

## 回测模块

`backtest/compare_strategies.py` 对比 1996-2023（27 年）两种策略：

| 策略 | 月投 | 说明 |
|------|------|------|
| Fixed DCA | 固定 $750 | 每月雷打不动 |
| Smart DCA | $300-$1000 | PE 三区 + 回撤双因子动态调整 |

**回测结果概要（PE ≥ 32 / 24-31 / ≤ 23）：**

| 指标 | Fixed DCA | Smart DCA |
|------|:---------:|:---------:|
| 总投入 | $245,250 | $213,250 |
| 最终市值 | $1,039,672 | $1,010,093 |
| 现金余额 | $0 | $48,383 |
| 差距 | — | **-2.8%** |
| 资本效率 | $1.00 | **$1.12** |
| **GFC 期间多买** | — | **+1.79 股** |

Smart DCA 以 2.8% 的微小终值差距，换取了 $48k 现金储备 + 崩盘时更多的低价筹码 + 更小的心理压力。

配置 `PE_OVERRIDE` 可测试不同阈值组合。

---

## 定时任务

### Linux / macOS (cron)

每月 1 日上午 9:00 自动运行：

```cron
0 9 1 * * cd /path/to/Dollar-cost && python -m sp500_dca_copilot.main >> output/cron.log 2>&1
```

### Windows (Task Scheduler)

1. 打开「任务计划程序」→ 创建基本任务
2. 触发器：每月 → 第 1 天
3. 操作：启动程序
   - 程序：`python`
   - 参数：`-m sp500_dca_copilot.main`
   - 起始于：`D:\Dollar-cost`

### 验证定时任务

```bash
# 手动模拟 cron 执行
cd /path/to/Dollar-cost && python -m sp500_dca_copilot.main --no-ai && echo "OK"
```

---

## 架构与数据流

```
                    ┌──────────────────────┐
                    │      Cron Job         │
                    │  每月 1 日 9:00 触发   │
                    └──────────┬───────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
     FRED API            Shiller CSV         FRED API
   SP500 价格           CAPE / PE          宏观指标
   USD/CNY 汇率        1871-2023        CPI, UNRATE,
                       前高/回撤       FEDFUNDS, GDP
            │                  │                  │
            └──────────────────┼──────────────────┘
                               ▼
                    ┌──────────────────┐
                    │  计算引擎         │
                    │  PE 区间判定      │
                    │  回撤档位匹配     │
                    │  金额 = 比例×上限  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  Prompt 组装      │
                    │  注入所有硬数据    │
                    │  规则表 + 历史回撤 │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  DeepSeek API     │
                    │  deepseek-chat    │
                    │  生成 Markdown     │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │  output/reports/  │
                    │  2026-06.md       │
                    └──────────────────┘
```

---

## 配置参考

所有可调参数集中在 `sp500_dca_copilot/config.py`：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `DEFAULT_MAX_MONTHLY_USD` | 1000 | 月投上限（`--amount` 覆盖） |
| `PE_ZONES.bubble.cape_min` | 32 | 泡沫区 CAPE 阈值 |
| `PE_ZONES.fair.cape_min` / `max` | 24 / 31 | 合理区 CAPE 范围 |
| `PE_ZONES.cheap.cape_max` | 23 | 便宜区 CAPE 阈值 |
| `PE_ZONES.*.tiers` | 见规则表 | 每个区间内的回撤-比例对 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | AI 模型 |
| `HISTORICAL_CRASHES` | 4 次 | 历史回撤参考数据 |
| `BACKTEST_SUMMARY` | 预计算 | 30 年回测摘要 |

区间比例和 PE 阈值均可按需调整，无需改代码。修改后运行回测验证效果。

---

## 数据来源

| 数据 | 来源 | 系列 ID | 频率 | 起始 |
|------|------|---------|------|------|
| S&P 500 价格 | FRED | `SP500` | 日 | 2016 |
| USD/CNY 汇率 | FRED | `DEXCHUS` | 日 | 1971 |
| CPI (通胀) | FRED | `CPIAUCSL` | 月 | 1947 |
| 失业率 | FRED | `UNRATE` | 月 | 1948 |
| 联邦基金利率 | FRED | `FEDFUNDS` | 月 | 1954 |
| GDP | FRED | `GDP` | 季 | 1947 |
| CAPE / PE | Shiller (Yale) | `ie_data.xls` | 月 | 1871 |
| AI 总结 | DeepSeek | `deepseek-chat` | — | — |

> FRED API 完全免费，注册即用。Shiller 数据公开可下载。

---

## 文件结构

```
Dollar-cost/
│
├── sp500_dca_copilot/           # 核心模块
│   ├── __init__.py
│   ├── config.py                # 所有配置参数 (PE 阈值、金额比例、回撤数据)
│   ├── data_fetcher.py          # 数据管线 (FRED API + Shiller CSV + 计算引擎)
│   ├── report_generator.py      # Prompt 构建 + DeepSeek API 调用
│   ├── main.py                  # CLI 入口 (cron 调度目标)
│   └── download_shiller_data.py # Shiller 数据下载器 (xlrd 解析 .xls)
│
├── backtest/                    # 回测模块
│   ├── compare_strategies.py    # Smart DCA vs Fixed DCA 多情景对比
│   └── trace_calculation.py     # 实时计算链路追踪 (调试)
│
├── data/                        # 数据文件
│   ├── shiller_sp500_monthly.csv  # Shiller 月度数据 (git tracked)
│   └── monthly_news.txt           # 用户可选补充资讯 (gitignored)
│
├── output/reports/              # 生成的月度报告
│   └── YYYY-MM.md
│
├── .env                         # API Key (gitignored)
├── .env.example                 # 环境变量模板
├── .gitignore
├── requirements.txt
├── LICENSE
└── README.md
```

---

## 免责声明

本工具**不是**投资建议。

- 不预测市场方向
- 不推荐买卖时机
- 不对任何投资结果负责

它唯一的目的：在 20-30 年的尺度上，用数据和纪律帮助你对抗贪婪和恐惧。

---

<p align="center">
  <b>Stay disciplined. Stay invested. Let compounding do the rest.</b>
</p>
