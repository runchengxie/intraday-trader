# 仓库协作指南

## 项目结构

生产代码位于 `src/intraday_trader_air/`。其中：

- `backtest/` 放置回测请求对象与执行入口。
- `strategies/` 放置策略基类、策略注册表和内置策略。
- `scripts/` 放置 CLI 子命令实现。
- `data_utils.py`、`db_handler.py`、`risk_manager.py`、`performance_analyzer.py`、`dashboard_app.py` 等模块组成数据、风控、分析和展示链路。

测试位于 `tests/`，分为 `unit`、`integration` 和 `e2e`。公共 fixture 放在 `tests/conftest.py`。根目录的 `Makefile`、`Dockerfile`、`docker-compose.yml` 和 `config.yml` 负责本地任务、镜像构建、服务编排和运行配置。

## 常用开发命令

```bash
uv sync
uv pip install -e .
intraday backtest run
intraday backtest run --strategy ema_crossover
intraday backtest optimise
intraday data backfill --fields trade_count,vwap
intraday update-data
intraday live
intraday dashboard
make lint
make fmt
make coverage
make docker-live
```

项目要求 Python 3.10。`pyproject.toml` 限制为 `>=3.10,<3.11`，不要把 CI 或本地开发环境偷偷升级到 3.11 以上再让错误信息替你写悬疑小说。

## 代码风格

- 使用四空格缩进。
- 行宽遵守 Ruff 的 88 字符限制。
- 模块、函数和变量使用 `snake_case`。
- 类名使用 `PascalCase`。
- 常量使用大写加下划线。
- 提交前运行 `uv run ruff check .` 和 `uv run ruff format .`。
- 如果必须忽略 lint 规则，请在评审说明里解释原因。

## 测试要求

常规测试：

```bash
uv run pytest
```

排除外部服务的测试：

```bash
uv run pytest -m 'not integration'
```

只运行集成测试：

```bash
uv run pytest -m integration
```

测试约定：

- 新测试文件应跟目标模块命名对应，例如 `tests/unit/test_risk_manager.py`。
- 能复用 `tests/conftest.py` 的 fixture 时优先复用，减少重复 mock。
- 访问 Alpaca、外部数据库或真实 WebSocket 的测试必须标记为 `integration`。
- 缺少外部依赖或凭证时，相关测试应明确跳过，避免在收集阶段直接失败。
- 变更策略、风控、订单执行或存储层时，需要补充对应单元测试。影响完整流程时，再补 e2e 测试。

## 配置与密钥

- 复制 `.env.example` 为 `.env`，在本地填写 Alpaca 和数据库凭证。
- 不要提交 `.env`、本地数据库、缓存、日志或图表输出。
- 切换存储后端时修改 `config.yml` 的 `database.backend`，可选值为 `sqlite`、`parquet`、`postgresql`。
- 使用 Docker live profile 时，`.env` 中必须有 `POSTGRES_PASSWORD`。
- 修改数据库表结构时，请同步更新 `DBHandler`、相关测试和 README 中的数据说明。

## 文档约定

本仓库文档以中文为主。写文档时遵守这些规则：

- 中文正文使用中文标点，例如 `（ ）`、`，`、`。`、`：`。
- 保留必要的行内代码引用，例如 `config.yml`、`intraday backtest run`。
- 避免中英混杂的长句。英文技术名词可保留，但解释尽量用中文。
- 少用双引号、粗体和破折号。
- 表达结论时直接写结论，少绕弯。

### 文档分工

| 文件 | 定位 | 更新原则 |
| --- | --- | --- |
| `README.md` | 项目入口：一句话介绍、快速开始、架构图、文档导航 | 功能增减或入口命令变化时更新 |
| `AGENTS.md`（本文件） | 仓库协作规范 | 代码风格、测试要求、提交流程变化时更新 |
| `docs/project-manual.md` | 项目说明书：能力清单、配置参考、CLI 详解、测试指南、已知技术债 | 功能、配置、测试覆盖或技术债变化时同步更新 |
| `docs/design-rationale.md` | 设计思路：策略选型、风控模型、绩效框架的考量 | 架构决策或设计理念变化时更新 |
| `docs/course-background.md` | 课程背景归档，仅作历史参考 | 一般不更新，除非需要补充来源信息

## 提交与 PR

提交信息使用简短的现在时描述，例如 `docs： polish README`、`tests： add cli parser coverage`。PR 中说明变更范围、测试结果、对交易行为或数据结构的影响。涉及仪表盘或 CLI 输出时，附上截图或命令输出片段。
