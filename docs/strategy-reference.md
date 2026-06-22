# 策略参考

本文详解四类内置策略的算法逻辑、信号公式、参数含义、适用场景和已知局限。

## 均值回归：Z-Score 滚动标准化

策略名：`MeanReversionZScoreStrategy`，注册表键：`mean_reversion`。

### 算法

每根新 bar 到来时：

1. 将当前价格加入长度为 `zscore_period` 的滚动窗口
2. 计算窗口内价格的均值 μ 和标准差 σ
3. 计算 Z-Score：`z = (当前价 - μ) / σ`
4. 当 z 低于 `zscore_lower`（超卖）时做多，当 z 高于 `zscore_upper`（超买）时做空
5. 持仓期间，当 z 回归到 `exit_threshold` 附近（多头 z ≥ exit_threshold，空头 z ≤ exit_threshold）时平仓

### 伪代码

```
每根 bar:
  price_history.append(price)
  如果 len(price_history) < zscore_period: 跳过
  μ = mean(price_history)
  σ = stdev(price_history)
  z = (price - μ) / max(σ, 1e-6)

  如果 无持仓:
    如果 z < zscore_lower:  做多
    如果 z > zscore_upper:   做空
  如果 有多头持仓 且 z >= exit_threshold: 平多
  如果 有空头持仓 且 z <= exit_threshold: 平空
```

### 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `zscore_period` | 20 | 滚动窗口长度（用于计算均值和标准差） |
| `zscore_upper` | 2.0 | 做空触发阈值。z 高于此值视为超买 |
| `zscore_lower` | -2.0 | 做多触发阈值。z 低于此值视为超卖 |
| `exit_threshold` | 0.0 | 平仓阈值。z 回归到此值附近时退出 |
| `order_type` | `market` | 下单类型：`market` 或 `limit` |
| `limit_price_offset_pct` | 0.0005 | 限价单的偏移比例（0.05%），仅在 `limit` 模式下生效 |

### 适用场景

- 震荡市：价格在一定区间内来回波动
- 标的有较强的均值回归特性（如 ETF、大盘指数）

### 局限

- 趋势市中会持续产生错误信号：价格持续上涨时很多 bar 都高于 `zscore_upper`，此时做空会不断亏损
- 假设价格分布平稳。如果标的的波动率结构发生变化（如突然放大），历史窗口的 σ 会滞后
- Z-Score 标准化抹去了绝对价格水平，无法区分"贵了 10% 再贵 10%"和"从正常跌到超卖"

---

## 趋势跟随：EMA 交叉 + ADX 过滤

策略名：`EMACrossoverStrategy`，注册表键：`ema_crossover`。

### 算法

每根新 bar 到来时：

1. 计算短期 EMA（`ema_short` 周期）和长期 EMA（`ema_long` 周期）
2. 计算 ADX（`adx_period` 周期）作为趋势强度指标
3. 当短期 EMA 上穿长期 EMA 且 ADX 高于 `adx_threshold` 时做多
4. 当短期 EMA 下穿长期 EMA 时平多（此时 ADX 不作为平仓条件）
5. 如果启用了 `trailing_stop_pct`：持仓期间记录最高收盘价，当价格回撤超过该比例时触发止损退出

### 伪代码

```
每根 bar:
  ema_short = EMA(close, period=ema_short)
  ema_long = EMA(close, period=ema_long)
  adx_val = ADX(bar, period=adx_period)

  如果 无持仓:
    如果 ema_short 上穿 ema_long 且 adx_val > adx_threshold: 做多
    如果 ema_short 下穿 ema_long 且 adx_val > adx_threshold: 做空（已禁用）
  如果 有多头持仓:
    如果 ema_short 下穿 ema_long: 平多
    如果 trailing_stop 触发: 平多

  如果 有多头持仓 且 当前收盘价 > highest_close:
    highest_close = 当前收盘价
    trailing_stop_price = highest_close * (1 - trailing_stop_pct)
```

### 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `ema_short` | 12 | 短期 EMA 周期 |
| `ema_long` | 26 | 长期 EMA 周期 |
| `adx_period` | 14 | ADX 计算周期 |
| `adx_threshold` | 25.0 | ADX 阈值。ADX 高于此值时认为趋势足够强，允许开仓 |
| `trailing_stop_pct` | 0.015 | 移动止损比例（1.5%）。设为 0 或 None 则禁用 |

### 适用场景

- 趋势市：价格有明确的单边方向
- ADX 高于 25 的环境（此时震荡市的假信号会被过滤掉）

### 局限

- 震荡市中 EMA 交叉频繁，即使有 ADX 过滤也可能产生连续小额亏损
- ADX 只衡量趋势强度不判断方向，EMA 交叉的方向信号可能和实际的量价行为不一致
- 移动止损可能在趋势中的正常回调时过早离场

---

## 趋势跟随补充：价格与长期均线比例

策略名：`CustomRatioStrategy`，注册表键：`custom_ratio`。

### 算法

每根新 bar 到来时：

1. 计算长期均线（`long_ma_period` 周期的 SMA）
2. 计算比值 `ratio = 当前收盘价 / 长期均线`
3. 当 ratio 低于 `buy_threshold`（价格相对均线便宜）时做多
4. 当 ratio 高于 `sell_threshold`（价格相对均线贵）时做空
5. 当 ratio 回到 `exit_threshold` 附近时平仓

### 伪代码

```
每根 bar:
  long_ma = SMA(close, period=long_ma_period)
  ratio = close / long_ma

  如果 无持仓:
    如果 ratio < buy_threshold:   做多
    如果 ratio > sell_threshold:  做空
  如果 有多头持仓 且 ratio >= exit_threshold: 平多
  如果 有空头持仓 且 ratio <= exit_threshold: 平空
```

### 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `long_ma_period` | 50 | 长期均线的计算周期 |
| `buy_threshold` | 0.98 | 做多阈值。ratio 低于此值视为便宜 |
| `sell_threshold` | 1.02 | 做空阈值。ratio 高于此值视为贵 |
| `exit_threshold` | 1.0 | 平仓阈值。ratio 回归到 1.0 附近时退出 |

### 适用场景

- 适合作为趋势策略的简化基准：如果 EMA+ADX 策略没有显著优于这个简单比例策略，那么 EMA+ADX 的复杂度就不值得
- 也适合长周期趋势判断

### 局限

- 完全依赖价格与均线的关系，不区分震荡和趋势
- 单均线策略在强烈趋势中可能过早离场
- 没有成交量或波动率确认

---

## 买入持有基准

策略名：`BuyAndHoldStrategy`，注册表键：`buy_and_hold`。

### 算法

在第一个 bar 时全仓买入，之后不再操作。

### 伪代码

```
第一个 bar:
  如果 无持仓:
    size = int(可用现金 * size_pct / 当前价)
    买入(size)
```

### 参数

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `size_pct` | 1.0 | 用于购买的资金比例。1.0 表示全仓 |

### 定位

- 判断主动策略是否贡献了 alpha（如果主动策略跑不赢买入持有，说明策略没有超额收益）
- 支持含股息总回报（`benchmark.total_return: true`），避免低估基准收益

---

## 策略注册表

四种策略都注册在 `src/intraday_trader/strategies/__init__.py` 的 `REGISTRY` 字典中：

```python
REGISTRY = {
    "ema_crossover": EMACrossoverStrategy,
    "mean_reversion": MeanReversionZScoreStrategy,
    "custom_ratio": CustomRatioStrategy,
    "buy_and_hold": BuyAndHoldStrategy,
}
```

在 `config.yml` 中通过 `strategies.<key>` 段配置策略后，回测引擎会从注册表加载对应类。

添加新策略时，创建一个继承 `BaseStrategy` 的新类，实现 `generate_signal()` 和 `should_exit()` 方法，然后把类加入 `REGISTRY` 即可。

## 策略对比

| 维度 | 均值回归 | EMA+ADX | 比例策略 | 买入持有 |
| --- | --- | --- | --- | --- |
| 收益来源 | 价格偏离回归 | 趋势延续 | 价格相对均线 | 市场 beta |
| 适合市场 | 震荡市 | 趋势市 | 通用 | 任何市场 |
| 交易频率 | 中等（阈值触发） | 低（交叉不频繁） | 低 | 一次性 |
| 最大风险 | 趋势中持续逆势 | 震荡中反复止损 | 极端行情失效 | 市场系统性风险 |
| 复杂度 | 低（2 个参数） | 中（4 个参数） | 低（4 个参数） | 极低 |
