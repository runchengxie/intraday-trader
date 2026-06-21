# 当前项目概览

本文汇总当前代码仓库的实际能力、测试覆盖和已知技术债。写新功能或修改现有模块时请先读本文，避免重复劳动或踩已知坑。

## 已实现能力

### 策略

- 三类内置策略：`MeanReversionZScoreStrategy`、`EMACrossoverStrategy`、`CustomRatioStrategy`。
- 一类基准：`BuyAndHoldStrategy`。
- 策略注册表支持 `config.yml` 驱动，无需改代码即可切换和配置策略。
- 均值回归策略支持 `filtered_close` 输入和限价单参数。
- EMA 交叉策略支持 ADX 过滤和移动止损。
- 参数优化支持网格搜索和并行执行。

### 数据

- Alpaca API 历史行情拉取，支持分钟级数据。
- 多级缓存：内存、本地 Parquet/SQLite、远程 PostgreSQL/TimescaleDB。
- `DBHandler` 支持 `sqlite`、`parquet`、`postgresql` 三种后端，PostgreSQL 下自动创建 hypertable。
- `intraday data backfill` 回补 `trade_count` 和 `vwap` 字段。
- 降级估算：缺 `trade_count`/`vwap` 时回测可自动估算，也可设置 `require_full_fields` 强制拒绝。
- 数据质量检查：时间戳单调性、缺失 bar、空值、价格跳变。

### 回测

- 基于 Backtrader 的事件驱动回测。
- 统一入口 `intraday_trader_air.backtest.engine.run_backtest()`。
- 输出指标：最终资产、交易次数、胜率、净利润、夏普比率、最大回撤、年化收益、VaR、CVaR、换手率。
- 含股息总回报基准。

### 实盘联调

- Alpaca REST 下单、账户查询、持仓查询、订单状态查询。
- Alpaca WebSocket 行情和订单更新订阅。
- `asyncio.Queue` 事件循环处理 trade、bar、订单更新。
- `RiskManager` 检查 VaR、流动性、点差、市场冲击、杠杆、敞口、价格跳变、成交量异常。
- `ExceptionHandler` 重试和熔断。
- `ConsistencyValidator` 信号、成交、绩效一致性检查。
- `no_fill_test_mode` 测试单和自动撤单。
- `PerformanceAnalyzer` 风控指标、交易成本、换手率、集中度、相对基准表现。

### 仪表盘

- Streamlit 应用从数据库读取交易日志和绩效快照并展示。

### 基础设施

- 统一 CLI 入口 `intraday`，支持 `backtest run/optimise/optimize/benchmark`、`data backfill`、`update-data`、`generate-report`、`live`、`dashboard`。
- 多阶段 Docker 镜像构建。
- Docker Compose profiles：`live`（交易机器人 + TimescaleDB）和 `db`（仅数据库）。
- Makefile 快捷命令。
- Ruff 格式化和 lint。
- Python 3.10 锁定，`pyproject.toml` 限制 `<3.11`。

## 测试覆盖

### 单元测试（`tests/unit/`）

| 文件 | 覆盖内容 |
| --- | --- |
| `test_configuration.py` | 配置加载、字段校验、时间窗错误处理 |
| `test_strategies.py` | EMA 交叉信号、均值回归信号、Ratio 策略信号、过滤器、限价单参数 |
| `test_data_quality.py` | 时间戳检查、缺失 bar、空值、价格跳变、报告生成 |
| `test_db_handler_storage.py` | SQLite 读写、Parquet 读写、upsert 去重、Parquet 引擎降级跳过 |
| `test_risk_manager.py` | VaR、流动性、点差、市场冲击、杠杆、敞口、价格跳变、成交量异常 |
| `test_performance_analyzer.py` | 收益计算、风险指标、交易成本、换手率、报告生成、图表输出 |
| `test_exception_handler.py` | 重试、熔断、错误分类和严重等级 |
| `test_broker_handler.py` | 下单、API 错误处理、账户查询 |
| `test_live_system.py` | 交易循环、信号路由到订单执行 |
| `test_cli.py` | CLI 命令解析、未知命令报错、帮助输出 |

### 集成测试（`tests/integration/`）

| 文件 | 覆盖内容 |
| --- | --- |
| `test_db_integration.py` | 数据库连接、表创建、hypertable 验证、数据读写、upsert、交易日志、绩效快照 |
| `test_broker_integration.py` | Alpaca REST 连接、行情获取、订单提交 |

### 端到端测试（`tests/e2e/`）

| 文件 | 覆盖内容 |
| --- | --- |
| `test_backtest_workflow.py` | 策略加载、数据馈送、回测执行、结果验证的完整链路 |

### 已知测试覆盖缺口

- `scripts/run_backfill_data.py` 没有独立测试，只通过 CLI 间接验证。
- `consistency_validator.py` 没有独立单元测试。
- `dashboard_app.py` 没有自动化测试。
- `plotting.py` 没有自动化测试。
- Docker 容器内测试尚未建立。

## 已知技术债

### 需要修复的问题

1. `intraday live` 命令行入口没有创建并传入 `DBHandler`，实盘快照默认不写入数据库。
2. `EnhancedTradingSystem.stop_trading()` 调用了尚未实现的 `generate_comprehensive_report()`。
3. `start_live_trading()` 中存在重复的初始账户和持仓刷新逻辑。
4. `run_live_trading.py` 内部有一个旧版 YAML 加载函数，比 `configuration.py` 的 `load_app_config()` 弱，需要统一。

### 未覆盖的真实交易细节

- 多标的组合。
- 交易所撮合延迟和订单簿深度。
- 真实交易费用（SEC 费用、交易所费用）。
- 断路器。
- 历史行情回放测试。

### 架构层面待改进

- 策略注册表目前只支持单标的策略，多标的策略需要扩展。
- 因子归因（滚动 beta、信息比率、多因子回归）尚未内置。
- 实盘端接入的 Alpaca 只覆盖 REST 和 WebSocket，未接入 FIX 或其他低延迟链路。

## 变更记录

- 2026-06-21：文档全面中文化，README、AGENTS.md、docs/ 全部翻译并整理。cli.py 重构为显式命令解析。新增 test_cli.py。修复 test_live_system.py 和 test_db_handler_storage.py 的 importorskip 缺失。
