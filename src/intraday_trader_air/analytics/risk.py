"""Pure-function risk-metric calculations extracted from ``PerformanceAnalyzer``.

All functions accept their inputs as explicit arguments so they can be
unit-tested and reused without instantiating the full analyzer.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_risk_metrics(
    returns: pd.Series,
    portfolio_values: list[tuple],
    initial_capital: float,
    trades: list,
    *,
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 252,
) -> dict:
    """Calculate risk-adjusted return metrics from portfolio time-series.

    Args:
        returns: Series of periodic returns (index = timestamp).
        portfolio_values: List of ``(timestamp, value)`` tuples.
        initial_capital: Starting portfolio value.
        trades: List of ``TradeRecord``-like objects with ``timestamp``,
            ``symbol``, ``side``, ``quantity``, ``price``, ``commission``.
        risk_free_rate: Annual risk-free rate (decimal, default 0.02).
        trading_days_per_year: Annualisation factor (default 252).

    Returns:
        dict with keys: total_return, annualized_return, volatility,
        sharpe_ratio, max_drawdown, calmar_ratio, sortino_ratio,
        var_95, cvar_95, win_rate, profit_factor, total_trades,
        analysis_period_days.
    """
    if len(returns) < 2:
        return {}

    # --- basic statistics ---------------------------------------------------
    total_return = (
        (portfolio_values[-1][1] / initial_capital - 1) if portfolio_values else 0.0
    )
    annualized_return = (
        (1 + total_return) ** (trading_days_per_year / len(returns)) - 1
        if len(returns) > 0
        else 0.0
    )
    volatility = returns.std() * np.sqrt(trading_days_per_year)

    # --- Sharpe -------------------------------------------------------------
    excess_returns = returns - risk_free_rate / trading_days_per_year
    sharpe_ratio = (
        excess_returns.mean() / returns.std() * np.sqrt(trading_days_per_year)
        if returns.std() > 0
        else 0.0
    )

    # --- Maximum drawdown ---------------------------------------------------
    portfolio_df = pd.DataFrame(portfolio_values, columns=["timestamp", "value"])
    portfolio_df.set_index("timestamp", inplace=True)
    cumulative_returns = portfolio_df["value"] / initial_capital
    running_max = cumulative_returns.expanding().max()
    drawdown = (cumulative_returns - running_max) / running_max
    max_drawdown = drawdown.min()

    # --- Calmar -------------------------------------------------------------
    calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0.0

    # --- Sortino ------------------------------------------------------------
    downside_returns = returns[returns < 0]
    downside_deviation = (
        downside_returns.std() * np.sqrt(trading_days_per_year)
        if len(downside_returns) > 0
        else 0.0
    )
    sortino_ratio = (
        (annualized_return - risk_free_rate) / downside_deviation
        if downside_deviation > 0
        else 0.0
    )

    # --- VaR / CVaR ---------------------------------------------------------
    var_95 = np.percentile(returns, 5)
    cvar_mask = returns <= var_95
    cvar_95 = float(returns[cvar_mask].mean()) if cvar_mask.any() else 0.0

    # --- Win rate / profit factor -------------------------------------------
    if trades:
        profitable_trades: list[float] = []
        losing_trades: list[float] = []

        positions_tracker: dict[str, dict] = {}
        for trade in trades:
            symbol = trade.symbol
            if symbol not in positions_tracker:
                positions_tracker[symbol] = {"quantity": 0.0, "cost_basis": 0.0}

            if trade.side == "buy":
                old_qty = positions_tracker[symbol]["quantity"]
                old_cost = positions_tracker[symbol]["cost_basis"] * old_qty
                new_cost = trade.quantity * trade.price + trade.commission

                positions_tracker[symbol]["quantity"] += trade.quantity
                if positions_tracker[symbol]["quantity"] > 0:
                    positions_tracker[symbol]["cost_basis"] = (
                        old_cost + new_cost
                    ) / positions_tracker[symbol]["quantity"]

            elif positions_tracker[symbol]["quantity"] > 0:
                cost_basis = positions_tracker[symbol]["cost_basis"]
                pnl = (trade.price - cost_basis) * trade.quantity - trade.commission

                if pnl > 0:
                    profitable_trades.append(pnl)
                else:
                    losing_trades.append(abs(pnl))

                positions_tracker[symbol]["quantity"] -= trade.quantity

        win_rate = (
            len(profitable_trades) / (len(profitable_trades) + len(losing_trades))
            if (len(profitable_trades) + len(losing_trades)) > 0
            else 0.0
        )
        avg_win = np.mean(profitable_trades) if profitable_trades else 0.0
        avg_loss = np.mean(losing_trades) if losing_trades else 0.0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else float("inf")
    else:
        win_rate = 0.0
        profit_factor = 0.0

    analysis_period_days = (
        (max(t.timestamp for t in trades) - min(t.timestamp for t in trades)).days
        if trades
        else 0
    )

    return {
        "total_return": total_return,
        "annualized_return": annualized_return,
        "volatility": volatility,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
        "calmar_ratio": calmar_ratio,
        "sortino_ratio": sortino_ratio,
        "var_95": var_95,
        "cvar_95": cvar_95,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_trades": len(trades),
        "analysis_period_days": analysis_period_days,
    }
