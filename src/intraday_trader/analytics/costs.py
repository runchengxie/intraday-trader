"""Trading-cost and turnover calculations extracted from ``PerformanceAnalyzer``."""

from __future__ import annotations

import logging
from datetime import timedelta

import numpy as np

logger = logging.getLogger(__name__)


def compute_trading_costs(trades: list) -> dict:
    """Detailed trading-cost analysis.

    Args:
        trades: List of ``TradeRecord``-like objects.

    Returns:
        dict or empty dict if no trades.
    """
    if not trades:
        return {}

    total_commission = sum(trade.commission for trade in trades)
    total_slippage = sum(abs(trade.slippage) * trade.quantity for trade in trades)
    total_market_impact = sum(
        abs(trade.market_impact) * trade.quantity for trade in trades
    )
    total_traded_value = sum(trade.quantity * trade.price for trade in trades)

    commission_rate = (
        total_commission / total_traded_value if total_traded_value > 0 else 0.0
    )
    slippage_rate = (
        total_slippage / total_traded_value if total_traded_value > 0 else 0.0
    )
    market_impact_rate = (
        total_market_impact / total_traded_value if total_traded_value > 0 else 0.0
    )
    total_cost = total_commission + total_slippage + total_market_impact
    total_cost_rate = total_cost / total_traded_value if total_traded_value > 0 else 0.0

    cost_by_symbol: dict[str, dict] = {}
    for symbol in {t.symbol for t in trades}:
        symbol_trades = [t for t in trades if t.symbol == symbol]
        sym_comm = sum(t.commission for t in symbol_trades)
        sym_slippage = sum(abs(t.slippage) * t.quantity for t in symbol_trades)
        sym_impact = sum(abs(t.market_impact) * t.quantity for t in symbol_trades)
        sym_value = sum(t.quantity * t.price for t in symbol_trades)
        cost_by_symbol[symbol] = {
            "commission": sym_comm,
            "slippage": sym_slippage,
            "market_impact": sym_impact,
            "total_cost": sym_comm + sym_slippage + sym_impact,
            "traded_value": sym_value,
            "cost_rate": (
                (sym_comm + sym_slippage + sym_impact) / sym_value
                if sym_value > 0
                else 0.0
            ),
        }

    logger.info(
        "Trading cost analysis: Total cost rate %.4f%%, Commission %.4f%%, "
        "Slippage %.4f%%",
        total_cost_rate * 100,
        commission_rate * 100,
        slippage_rate * 100,
    )

    return {
        "total_commission": total_commission,
        "total_slippage": total_slippage,
        "total_market_impact": total_market_impact,
        "total_cost": total_cost,
        "total_traded_value": total_traded_value,
        "commission_rate": commission_rate,
        "slippage_rate": slippage_rate,
        "market_impact_rate": market_impact_rate,
        "total_cost_rate": total_cost_rate,
        "cost_by_symbol": cost_by_symbol,
        "trade_count": len(trades),
    }


def compute_turnover_rate(
    trades: list,
    portfolio_values: list[tuple],
    initial_capital: float,
    period_days: int = 30,
) -> dict:
    """Portfolio turnover analysis over *period_days*.

    Args:
        trades: List of ``TradeRecord``-like objects.
        portfolio_values: List of ``(timestamp, value)`` tuples.
        initial_capital: Starting portfolio value.
        period_days: Look-back window in calendar days (default 30).

    Returns:
        dict with turnover_rate, annualized_turnover, total_traded_value, …
    """
    if not trades:
        return {"turnover_rate": 0.0, "analysis_period": period_days}

    trade_window_end = max(t.timestamp for t in trades)
    trade_window_start = trade_window_end - timedelta(days=period_days)

    period_trades = [
        t for t in trades if trade_window_start <= t.timestamp <= trade_window_end
    ]

    if not period_trades:
        return {"turnover_rate": 0.0, "analysis_period": period_days}

    total_traded_value = sum(t.quantity * t.price for t in period_trades)

    if portfolio_values:
        pv_end = max(ts for ts, _ in portfolio_values)
        pv_start = pv_end - timedelta(days=period_days)
        period_pv = [v for ts, v in portfolio_values if pv_start <= ts <= pv_end]
    else:
        period_pv = []

    avg_portfolio_value = float(np.mean(period_pv)) if period_pv else initial_capital

    turnover_rate = (
        total_traded_value / avg_portfolio_value if avg_portfolio_value > 0 else 0.0
    )
    annualized_turnover = turnover_rate * (365 / period_days)

    logger.info(
        "Turnover analysis: %.2f%% (%d days), Annualized: %.2f%%",
        turnover_rate * 100,
        period_days,
        annualized_turnover * 100,
    )

    return {
        "turnover_rate": turnover_rate,
        "annualized_turnover": annualized_turnover,
        "total_traded_value": total_traded_value,
        "avg_portfolio_value": avg_portfolio_value,
        "analysis_period": period_days,
        "trade_count": len(period_trades),
    }
