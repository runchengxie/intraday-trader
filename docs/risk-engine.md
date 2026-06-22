# 风控引擎说明

本文展开 `RiskManager` 的分层检查逻辑、各参数含义、调优思路和扩展示例。

## 设计思路

风控分为两层，各司其职：

- 行情层：每次行情更新时自动运行，检查数据异常和极端行情。频率高、计算轻，在事件循环内完成
- 下单层：实际下单前调用，检查当前持仓和账户状态。只在有下单需求时才执行

两层任意一层的拦截都能阻止订单提交，但含义不同：行情层拦截说明市场状态异常（可能不是下单的好时机），下单层拦截说明当前风险敞口已达到上限。

## 行情层检查

`RiskManager.update_market_data(price, volume)` 在每根新 bar 到来时执行以下四项检查：

### 价格跳变检测

```
参数：price_jump_threshold（默认 0.05，即 5%）
逻辑：abs(最新收益率) > price_jump_threshold → 告警
```

收益率 = (当前价 - 上一根 bar 收盘价) / 上一根 bar 收盘价。

单根 bar 内涨跌超过 5% 通常意味着数据错误或极端事件。此检查只告警不直接阻止交易，因为真正的极端行情下你可能反而需要快速反应。

### 成交量异常检测

```
参数：volume_spike_threshold（默认 3.0）
逻辑：当前成交量 > 近 10 根 bar 平均成交量 * volume_spike_threshold → 告警
```

成交量突然放大 3 倍以上可能与重大新闻或流动性事件有关。此时市场冲击成本可能被低估，下单应谨慎。

### 流动性检查

```
参数：min_liquidity_volume（默认 1000）
逻辑：当前成交量 < min_liquidity_volume → 告警
```

成交量过低时流动性差，市价单滑点大，限价单可能无法成交。

### 数据质量检查

```
逻辑：price <= 0 或 volume < 0 → 告警
```

防止因数据源异常（如 API 返回错误值）导致后续计算崩溃。

## 下单层检查

### 流动性与冲击成本检查

`RiskManager.check_liquidity_and_impact(order_size, recent_avg_volume, current_volatility, bid_ask_spread_pct)`

```
参数：max_order_participation_ratio（默认 0.02）
逻辑：订单量 / 近期平均成交量 > max_order_participation_ratio → 拒绝
```

防止单笔订单占比过高，在流动性不足时推高成交成本。0.02 是保守值，适用于中等流动性标的。大市值标的可以上调到 0.05-0.10。

```
参数：max_bid_ask_spread_pct（默认 0.005）
逻辑：买卖价差 > max_bid_ask_spread_pct → 告警
```

0.5% 的价差阈值在美股中等流动性标的上偏宽松，目的是在正常时段不阻止交易，只在价差异常扩大时拦截。

```
参数：market_impact_coefficient（默认 0.5）
冲击成本估算 = market_impact_coefficient * sqrt(订单量 / 日均量) * 当前波动率
```

这是简化的平方根冲击模型。0.5 是偏保守的估计，实盘前建议拿出历史数据校准。

### 杠杆与敞口检查

`RiskManager.check_leverage_and_exposure()`

```
参数：max_gross_exposure（默认 1.5）
逻辑：(多头市值 + 空头市值绝对值) / 净值 > max_gross_exposure → 拒绝
```

1.5 意味着多空各 75% 仓位可以共存。

```
参数：max_leverage（默认 2.0）
逻辑：总资产 / 净值 > max_leverage → 拒绝
```

在 Alpaca 纸上交易环境中，实际杠杆通常受限于账户类型（如 Reg T margin 账户最高 2 倍）。

```
参数：max_concentration（默认 0.3）
逻辑：单标的市值 / 净值 > max_concentration → 拒绝
```

单标的 30% 上限在当前单标的策略下意义不大，为多标的扩展预留。

## VaR 计算

`RiskManager.calculate_var(portfolio_value, method)`

### 历史模拟法

```
取收益率序列的 alpha 分位数
VaR_amount = abs(percentile(returns, alpha * 100)) * portfolio_value
```

例如 `confidence_level=0.05` 时，取历史收益率最差的 5% 分位。

### 参数法

```
假设收益率服从正态分布
VaR_amount = abs(norm.ppf(alpha, mean(returns), std(returns))) * portfolio_value
```

参数法依赖正态假设。日内策略的收益率通常有肥尾和偏度，参数法会低估真实尾部风险。推荐使用历史模拟法（默认）。

### 滚动 VaR

RiskManager 还支持计算滚动 VaR 序列，用于观察风险敞口在时间上的变化趋势。

## 参数调优思路

### 偏保守场景（实盘初期）

```
max_order_participation_ratio: 0.01
max_bid_ask_spread_pct: 0.003
max_var: 0.03
max_concentration: 0.2
```

适合刚上实盘、需要观察系统行为的阶段。订单较小，风险限制较紧。

### 偏积极场景（已验证的策略）

```
max_order_participation_ratio: 0.05
max_bid_ask_spread_pct: 0.01
max_var: 0.08
max_concentration: 0.5
```

适合经过充分回测和纸上交易验证的策略。前提是标的流动性足够承接更大订单。

### 参数校准流程

1. 收集标的至少 6 个月的历史分钟线数据
2. 用历史数据回测计算实际的成交量分布、价差分布和波动率分布
3. 将参数设在比历史最差情况略宽松但能覆盖 99% 正常场景的水平
4. 在模拟环境中跑 1-2 周，观察风控拦截次数和拦截原因
5. 根据实际拦截情况微调

## 扩展风控：加入新检查

在 `RiskManager` 中加入新检查的模式：

1. 行情层：在 `_perform_risk_checks()` 方法中添加新的检查函数
2. 下单层：在 `check_liquidity_and_impact()` 或新建一个 `check_*` 方法
3. 在 `config.yml` 的 `risk_limits` 段中添加对应参数

示例：加入"单日最大亏损限制"：

```python
# 在 RiskManager 中添加
def check_daily_loss_limit(self, daily_pnl: float, portfolio_value: float) -> bool:
    limit_pct = self.config.get("max_daily_loss_pct", 0.05)
    return abs(daily_pnl) / portfolio_value < limit_pct
```

然后在 `config.yml` 中添加：

```yaml
live_trading:
  risk_limits:
    max_daily_loss_pct: 0.05
```

## 注意事项

- 风控参数是最后一道防线，不能替代策略本身的止损逻辑。策略应在信号层面就避免在不利状态下开仓
- 模拟环境中风控拦截的行为可能和实盘不同。例如富途 SIMULATE 环境中的价差和成交量是模拟值
- VaR 计算需要至少 30 个收益率数据点（约一个多月），在此之前 RiskManager 会返回 None 并记录警告
- 所有风控检查的日志级别为 WARNING 和 ERROR，建议在实盘中接入告警通道
