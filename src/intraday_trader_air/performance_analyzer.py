import json
import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from .analytics.costs import compute_trading_costs, compute_turnover_rate
from .analytics.relative import compute_relative_performance
from .analytics.risk import compute_risk_metrics
from .plotting import plot_from_analyzer

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """
    Represents a single trade record
    """

    timestamp: datetime
    symbol: str
    side: str  # 'buy' or 'sell'
    quantity: float
    price: float
    commission: float
    order_id: str
    execution_time: float = 0.0  # Execution time in seconds
    slippage: float = 0.0  # Slippage per share
    estimated_impact_cost: float = 0.0
    market_impact: float = 0.0  # Market impact per share


class PerformanceAnalyzer:
    """
    A professional performance analyzer for algorithmic trading strategies
    This class calculates key metrics like turnover, trading costs, and risk-adjusted returns
    """

    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital
        self.trades: list[TradeRecord] = []
        self.portfolio_values: list[tuple[datetime, float]] = []
        self.positions: dict[str, float] = {}  # symbol -> quantity
        self.cash = initial_capital
        # --- OPTIMIZATION: Store the latest known market prices ---
        self.latest_market_prices: dict[str, float] = {}
        self.benchmark_returns: pd.Series | None = None
        self.benchmark_name: str = "Benchmark"

        logger.info(
            f"Performance analyzer initialized with initial capital: {initial_capital:,.2f}"
        )

    def add_trade(self, trade: TradeRecord):
        """
        Adds a trade record and updates the portfolio state accordingly
        """
        self.trades.append(trade)

        # Update positions
        if trade.symbol not in self.positions:
            self.positions[trade.symbol] = 0.0

        if trade.side == "buy":
            self.positions[trade.symbol] += trade.quantity
            self.cash -= trade.quantity * trade.price + trade.commission
        else:  # sell
            self.positions[trade.symbol] -= trade.quantity
            self.cash += trade.quantity * trade.price - trade.commission

        logger.debug(
            f"Trade added: {trade.symbol} {trade.side} {trade.quantity}@{trade.price}"
        )

    def record_trade(self, db_trade_log):
        """Records a trade from a database log object."""
        trade = TradeRecord(
            timestamp=db_trade_log.timestamp,
            symbol=db_trade_log.symbol,
            side=db_trade_log.side,
            quantity=db_trade_log.quantity,
            price=db_trade_log.price,
            commission=db_trade_log.commission,
            order_id=db_trade_log.order_id,
        )
        self.add_trade(trade)

    def add_snapshot(self, timestamp, equity):
        """Adds a portfolio equity snapshot."""
        self.portfolio_values.append((timestamp, equity))

    def update_portfolio_value(
        self, timestamp: datetime, market_prices: dict[str, float]
    ):
        """
        Updates the portfolio's total value at a specific point in time

        Args:
            timestamp: The current timestamp for the valuation
            market_prices: A dictionary of current market prices, mapping symbols to prices
        """
        portfolio_value = self.cash

        for symbol, quantity in self.positions.items():
            if symbol in market_prices and quantity != 0:
                portfolio_value += quantity * market_prices[symbol]

        self.portfolio_values.append((timestamp, portfolio_value))

        # --- OPTIMIZATION: Update the latest known market prices ---
        self.latest_market_prices = market_prices

        logger.debug(f"Portfolio value updated: {portfolio_value:,.2f}")

    def calculate_returns(self) -> pd.Series:
        """
        Calculates the time series of portfolio returns
        """
        if len(self.portfolio_values) < 2:
            return pd.Series()

        df = pd.DataFrame(self.portfolio_values, columns=["timestamp", "value"])
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)

        returns = df["value"].pct_change().dropna()
        return returns

    def attach_benchmark_series(
        self,
        series: pd.Series,
        name: str = "Benchmark",
        is_price_series: bool = True,
    ):
        """Attach a benchmark series (price or returns) for relative performance."""

        if series is None or len(series) == 0:
            logger.warning("Benchmark series is empty; skipping attachment.")
            return

        benchmark_series = series.dropna().sort_index()
        if benchmark_series.empty:
            logger.warning(
                "Benchmark series contains only NaNs after cleaning; skipping."
            )
            return

        if is_price_series:
            returns = benchmark_series.pct_change().dropna()
        else:
            returns = benchmark_series

        if returns.empty:
            logger.warning(
                "Benchmark series has insufficient data to compute returns; skipping."
            )
            return

        self.benchmark_returns = returns
        self.benchmark_name = name
        logger.info(
            "Benchmark series '%s' attached (%d observations).", name, len(returns)
        )

    def calculate_relative_performance(self) -> dict:
        """Calculate relative performance metrics versus the attached benchmark."""
        if self.benchmark_returns is None or self.benchmark_returns.empty:
            return {}
        portfolio_returns = self.calculate_returns()
        return compute_relative_performance(
            portfolio_returns, self.benchmark_returns, self.benchmark_name
        )

    def calculate_turnover_rate(self, period_days: int = 30) -> dict:
        """Calculates the portfolio turnover rate."""
        return compute_turnover_rate(
            self.trades, self.portfolio_values, self.initial_capital, period_days
        )

    def calculate_trading_costs(self) -> dict:
        """Performs a detailed analysis of trading costs."""
        return compute_trading_costs(self.trades)

    def calculate_risk_metrics(self) -> dict:
        """Calculates risk-adjusted return metrics."""
        returns = self.calculate_returns()
        if len(returns) < 2:
            return {}
        return compute_risk_metrics(
            returns, self.portfolio_values, self.initial_capital, self.trades
        )

    def calculate_concentration_risk(self) -> dict:
        """
        Calculates concentration risk metrics for the current portfolio
        """
        if not self.portfolio_values:
            return {}

        current_portfolio_value = self.portfolio_values[-1][1]

        # Calculate weights for each symbol
        weights = {}
        total_position_value = 0.0

        symbol_prices = self.latest_market_prices

        for symbol, quantity in self.positions.items():
            # Check for non-zero quantity and if the price is available in our latest snapshot
            if quantity != 0 and symbol in symbol_prices:
                position_value = abs(quantity * symbol_prices[symbol])
                # Ensure portfolio value is not zero to avoid division errors
                if current_portfolio_value > 0:
                    weights[symbol] = position_value / current_portfolio_value
                else:
                    weights[symbol] = 0.0
                total_position_value += position_value

        # Calculate concentration metrics
        if weights:
            # Herfindahl-Hirschman Index (HHI)
            herfindahl_index = sum(w**2 for w in weights.values())

            # Maximum weight
            max_weight = max(weights.values()) if weights else 0.0

            # Weight of top 3 positions
            top3_weights = sorted(weights.values(), reverse=True)[:3]
            top3_concentration = sum(top3_weights)

            # Effective number of positions
            effective_positions = 1 / herfindahl_index if herfindahl_index > 0 else 0
        else:
            herfindahl_index = 0.0
            max_weight = 0.0
            top3_concentration = 0.0
            effective_positions = 0

        cash_weight = (
            self.cash / current_portfolio_value if current_portfolio_value > 0 else 0.0
        )

        result = {
            "position_weights": weights,
            "herfindahl_index": herfindahl_index,
            "max_weight": max_weight,
            "top3_concentration": top3_concentration,
            "effective_positions": effective_positions,
            "cash_weight": cash_weight,
            "total_positions": len(
                [w for w in weights.values() if w > 0.001]
            ),  # Positions with weight > 0.1%
        }

        logger.info(
            f"Concentration risk: Max weight {max_weight:.2%}, Top 3 concentration {top3_concentration:.2%}, Effective # of positions {effective_positions:.1f}"
        )
        return result

    def generate_performance_report(self) -> str:
        """
        Generates a comprehensive performance report
        """
        logger.info("Generating comprehensive performance report...")

        report = {
            "report_timestamp": datetime.now(),
            "initial_capital": self.initial_capital,
            "current_value": (
                self.portfolio_values[-1][1]
                if self.portfolio_values
                else self.initial_capital
            ),
            "cash_position": self.cash,
            "active_positions": {
                k: v for k, v in self.positions.items() if abs(v) > 1e-6
            },
            "returns_analysis": self.calculate_risk_metrics(),
            "trading_costs": self.calculate_trading_costs(),
            "turnover_analysis": self.calculate_turnover_rate(),
            "concentration_risk": self.calculate_concentration_risk(),
        }

        benchmark_report = self.calculate_relative_performance()
        if benchmark_report:
            report["benchmark_analysis"] = benchmark_report

        # Add summary metrics for quick overview
        if report["returns_analysis"]:
            report["summary"] = {
                "total_return": report["returns_analysis"].get("total_return", 0.0),
                "sharpe_ratio": report["returns_analysis"].get("sharpe_ratio", 0.0),
                "max_drawdown": report["returns_analysis"].get("max_drawdown", 0.0),
                "win_rate": report["returns_analysis"].get("win_rate", 0.0),
                "total_cost_rate": report["trading_costs"].get("total_cost_rate", 0.0),
                "turnover_rate": report["turnover_analysis"].get(
                    "annualized_turnover", 0.0
                ),
                "max_concentration": report["concentration_risk"].get(
                    "max_weight", 0.0
                ),
            }
            if benchmark_report:
                report["summary"].update(
                    {
                        "benchmark_total_return": benchmark_report.get(
                            "benchmark_total_return", 0.0
                        ),
                        "alpha": benchmark_report.get("alpha"),
                        "information_ratio": benchmark_report.get("information_ratio"),
                    }
                )

        logger.info("Performance report generation complete.")

        # Convert to JSON string
        def default_converter(o):
            if isinstance(o, (datetime, pd.Timestamp)):
                return o.isoformat()
            if isinstance(o, (np.integer, np.floating)):
                return o.item()
            if isinstance(o, pd.Series):
                return o.to_dict()
            raise TypeError(
                f"Object of type {o.__class__.__name__} is not JSON serializable"
            )

        return json.dumps(report, indent=4, default=default_converter)

    def plot_performance_charts(self, save_path: str | None = None):
        """Plot strategy and benchmark performance summary charts."""

        if not self.portfolio_values:
            logger.warning("No portfolio value data available for plotting")
            return

        plot_from_analyzer(
            self,
            out_path=save_path,
            title="Algorithmic Trading Performance",
            show=save_path is None,
        )
