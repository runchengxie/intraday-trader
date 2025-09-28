# Algorithmic Trading for Reversion and Trend-Following

> **课堂参考**：此指南保留课堂作业中的补充说明，当前仓库采纳部分思路，但具体执行细节以最新代码与文档为准。

## Introduction

Part I. Implement at least (a) one mean-reversion strategy with a specific indicator of your choice AND (b) one trend-following strategy with several indicators of your choice. Rule-based strategy code to produce P&L plot.

Event-driven backtesting / life-like testing in Parts II and III. Code must have routines on order handling, including re-verification of server responses (eg, order cancelled, partially filled, returned with an incorrect info).

## Simple but Effective Trend Following in FX

* **Step 1:** resample the prices at regular intervals (eg, 30 seconds); can use `pandas` resample method.

* **Step 2:** calculate an average price over the longer period (eg, past five-minute intervals). Implement trading logic to open a position when market prices deviate from that average, and close the position when prices revert back to it.

* **Step 3:** compute the ratio of the short-term average to the long-term average price. No trend is signaled by the ratio of 1, short-term prices ≈ the long-term prices. Uptrend signaled by the ratio above 1, and downtrend by less than 1.

## Trend-Following Indicators

Common indicators: Moving Averages, Exponential Moving Averages (EMA), Average Directional Index (ADX).

EMAt = αPt + (1 − α)EMAt-1

choice of α is practical, discussed in TUT Market Prediction.

MACD = EMAshort − EMAlong

```python
data['EMA_12'] = data['Close'].ewm(span=12, adjust=False).mean()
data['EMA_26'] = data['Close'].ewm(span=26, adjust=False).mean()
data['MACD'] = data['EMA_12'] - data['EMA_26']
```

## Broker API - REST

1. Alpaca, IB Web, and Oanda. Alpaca REST API is free and includes asynchronous events handling based on WebSocket and Server Side Events (SSE).

2. Utilizes HTTP methods, eg GET (retrieve data), POST (create new data), PUT (update data). Useable for non-time-critical operations such as retrieving historical data, account information, placing orders, and getting order status.

## Broker API - FIX

1. The more industrial strength and lower latency API choice is FIX (Financial Information eXchange). A messaging protocol designed for the real-time exchange.

2. Supports submission and cancellation of various order types, trade execution reports, and market data dissemination – all for high frequency trading. FIX is used by large institutions, funds, and broker/dealers.

## Risk Management

* **Data Work and Features.** Retrieving historical data, tick data, candles data.

* **Systematic Backtesting** (eg, concentration in asset, Beta-to-SPY) are of no utility for this type of algo trading project, however for overall performance evaluation it's useful to provide a tearsheet with information about turnover.

    1. Compute Drawdowns, Sharpe Ratio and Value-at-Risk as adapted (it is over the period, which can include unequal number of transactions).

    2. Consider computation of Kelly Criterion for bet size.

READING *Python for Finance Mastering Data-Driven Finance* by Yves Hilpisch.

## Algorithmic Flow

* Optionally, introduce liquidity and algorithmic flow considerations (a model of order flow). How would you be entering and accumulating the position? What impact *your transactions* will make on the market order book?

* Related issue is the possible leverage for the strategy. While the maximum leverage is 1/Margin, the more adequate solution is a maximally leveraged market-neutral gain or alpha-to-margin ratio.

    AM = α / Margin

## Developing a Trading Business

There are libraries for anything: data processing, times series and techniques from ML, and tear sheets/trading analytics.

## EXTRA. Trading Strategy Evaluation - relevant to topics TS, ML, and AL

* Systematic Backtesting: alpha and rolling beta. Drawdown Control

* Ratios and Scorecards

* (Algorithmic Trading Efficiency)

`https://github.com/stefan-jansen/pyfolio-reloaded`

## Systematic Backtesting

1. We will look at **how to relate P&L** to the market and factors, to understand what drives P&L, what you make money on.

2. Then, we will talk about **evaluating P&L** with drawdown control and VaR.

3. You can look for suitable models for algorithmic **order flow** and liquidity impact. [Optional]

## Alpha and Beta

**Beta** is the strategy's market exposure, for which you should not pay much as it is easy to gain by buying an ETF or index futures contract.

**Alpha** is the excess return after subtracting return due to market movements.

RSt = α + βRMt + εt

E[RSt − βRMt] = α

**RMt = Rt − rƒ** is the time series of returns representing **the market factor**.

## Risk-Reward Ratios

**Information Ratio (IR)** focuses on risk-adjusted *abnormal* return, the risk-adjusted alpha!

α / σ(ε)

(That doesn't tell us how much dollar alpha is there. It can be eaten by transaction costs.)

**Sharpe Ratio** measures return per unit of risk. Familiar form:

E(Rt − rƒ) / σ(Rt − rƒ)

## Factors

Evaluating performance **against factors** is the central part of the backtesting.

We saw the separation of alpha and beta in regression *wrt* one market factor

RSt = α + βRMt + εt

We see that a `factor` is a time series of changes, similar to the series of asset returns.

## Named Factors

* **Up Minus Down (UMD)** or **momentum** factor would leverage on stocks that are going up. The recent month's returns are excluded from calculation to avoid a spurious signal.

* **Small Minus Big (SMB)** factor shorts large cap stocks, so βSMB measures the tilt towards small stocks.

* Long-short **High Minus Low (HML)** or **value** factor: buy top 30% of companies with the high book-to-market value and sell the bottom 30% (expensive stocks).

1) Except for HML, the impact/presence of other factors questionable.

2) Since 2015, Fama-French moved to 5-factor model that include profitability RMW and investment CMA but ignore the proper 3) Momentum factor and 4) Low Volatility (Betting Against Beta) factors.

## Factors Backtesting

So how do we check against those factors?

Set up a regression!

RSt = α + βM RMt + βHML RHMLt + εt

where RHMLt is return series from the long-short HML factor.

* We can **add factors** to this regression.

* We can have **rolling estimates** of these betas for each day/week.

## Factors Backtesting (Advanced)

* Scale returns to have the same volatility as the benchmark – put on the same plot for correct comparison.

* Rolling Sharpe Ratio – changes **not** desirable).

* Rolling market factor beta – β > 1 **not** desirable.

* Rolling betas *wrt* to UMD (momentum), SMB, and industry sectors.

## Drawdowns

The drawdown is the cumulative percentage loss, given the loss in the initial timestep.

Let's define the highest past peak performance as High Water Mark

DDt = (HWMt - Pt) / HWMt

where Pt is the cumulative return (or portfolio value Πt).

It makes sense to evaluate a maximum drawdown over past period maxt≤T DDt.

## Drawdown Control

The strategy must be able to survive without running into a close-out.

It makes sense to pre-define Maximum Acceptable Drawdown (MADD) and trace

VaRt ≤ MADD – DDt

where VaRt is today's VaR and DDt is current drawdown.

## Backtesting for Risk and Liquidity

1. Does cumulative P&L behave as expected (eg, for a coint pair trade)? Behavior of risk measures (volatility/VaR/Drawdown)?

2. Is P&L coming from a few large trades or many smaller trades? Does all profit come from a particular period. Concentration in assets and its attribution - as intended?

3. Turnover - good or bad for your stat arb/algo strat/allocation? Impact of transaction costs (slippage). Plot P&L value (or alpha) vs. Ntransactions.

## Python Ecosystem

### The Quant Finance PyData Stack

Source: [Jake VanderPlas: State of the Tools](https://www.youtube.com/watch?v=5GINDD7qbP4)

Github examples below might be no longer updated. Given to showcase the useful elements of systematic backtesting: **a.** rolling beta *wrt* S&P500 plot, **b.** rolling Sharpe Ratio, and **c.** various ratios in scorecards.

1. `github.com/quantopian/ALPHALENS`
    `github.com/quantopian/alphalens/blob/master/alphalens/examples/alphalens_tutorial_on_quantopian.ipynb`

2. `github.com/quantopian/PYFOLIO`
    `quantopian.github.io/pyfolio/notebooks/single_stock_example/`
