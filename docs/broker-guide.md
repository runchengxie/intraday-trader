# 券商接入指南

本文介绍如何接入 Alpaca 和富途 FutuOpenD 两个券商通道，包括环境变量、config.yml 配置、安装步骤和常见排障。

## Alpaca

### 前置条件

1. 注册 [Alpaca Markets](https://alpaca.markets/) 账号
2. 在 Alpaca Dashboard 中生成 Paper Trading 的 API Key 和 Secret Key
3. 记录 Paper Trading 的接口地址（通常为 `https://paper-api.alpaca.markets`）

### 安装

Alpaca 是默认券商，核心依赖 `alpaca-trade-api` 已包含在基础安装中：

```bash
uv sync
uv pip install -e .
```

### 环境变量

在 `.env` 中设置：

```env
APCA_API_KEY_ID="PKXXXXXXXXXXXX"
APCA_API_SECRET_KEY="XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
ALPACA_BASE_URL="https://paper-api.alpaca.markets"
```

- `ALPACA_BASE_URL` 指向 Paper Trading 环境时订单不会产生真实资金变动
- 实盘时改为 `https://api.alpaca.markets`，且必须使用 Live Trading 的 Key

### config.yml 配置

```yaml
live_trading:
  broker:
    name: "alpaca"

data:
  provider:
    name: "alpaca"
```

当 `broker` 或 `provider` 段不存在时，系统自动回到 Alpaca，向后兼容旧版配置文件。

### 支持能力

- REST 下单（市价单、限价单）
- 账户查询、持仓查询、订单状态查询
- WebSocket 实时行情和订单更新推送
- 回测数据：历史分钟线和日线

### 排障

| 现象 | 可能原因 | 解决方法 |
| --- | --- | --- |
| `alpaca_trade_api.rest.APIError: authentication failed` | Key 或 Secret 错误 | 检查 `.env` 中 `APCA_API_KEY_ID` 和 `APCA_API_SECRET_KEY`；确认 Key 与 `ALPACA_BASE_URL` 的 Paper/Live 环境匹配 |
| `ConnectionError` 或超时 | 网络不通 | 检查能否访问 `https://paper-api.alpaca.markets`；确认没有代理阻断 |
| 回测数据为空 | 标的代码不对或日期范围无数据 | 确认标的在 Alpaca 可用；日期不要超过 Alpaca 免费账户的历史数据限制 |
| WebSocket 连不上 | 网络或凭证问题 | Alpaca WebSocket 地址与 REST 不同（`wss://paper-api.alpaca.markets/stream`），检查防火墙是否允许 WebSocket 连接 |

## 富途 FutuOpenD

### 前置条件

1. 下载并安装 [FutuOpenD](https://www.futunn.com/download/openAPI) 网关程序
2. 在 FutuOpenD 中登录富途账户
3. 确认 FutuOpenD 的 API 端口（默认 11111）已开放

### 安装

富途支持是可选的，需要额外安装 `futu-api`：

```bash
uv pip install -e ".[futu]"
```

### 环境变量

在 `.env` 中设置（均为可选，有默认值）：

```env
# 以下均有默认值，不设置也能运行
FUTU_HOST="127.0.0.1"        # FutuOpenD 地址，默认 127.0.0.1
FUTU_PORT="11111"            # FutuOpenD 端口，默认 11111
FUTU_TRD_ENV="SIMULATE"      # 交易环境：SIMULATE 或 REAL
FUTU_MARKET="HK"             # 市场：HK / US / CN
FUTU_UNLOCK_PWD=""           # REAL 模式下的交易解锁密码
```

环境变量的优先级高于 `config.yml` 中的对应参数。如果两边都不设，适配器使用代码中的默认值。

### config.yml 配置

完整的富途配置示例：

```yaml
live_trading:
  broker:
    name: "futu"
    market: "HK"              # HK / US / CN
    mode: "simulate"          # simulate / real
    host: "127.0.0.1"         # FutuOpenD 所在机器
    port: 11111               # FutuOpenD API 端口

data:
  provider:
    name: "futu"
    market: "HK"
    host: "127.0.0.1"
    port: 11111
```

最小配置（仅指定 name，其余取默认值）：

```yaml
live_trading:
  broker:
    name: "futu"

data:
  provider:
    name: "futu"
```

### 市场代码说明

| 代码 | 含义 | 标的格式示例 |
| --- | --- | --- |
| `HK` | 港股 | `00700`、`09988`（自动加 `HK.` 前缀） |
| `US` | 美股 | `AAPL`、`TSLA`（自动加 `US.` 前缀） |
| `CN` | A 股 | `600000`、`000001`（6 开头加 `SH.`，其余加 `SZ.`） |

可以直接传入带前缀的完整代码（如 `HK.00700`），适配器不再追加前缀。

### 交易环境

| 值 | 说明 | 适用场景 |
| --- | --- | --- |
| `SIMULATE` | 模拟交易 | 策略联调、风控验证、开发阶段首选 |
| `REAL` | 真实交易 | 实盘，需要设置 `FUTU_UNLOCK_PWD` 环境变量 |

切换为 `REAL` 时，适配器在初始化阶段会调用 `unlock_trade(password)` 解锁交易。如果 `FUTU_UNLOCK_PWD` 未设置或密码错误，初始化会直接抛出异常。

### 支持能力

- REST 风格下单（市价单、限价单）
- 账户查询、持仓查询、订单状态查询、批量撤单
- 历史 K 线：1/5/15/30/60 分钟和日线
- 支持港股、美股、A 股三个市场

### 当前局限

- 行情和订单状态走 REST 轮询，未接入 WebSocket 实时推送
- 订单类型只支持市价单（`OrderType.MARKET`）和限价单（`OrderType.NORMAL`）
- 止损单、条件单等复杂订单类型暂不支持
- 模拟环境的成交模拟行为依赖 FutuOpenD 自身，成交率和延迟不受本项目控制

### 排障

| 现象 | 可能原因 | 解决方法 |
| --- | --- | --- |
| `ConnectionRefusedError` | FutuOpenD 未启动或端口不对 | 确认 FutuOpenD 正在运行；检查端口号（默认 11111）；`netstat -an | grep 11111` 确认端口监听 |
| `futu` 导入失败 | 未安装 `futu-api` | 运行 `uv pip install -e ".[futu]"` |
| `unlock_trade failed` | REAL 模式下未设置密码或密码错误 | 确认 `.env` 中 `FUTU_UNLOCK_PWD` 设置为正确的交易密码 |
| 下单返回 None 或失败 | 标的代码格式不对 | 港股不要省略前缀，如 `HK.00700` 而非 `00700` |
| 港股代码自动加了 `HK.` 但显示不支持 | 该标的不在富途可交易范围内 | 检查 FutuOpenD 界面中该标的是否可交易；部分标的只支持行情不支持交易 |
| 行情数据为空 | 日期范围超出富途历史数据限制 | 富途免费账户的历史 K 线数据有限制（通常最近几个月到一年），缩短日期范围重试 |

## 券商切换总结

| 场景 | broker.name | provider.name | 额外安装 |
| --- | --- | --- | --- |
| Alpaca 美股交易 + 回测 | `alpaca` | `alpaca` | 无需（默认） |
| 富途港股交易 + 回测 | `futu` | `futu` | `uv pip install -e ".[futu]"` |
| 混合：Alpaca 数据回测 + 富途下单 | `futu` | `alpaca` | `uv pip install -e ".[futu]"` |
