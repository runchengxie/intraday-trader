# 工作流操作手册

本文从零开始，逐步走完 intraday-trader 的完整工作流：环境搭建 → 数据拉取 → 回测 → 参数优化 → 纸上交易 → 日报查看。

每一步都附有实际命令和预期输出说明。

## 前提

- Python 3.10 已安装
- `uv` 已安装（推荐，也可用 pip）
- 已按 `docs/broker-guide.md` 完成券商接入配置

## 第 1 步：环境搭建

```bash
cd intraday-trader
cp .env.example .env
# 编辑 .env，填入 Alpaca 密钥（使用富途时还需填入 FutuOpenD 参数）

uv venv && source .venv/bin/activate
uv sync
uv pip install -e .
```

验证安装：

```bash
intraday --help
```

预期输出：显示可用命令列表（`backtest`、`data`、`update-data`、`live`、`dashboard`、`generate-report`）。

## 第 2 步：配置策略和回测参数

打开 `config.yml`，确认以下关键参数：

```yaml
data:
  ticker: "SPY"
  start_date: "2023-01-01"
  end_date: "2023-06-30"
  timeframe_value: 15
  timeframe_unit: "Minute"

backtest:
  initial_cash: 100000.0
  commission: 0.001        # 0.1% 佣金
  slippage_perc: 0.001     # 0.1% 滑点
```

`strategies` 段中每个策略的 `params` 控制单次回测参数，`opt_ranges` 控制参数优化的搜索范围。

## 第 3 步：拉取行情数据

```bash
intraday update-data
```

这一步会：
1. 从 `data.provider` 指定的行情源拉取配置标的前一日的分钟线数据
2. 写入 `output/cache/` 本地缓存
3. 写入数据库（根据 `database.backend` 配置）
4. 运行数据质量检查，输出 `output/data_qc_*.json`

预期输出：

```
INFO - Fetching data for SPY...
INFO - Data updated and cached successfully.
INFO - Data quality check completed: 0 anomalies found.
```

如果网络不通或凭证错误，会看到具体报错。检查 `.env` 和网络后重试。

## 第 4 步：回测

### 运行全部已配置策略

```bash
intraday backtest run
```

这会依次运行买入持有基准和 `strategies` 段中启用的每个策略。

预期输出（截取关键行）：

```
Buy & Hold Benchmark:
  Final Portfolio Value: $108,234.56
  Total Return: 8.23%
  Sharpe Ratio: 0.85
  Max Drawdown: 12.4%

Mean Reversion (Z-Score):
  Final Portfolio Value: $112,450.00
  Total Return: 12.45%
  Sharpe Ratio: 1.32
  Max Drawdown: 7.8%
  Win Rate: 58.3%
  Number of Trades: 47
```

### 只运行指定策略

```bash
intraday backtest run --strategy ema_crossover
```

### 生成回测图表

回测运行后，图表保存在 `output/charts/` 目录。图表包含：
- 策略净值曲线
- 买入持有基准对比
- 交易点位标记
- 回撤区间标注

### 只运行基准

```bash
intraday backtest benchmark
```

这只会跑买入持有策略，用于快速确认数据加载和回测框架正常，不执行任何主动策略。

## 第 5 步：参数优化

```bash
intraday backtest optimise --strategy mean_reversion
```

`optimise` 和 `optimize` 是同一个命令的别名。

这一步会：
1. 读取 `strategies.mean_reversion.opt_ranges` 中定义的参数搜索范围
2. 按网格搜索逐个尝试参数组合
3. 输出按夏普比率或最终资产排序的前十名结果

预期输出：

```
Optimization Results (Top 10):
Rank  Sharpe  Final Value  Params
1     1.45    $118,200     zscore_period=20, zscore_upper=2.5, ...
2     1.42    $116,800     zscore_period=25, zscore_upper=2.0, ...
...
```

搜索空间越大耗时越长。`max_cpus: "auto"` 会自动使用 CPU 核心数减一来并行执行。

## 第 6 步：回补缺失字段

部分行情源（如某些 Alpaca 免费账户）不返回 `trade_count` 和 `vwap`。可以在拉取数据后补上：

```bash
intraday data backfill --fields trade_count,vwap
```

如果只是想确认当前数据完整性，看 `intraday update-data` 的质量检查报告即可。

## 第 7 步：启动纸上交易

```bash
intraday live
```

这一步启动 asyncio 事件循环，核心流程：

1. 连接券商，获取账户和持仓快照
2. 订阅实时行情（Alpaca WebSocket，富途使用 REST 轮询）
3. 每收到一根新 bar，运行实时均值回归策略生成信号
4. 信号经过风控检查后，走执行管线（信号 → 目标 → 订单计划 → 下单）
5. 订单状态变更时更新持仓和绩效快照

日志会实时输出到控制台，典型输出：

```
INFO - Starting live trading session for AAPL
INFO - Account connected: ID=xxx, Cash=$98,500.00
INFO - BUY SIGNAL: Z-Score=-2.35 (oversold)
INFO - Risk check passed: VaR=1.2%, exposure=0.3%
INFO - Order submitted: id=abc123, BUY 10 AAPL @ market
INFO - Order filled: id=abc123, 10 AAPL @ 185.30
```

按 `Ctrl+C` 优雅退出，系统会取消所有未成交订单并记录当前状态。

### no_fill_test_mode（测试单模式）

在 `config.yml` 中开启后，订单会以大幅偏移的限价单提交（默认偏移 10%），确保不会实际成交。适用于：

- 验证下单链路和订单状态处理逻辑
- 检查风控拦截是否正确触发
- 在生产前做完整的干跑测试

```yaml
live_trading:
  no_fill_test_mode:
    enabled: true
    price_offset_pct: 0.10
    test_duration_seconds: 60
    max_test_orders: 5
```

## 第 8 步：生成日报

```bash
intraday generate-report
```

产出 `output/daily_report_YYYYMMDD.json`，包含：

- 当前净值、现金、持仓
- 当日收益率和累计收益率
- 夏普比率、最大回撤、VaR
- 交易成本合计
- 换手率
- 基准对比

示例输出：

```json
{
  "report_timestamp": "2026-06-22T16:00:00",
  "current_value": 108450.00,
  "summary": {
    "total_return": 0.0845,
    "sharpe_ratio": 1.32,
    "max_drawdown": 0.078,
    "win_rate": 0.583
  }
}
```

## 第 9 步：查看仪表盘

```bash
intraday dashboard
```

启动 Streamlit 应用，默认访问 `http://localhost:8501`。

页面展示：
- 四个 KPI 卡片（总收益、夏普比率、最大回撤、VaR）
- 净值曲线
- 最近交易列表

侧边栏可调整加载天数范围（默认最近 7 天）。

## 快速检查清单

初次使用本项目的推荐顺序：

- [ ] `uv sync && uv pip install -e .` 安装依赖
- [ ] 配置 `.env` 和 `config.yml`
- [ ] `intraday backtest benchmark` 验证回测链路
- [ ] `intraday backtest run` 跑完整回测
- [ ] `intraday backtest optimise` 试试参数优化
- [ ] `intraday live` 在 `no_fill_test_mode` 下干跑
- [ ] 关闭 `no_fill_test_mode`，在 Paper Trading / 模拟环境中实跑
- [ ] `intraday generate-report` 生成日报
- [ ] `intraday dashboard` 打开仪表盘检查数据

## 常见工作流模式

### 模式 A：策略开发循环

```
修改策略代码 → make lint → make backtest → 看回测结果 → 调参数 → 重复
```

### 模式 B：实盘上线前验证

```
intraday backtest optimise       # 找到最优参数
intraday live                    # no_fill_test_mode 干跑
intraday generate-report         # 检查日报
# 确认风控、订单链路和日志正常后
# 修改 config.yml 关闭 no_fill_test_mode
intraday live                    # 正式纸上/模拟交易
```

### 模式 C：数据维护

```
intraday update-data             # 每周拉取最新行情
intraday data backfill           # 回补缺失字段
# 检查 output/data_qc_*.json 确认数据质量
```
