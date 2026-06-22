# Streamlit 仪表盘指南

本文介绍 intraday-trader 的 Streamlit 仪表盘：启动方式、页面布局、数据来源和扩展方法。

## 启动

```bash
intraday dashboard
# 或
make dashboard
```

Streamlit 应用会在 `http://localhost:8501` 启动。如果端口被占用，Streamlit 会自动选择下一个可用端口。

仪表盘需要数据库中有数据才能展示。如果数据库为空，页面会显示"No performance snapshots found for the selected period"的警告。

## 页面布局

### 侧边栏

- `Days of data to load` 滑块：控制加载多少天的数据。默认 7 天，范围 1-90 天
- 数据通过 `@st.cache_data(ttl=600)` 缓存 10 分钟，短期内重复访问不会重新查库

### 主面板

#### KPI 卡片（四列）

| 指标 | 数据来源 |
| --- | --- |
| Total Return | 最新净值与初始资金的差异百分比 |
| Sharpe Ratio | `PerformanceAnalyzer.calculate_risk_metrics()` 中的 `sharpe_ratio` |
| Max Drawdown | `PerformanceAnalyzer.calculate_risk_metrics()` 中的 `max_drawdown` |
| Daily VaR (95%) | `RiskManager.calculate_var()` 的历史模拟法结果 |

#### 净值曲线

`st.line_chart` 绘制 `performance_snapshots` 表中 `portfolio_value` 的时间序列。

#### 最近交易列表

`st.dataframe` 展示 `trade_logs` 表内容，按时间倒序排列。列包括时间戳、标的、方向、数量、价格和佣金。

## 数据来源

仪表盘依赖两个数据库表：

### `performance_snapshots`

存储定期的净值快照：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `timestamp` | datetime | 快照时间 |
| `portfolio_value` | float | 此时的总净值（现金 + 持仓市值） |

只有在实盘交易过程中明确写入了快照，仪表盘才有数据。当前已知问题：`intraday live` 命令行入口没有创建并传入 `DBHandler`，实盘快照默认不写入数据库。

### `trade_logs`

存储每笔交易的记录：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `timestamp` | datetime | 成交时间 |
| `symbol` | string | 标的代码 |
| `side` | string | buy 或 sell |
| `quantity` | float | 成交数量 |
| `price` | float | 成交价格 |
| `commission` | float | 佣金 |
| `order_id` | string | 订单 ID |

### 数据写入路径

```
实盘事件循环 → 成交事件 → TradeLog 写入 DB → PerformanceSnapshot 写入 DB
                                        ↓
                              仪表盘从 DB 读取展示
```

如果 `DBHandler` 未在实盘启动时创建并传入 `EnhancedTradingSystem`，则快照和交易日志只存在于内存中，仪表盘无法读取。

## 扩展仪表盘

### 添加新指标卡片

在 `st.columns(4)` 后追加新列：

```python
col5 = st.columns(5)[4]
col5.metric("新指标名称", f"{new_value:.2f}")
```

### 添加新图表

在"Performance Charts"区域追加：

```python
st.subheader("我的新图表")
st.line_chart(my_dataframe)
```

Streamlit 原生支持的图表类型：`st.line_chart`、`st.area_chart`、`st.bar_chart`。也可用 `st.pyplot` 嵌入 Matplotlib 图表。

### 添加新的数据筛选维度

在侧边栏增加控件：

```python
symbol_filter = st.sidebar.selectbox("Symbol", ["ALL", "AAPL", "SPY"])
if symbol_filter != "ALL":
    trade_logs = trade_logs[trade_logs["symbol"] == symbol_filter]
```

### 添加告警/通知面板

当天有风控拦截或异常事件时，可在主面板顶部展示：

```python
alerts = db_handler.get_recent_alerts(hours=24)
if alerts:
    for alert in alerts:
        st.warning(alert["message"])
```

以上改动都在 `src/intraday_trader/dashboard_app.py` 中完成，保存后 Streamlit 会自动热重载页面。

## 排障

| 现象 | 原因 | 解决方法 |
| --- | --- | --- |
| 页面白屏或报错 | 数据库连接失败 | 检查 `config.yml` 的 `database` 段配置；确认数据库服务正在运行 |
| "No performance snapshots found" | 数据库中有数据但时间范围不对 | 增大侧边栏的加载天数 |
| "No performance snapshots found"（数据库确实为空） | 实盘未写入快照 | 检查 `intraday live` 是否正确创建并传入了 `DBHandler` |
| `streamlit` 未找到 | 未安装 dashboard 可选依赖 | `uv pip install -e ".[dashboard]"` |
| 图表不更新 | Streamlit 缓存未失效 | 刷新页面或等待缓存 TTL（10 分钟）过期 |
| 端口被占用 | 已有 Streamlit 实例在运行 | 停掉旧实例或指定新端口：`streamlit run --server.port 8502` |
