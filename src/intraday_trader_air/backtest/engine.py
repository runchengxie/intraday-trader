"""Core backtesting routines shared by CLI and scripts."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from statistics import fmean
from typing import Any

import backtrader as bt
import numpy as np

from intraday_trader_air.backtest_utils import analyze_optimization_results

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BacktestRequest:
    """Container describing the work to be executed by ``run_backtest``."""

    strategy_cls: type
    data_feed: bt.feeds.PandasData
    initial_cash: float
    commission: float
    slippage_perc: float = 0.0
    risk_config: Mapping[str, Any] | None = None
    single_run_params: Mapping[str, Any] | None = None
    optimize: bool = False
    opt_param_names: list[str] | None = None
    opt_param_values: Mapping[str, Any] | None = None
    strategy_name: str = "Strategy"
    maxcpus: int = 1
    enable_enhanced_features: bool = True


def run_backtest(request: BacktestRequest) -> tuple[bt.Cerebro, dict[str, Any]] | Any:
    """Execute a Backtrader backtest according to ``request``."""

    single_run_params = dict(request.single_run_params or {})
    opt_param_values = dict(request.opt_param_values or {})

    cerebro = bt.Cerebro()
    cerebro.adddata(request.data_feed)
    cerebro.broker.setcash(request.initial_cash)
    cerebro.broker.setcommission(commission=request.commission)
    if request.slippage_perc > 0.0:
        cerebro.broker.set_slippage_perc(perc=request.slippage_perc)

    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="tradeanalyzer")
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days
    )
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(
        bt.analyzers.TimeReturn, _name="timereturn", timeframe=bt.TimeFrame.Days
    )
    cerebro.addanalyzer(bt.analyzers.Transactions, _name="transactions")

    if request.optimize:
        if not opt_param_values:
            raise ValueError("opt_param_values must be provided for optimization")

        logger.info("Starting %s parameter optimization", request.strategy_name)
        cerebro.optstrategy(request.strategy_cls, **opt_param_values)
        results = cerebro.run(maxcpus=request.maxcpus)
        logger.info("Completed %s parameter optimization", request.strategy_name)

        if request.opt_param_names is None:
            logger.warning(
                "opt_param_names not provided for %s, skipping optimisation analysis",
                request.strategy_name,
            )
            return results

        opt_df = analyze_optimization_results(
            results, request.opt_param_names, request.initial_cash
        )
        if opt_df is None or opt_df.empty:
            logger.warning(
                "%s optimisation analysis returned no rows", request.strategy_name
            )
        return opt_df

    logger.info("Starting %s single run backtest", request.strategy_name)
    cerebro.addstrategy(request.strategy_cls, **single_run_params)
    results = cerebro.run()
    strat = results[0]

    trade_analysis = strat.analyzers.tradeanalyzer.get_analysis()
    sharpe_ratio = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    timereturns = strat.analyzers.timereturn.get_analysis()
    transactions = strat.analyzers.transactions.get_analysis()

    return_values = np.array(list(timereturns.values()), dtype=float)
    var_95 = (
        float(np.percentile(return_values, 5)) if return_values.size else float("nan")
    )
    if return_values.size:
        cvar_mask = return_values <= var_95
        cvar_95 = (
            float(return_values[cvar_mask].mean()) if cvar_mask.any() else float("nan")
        )
    else:
        cvar_95 = float("nan")

    total_traded_value = 0.0
    for trade_list in transactions.values():
        for trade in trade_list:
            size = trade[0]
            price = trade[1]
            total_traded_value += abs(size * price)

    avg_portfolio_value = fmean([request.initial_cash, cerebro.broker.getvalue()])
    turnover_ratio = (
        total_traded_value / avg_portfolio_value
        if avg_portfolio_value > 0
        else float("nan")
    )

    analysis_results = {
        "Final Value": cerebro.broker.getvalue(),
        "Total Trades": trade_analysis.get("total", {}).get("total", 0),
        "Win Rate (%)": (
            (
                trade_analysis.get("won", {}).get("total", 0)
                / trade_analysis.get("total", {}).get("total", 1)
                * 100
            )
            if trade_analysis.get("total", {}).get("total", 0) > 0
            else "N/A"
        ),
        "Total Net PnL": trade_analysis.get("pnl", {})
        .get("net", {})
        .get("total", "N/A"),
        "Sharpe Ratio": sharpe_ratio.get("sharperatio", "N/A"),
        "Max Drawdown (%)": drawdown.get("max", {}).get("drawdown", "N/A"),
        "Annualized Return (%)": returns.get("rnorm100", "N/A"),
        "Value at Risk (95%) (%)": var_95 * 100 if np.isfinite(var_95) else "N/A",
        "Conditional VaR (95%) (%)": cvar_95 * 100 if np.isfinite(cvar_95) else "N/A",
        "Turnover (%)": turnover_ratio * 100 if np.isfinite(turnover_ratio) else "N/A",
    }
    return cerebro, analysis_results
