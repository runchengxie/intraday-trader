# Docker 使用指南

本文介绍 intraday-trader 的 Docker 部署方式，包括构建、profiles、环境变量注入和与本地开发的切换。

## 架构

`docker-compose.yml` 定义了两个服务：

- `db`：TimescaleDB（基于 PostgreSQL 16），提供持久化存储
- `trading-bot`：交易机器人，运行 `intraday live`

通过 Docker Compose profiles 控制启动哪些服务：

| Profile | 启动的服务 | 用途 |
| --- | --- | --- |
| `db` | 仅 TimescaleDB | 本地开发时只启动数据库，CLI 在本地跑 |
| `live` | TimescaleDB + trading-bot | 完整线上部署 |

## 构建镜像

```bash
docker compose build
# 或
make docker-build
```

`Dockerfile` 使用多阶段构建：

1. `builder` 阶段：用 `uv build` 打 wheel 包
2. `runner` 阶段：用 `python:3.10-slim` 作为运行基础镜像，从 builder 复制 wheel 并安装

最终镜像以非 root 用户 `trader` 运行，默认命令为 `intraday live`。

## 启动服务

### 仅启动数据库

用于本地开发：数据库跑在 Docker 里，CLI 在本地虚拟环境中执行。

```bash
docker compose --profile db up db
# 或
make docker-db
```

数据库默认暴露端口 `5432`，本地 CLI 可以直连：

```yaml
# config.yml（本地连 Docker 数据库）
database:
  backend: "postgresql"
  host: "localhost"
  port: 5432
  user: "trading_user"
  password: "your_password"
  dbname: "trading_db"
```

### 启动完整交易栈

```bash
docker compose --profile live up trading-bot
# 或
make docker-live
```

这会同时启动 TimescaleDB 和交易机器人。`trading-bot` 依赖 `db` 的健康检查（`pg_isready`），数据库就绪后才启动。

### 在容器内跑回测

```bash
docker compose --profile live run --rm trading-bot intraday backtest run --strategy ema_crossover
# 或
make docker-backtest ARGS='--strategy ema_crossover'
```

`--rm` 确保容器执行完后自动删除。

## 环境变量

### 交易机器人需要的变量

以下变量在 `docker-compose.yml` 中通过 `environment` 段注入：

| 变量 | 来源 | 说明 |
| --- | --- | --- |
| `APCA_API_KEY_ID` | 宿主机环境或 `.env` | Alpaca API Key |
| `APCA_API_SECRET_KEY` | 宿主机环境或 `.env` | Alpaca Secret Key |
| `ALPACA_BASE_URL` | 硬编码默认值 `https://paper-api.alpaca.markets` | Alpaca 接口地址 |
| `POSTGRES_PASSWORD` | `.env` 文件 | 数据库密码 |
| `DB_BACKEND` | 硬编码 `postgresql` | 固定使用 PostgreSQL |
| `DB_HOST` | 硬编码 `db` | 数据库容器名 |
| `DB_PORT` | 硬编码 `5432` | 数据库端口 |
| `DB_USER` | 硬编码 `trading_user` | 数据库用户 |
| `DB_NAME` | 硬编码 `trading_db` | 数据库名 |

### 注意

- `POSTGRES_PASSWORD` 必须存在。Docker Compose 会从项目根目录的 `.env` 文件读取，不会从宿主机全局环境变量读取 Shell 中已 export 的值
- Alpaca 凭证从宿主机环境变量注入。启动前确认已在 Shell 中 `export` 了 `APCA_API_KEY_ID` 和 `APCA_API_SECRET_KEY`，或者在 `.env` 中设置后通过其他方式注入
- 富途环境变量未在 `docker-compose.yml` 中预设。如需在容器中使用富途，需自行在 `environment` 段添加 `FUTU_HOST`、`FUTU_PORT` 等变量，且确保 FutuOpenD 的网络可达

## 数据持久化

`docker-compose.yml` 定义了一个命名卷 `timescale_data`：

```yaml
volumes:
  timescale_data:
```

数据库容器的数据目录挂载到这个卷上，容器删除后数据不会丢失。

交易机器人的 `output/` 目录挂载到宿主机：

```yaml
volumes:
  - ./output:/app/output
```

日志、图表、日报和缓存都在宿主机 `./output/` 下可见。

## Docker 与本地开发的切换

| 场景 | 数据库 | CLI | 适用 |
| --- | --- | --- | --- |
| 纯本地 | SQLite（默认） | 本地 `intraday` | 快速开发和回测 |
| 本地 + Docker 数据库 | Docker `db` 服务 | 本地 `intraday`，`config.yml` 中 `database.backend: postgresql` | 需要长历史存储但不想容器化 CLI |
| 全 Docker | Docker `live` profile | 容器内 `intraday` | 线上部署和 CI |

切换方式：修改 `config.yml` 的 `database.backend`，以及对应的 `host`/`port`/`user`/`password`/`dbname`。

## 常用排障

| 现象 | 可能原因 | 解决方法 |
| --- | --- | --- |
| `trading-bot` 反复重启 | 数据库健康检查未通过 | 等 `db` 服务输出 `database system is ready to accept connections` 后再试；增加 `start_period` |
| `POSTGRES_PASSWORD is not set` | `.env` 文件不存在或缺少该变量 | 在项目根目录创建 `.env` 并添加 `POSTGRES_PASSWORD=xxx` |
| Alpaca 认证失败 | 环境变量未注入到容器 | 确认 Shell 中已 `export APCA_API_KEY_ID=...`；或者在 `docker-compose.yml` 中直接写值（不推荐提交） |
| `output/` 目录权限错误 | 容器内 `trader` 用户与宿主机用户 UID 不匹配 | `chmod 777 output/` 或调整 Dockerfile 中的 UID |
| 富途连接失败 | FutuOpenD 在宿主机，容器内 `127.0.0.1` 指向容器自身 | 使用 `host.docker.internal` 替代 `127.0.0.1`（macOS/Windows），或使用宿主机真实 IP |
