# Python 算法交易框架（中文指南）

本项目是一个现代化、可安装的 Python 框架，用于开发、回测与部署算法交易策略。默认采用轻量级的 SQLite 缓存，方便在本地快速迭代；当需要更高性能或横向扩展时，可以无缝切换到 TimescaleDB。框架还提供风险管理、绩效分析以及 Alpaca 纸上交易 API 的接入工具。

## 关键特性

- **工程化架构**：通过多阶段 `Dockerfile` 与 `docker-compose.yml` 进行容器化管理，确保运行环境可复现、易扩展。
- **自动化工作流**：内置 GitHub Actions，可按日/周定时执行数据更新与回测任务。
- **可安装的 CLI 工具集**：项目以 Python 包形式发布，提供数据更新、回测、实盘运行和报表生成等命令行入口。
- **灵活的数据持久化方案**：默认使用 SQLite 或 Parquet 缓存，也可以在需要时切换到 TimescaleDB。
- **多策略支持**：
  - *均值回归（Z-Score）*：可选卡尔曼滤波，用于价格平滑处理。
  - *趋势跟随（EMA 交叉）*：可选 ADX 过滤器以确认趋势强度。
  - *动量策略（Price/MA Ratio）*：基于价格与长期均线比值的信号。
- **风险管理模块**：下单前进行流动性、头寸敞口等检查，降低异常交易风险。
- **绩效分析与可视化**：
  - 基于 `backtrader` 的回测引擎。
  - `PerformanceAnalyzer` 输出收益、换手率、交易成本及夏普/索提诺等指标。
  - `Streamlit` 仪表盘展示实时表现与风险指标。
- **稳健的实盘执行引擎**：基于 `asyncio`，具备 WebSocket 断线重连与状态校验机制。

## 架构总览

整体架构围绕一个中心化的数据层展开，既服务回测又支持实盘。以下流程图展示了各模块之间的交互关系：

```mermaid
flowchart LR
    subgraph Core_Services["核心服务"]
        direction LR
        DB_Handler[DBHandler]
        Database[(TimescaleDB)]
        DB_Handler -- "管理" --> Database
    end

    subgraph Live_Trading["实时交易系统 (run-live)"]
        direction TB
        ETS[EnhancedTradingSystem]
        Broker[BrokerAPIHandler]
        Strat[Trading Strategy]

        ETS -- "下单" --> Broker
        Broker -- "推送行情" --> ETS
        ETS -- "获取信号" --> Strat
    end

    subgraph Backtest_and_Analytics["回测与分析"]
        direction TB
        BacktestScript[run-backtest]
        ReportScript[run-generate-report]
        DashboardScript[run-dashboard]
        Data_Utils[data_utils.py]

        BacktestScript -- "调用" --> Data_Utils
        Data_Utils -- "提供数据" --> BacktestScript
    end

    subgraph Automation["自动化 (GitHub Actions)"]
        direction TB
        Cron_Data[每日数据更新]
        Cron_Backtest[每周回测]

        Cron_Data --> Live_Trading
        Cron_Backtest --> Backtest_and_Analytics
    end

    Live_Trading -- "记录交易与指标" --> DB_Handler
    Backtest_and_Analytics -- "查询历史数据" --> DB_Handler
    ReportScript -- "拉取数据" --> DB_Handler
    DashboardScript -- "可视化数据" --> DB_Handler

    classDef core fill:#f9f,stroke:#333,stroke-width:1px;
    classDef db fill:#cde,stroke:#333,stroke-width:2px;
    classDef automation fill:#ffc,stroke:#333,stroke-width:1px;
    class ETS,Broker,Strat,BacktestScript,ReportScript,DashboardScript,Data_Utils core;
    class DB_Handler,Database db;
    class Cron_Data,Cron_Backtest automation;
```

## 快速开始

你可以选择使用 Docker（可选，用于可复现/部署）或本地 Python 环境来运行项目。

| 场景 | 推荐方式 | 说明 |
| --- | --- | --- |
| 本地策略开发 / 快速回测 | 本地虚拟环境 | `uv sync && uv pip install -e .` 后即可使用 CLI，启动速度最快。
| 需要 TimescaleDB、CI 任务或课堂验收 | Docker（`--profile live`） | 容器一次性拉起交易服务与 TimescaleDB，环境完全可复现。
| 只想调试数据库 | Docker（`--profile db`） | 单独启动 TimescaleDB，供本地脚本或 BI 工具连接。

下面分别介绍两种方式的具体步骤，同时提供 `Makefile` 快捷命令供选择。

### 方式一：Docker（按需，可复现/部署用）

1. **克隆仓库**
   ```bash
   git clone https://github.com/runchengxie/algorithmic-trading-framework.git
   cd algorithmic-trading-framework
   ```

2. **创建环境变量文件**
   ```bash
   cp .env.example .env  # 如果仓库提供了示例文件，可直接复制
   ```
   若没有示例文件，可使用任意文本编辑器手动创建 `.env`，并填入以下内容：
   ```env
   APCA_API_KEY_ID="你的 Alpaca Paper Trading Key"
   APCA_API_SECRET_KEY="你的 Alpaca Secret"
   ALPACA_BASE_URL="https://paper-api.alpaca.markets"
   POSTGRES_PASSWORD="用于 TimescaleDB 的密码"
   ```

3. **启动服务**
   ```bash
   # 等价命令：make docker-live
   docker compose --profile live up trading-bot
   ```
   `--profile live` 会同时拉起交易机器人与 TimescaleDB；若只需要数据库，可执行 `docker compose --profile db up db`。
   使用 `CTRL+C` 停止服务，或通过 `docker compose down` 清理容器与网络。

### 方式二：本地 Python 环境

1. **创建虚拟环境**
   ```bash
   # 推荐使用 uv
   uv venv
   source .venv/bin/activate

   # 或者使用标准库 venv
   # python -m venv venv
   # source venv/bin/activate
   ```

2. **安装依赖并注册 CLI 命令**
   ```bash
   uv sync
   uv pip install -e .
   ```
   执行以上命令后会自动在虚拟环境中注册 `patf` 命令行入口，方便通过统一的 CLI 调用各个脚本。

3. **配置凭证**
   将 Alpaca API Key 写入 `.env` 或操作系统的环境变量中：
   ```bash
   export APCA_API_KEY_ID="你的 Key"
   export APCA_API_SECRET_KEY="你的 Secret"
   export ALPACA_BASE_URL="https://paper-api.alpaca.markets"
   ```

4. **运行命令行工具**
   - 更新行情数据：`patf run-update-data`
   - 回测策略：`patf run-backtest`
   - 生成报表：`patf run-generate-report`
   - 启动纸上交易：`patf run-live`

## 常用命令速查

项目根目录提供 `Makefile`，在安装完 CLI 后可以直接运行：

```bash
make help           # 查看所有常用命令
make backtest       # 本地回测
make update         # 更新数据缓存
make docker-live    # 容器模式启动交易服务 + DB
make docker-db      # 仅启动 TimescaleDB（容器）
```

## 项目结构

```
├── src/patf_trading_framework/   # 核心代码（策略、数据、风险、实盘引擎）
│   └── strategies/               # 策略包（含基类、注册表与具体策略实现）
├── tests/                        # 单元测试与集成测试
├── docs/                         # 文档与设计说明
├── notebooks/                    # Jupyter/研究用脚本
├── project_tools/                # 开发工具与辅助脚本
├── Makefile                      # 本地与 Docker 工作流统一入口
├── config.yml                    # 全局配置（策略参数、数据源、数据库）
├── docker-compose.yml            # Docker 编排配置
└── pyproject.toml                # 项目依赖与打包信息
```

## 常见问题（FAQ）

### 1. 一定要用 TimescaleDB 吗？
不需要。项目默认使用 SQLite/Parquet 缓存来降低门槛，等需要更长历史或多标的并发查询时，再切换到 TimescaleDB 即可。

### 2. Alpaca 账号必须是真实资金吗？
不需要。建议先使用 Alpaca Paper Trading（模拟账户）来测试策略。

### 3. Docker 是必须的吗？
不是。Docker 提供的是更稳的运行环境，但你完全可以在本地虚拟环境中直接运行脚本。

### 4. 如何扩展新策略？
在 `src/patf_trading_framework/strategies/` 下新增策略类，并在 `config.yml` 中配置相应参数，便可在 CLI 中切换使用。

### 5. 如何切换数据存储后端？
通过 `config.yml` 的 `database` 配置块即可。你可以选择：
- `sqlite:///output/trading.db`
- `parquet://output/cache`
- `postgresql+psycopg2://user:pass@host:5432/dbname`

