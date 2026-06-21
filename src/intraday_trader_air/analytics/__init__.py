"""Analytics package — standalone metric calculations."""

from intraday_trader_air.analytics.costs import (
    compute_trading_costs,
    compute_turnover_rate,
)
from intraday_trader_air.analytics.relative import compute_relative_performance
from intraday_trader_air.analytics.risk import compute_risk_metrics

__all__ = [
    "compute_relative_performance",
    "compute_risk_metrics",
    "compute_trading_costs",
    "compute_turnover_rate",
]
