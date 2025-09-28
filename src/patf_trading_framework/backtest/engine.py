"""Core backtesting routines shared by CLI and scripts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

import backtrader as bt

from patf_trading_framework.backtest_utils import analyze_optimization_results
from patf_trading_framework.exception_handler import ExceptionHandler
from patf_trading_framework.performance_analyzer import PerformanceAnalyzer
from patf_trading_framework.risk_manager import RiskManager

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

    risk_manager = None
    performance_analyzer = None
    exception_handler = None

    if request.enable_enhanced_features:
        try:
            risk_manager = RiskManager(request.risk_config or {})
            performance_analyzer = PerformanceAnalyzer(
                initial_capital=request.initial_cash
            )
            exception_handler = ExceptionHandler()
            logger.info("Enhanced feature components initialized successfully")
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.warning(
                "Enhanced feature initialization failed, using basic mode: %s", exc
            )
            request.enable_enhanced_features = False

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
    }
    return cerebro, analysis_results
