import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

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
            logger.warning("Benchmark series contains only NaNs after cleaning; skipping.")
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
        logger.info("Benchmark series '%s' attached (%d observations).", name, len(returns))

    def calculate_relative_performance(self) -> dict:
        """Calculate relative performance metrics versus the attached benchmark."""

        if self.benchmark_returns is None or self.benchmark_returns.empty:
            return {}

        portfolio_returns = self.calculate_returns()
        combined = pd.concat(
            [portfolio_returns.rename("portfolio"), self.benchmark_returns.rename("benchmark")],
            axis=1,
            join="inner",
        ).dropna()

        if combined.empty:
            return {}

        port = combined["portfolio"]
        bench = combined["benchmark"]

        bench_var = np.var(bench)
        beta = np.cov(port, bench)[0, 1] / bench_var if bench_var > 0 else None
        alpha = port.mean() - (beta * bench.mean() if beta is not None else 0.0)
        active_returns = port - bench
        tracking_error = active_returns.std(ddof=1)
        information_ratio = (
            active_returns.mean() / tracking_error if tracking_error > 0 else None
        )

        cumulative_port = (1 + port).cumprod()
        cumulative_bench = (1 + bench).cumprod()

        result = {
            "benchmark_name": self.benchmark_name,
            "benchmark_total_return": cumulative_bench.iloc[-1] - 1,
            "strategy_total_return": cumulative_port.iloc[-1] - 1,
            "active_return": (cumulative_port.iloc[-1] - cumulative_bench.iloc[-1]),
            "alpha": alpha,
            "beta": beta,
            "tracking_error": tracking_error,
            "information_ratio": information_ratio,
        }

        logger.info(
            "Relative performance vs %s: alpha %.4f, beta %.4f, IR %s",
            self.benchmark_name,
            alpha if alpha is not None else float("nan"),
            beta if beta is not None else float("nan"),
            f"{information_ratio:.4f}" if information_ratio is not None else "nan",
        )

        return result

    def calculate_turnover_rate(self, period_days: int = 30) -> dict:
        """
        Calculates the portfolio turnover rate.

        Args:
            period_days: The calculation period in days.

        Returns:
            A dictionary containing the turnover analysis.
        """
        if not self.trades:
            return {"turnover_rate": 0.0, "analysis_period": period_days}

        # Get trades within the specified period
        end_date = max(trade.timestamp for trade in self.trades)
        start_date = end_date - timedelta(days=period_days)

        period_trades = [
            t for t in self.trades if start_date <= t.timestamp <= end_date
        ]

        if not period_trades:
            return {"turnover_rate": 0.0, "analysis_period": period_days}

        # Calculate the total value of trades
        total_traded_value = sum(
            trade.quantity * trade.price for trade in period_trades
        )

        # Calculate the average portfolio value
        period_portfolio_values = [
            value
            for timestamp, value in self.portfolio_values
            if start_date <= timestamp <= end_date
        ]

        if not period_portfolio_values:
            avg_portfolio_value = self.initial_capital
        else:
            avg_portfolio_value = np.mean(period_portfolio_values)

        # Turnover Rate = Total Traded Value / Average Portfolio Value
        turnover_rate = (
            total_traded_value / avg_portfolio_value if avg_portfolio_value > 0 else 0.0
        )

        # Annualize the turnover rate
        annualized_turnover = turnover_rate * (365 / period_days)

        result = {
            "turnover_rate": turnover_rate,
            "annualized_turnover": annualized_turnover,
            "total_traded_value": total_traded_value,
            "avg_portfolio_value": avg_portfolio_value,
            "analysis_period": period_days,
            "trade_count": len(period_trades),
        }

        logger.info(
            f"Turnover analysis: {turnover_rate:.2%} ({period_days}days), Annualized: {annualized_turnover:.2%}"
        )
        return result

    def calculate_trading_costs(self) -> dict:
        """
        Performs a detailed analysis of trading costs
        """
        if not self.trades:
            return {}

        # Commission costs
        total_commission = sum(trade.commission for trade in self.trades)

        # Slippage costs
        total_slippage = sum(
            abs(trade.slippage) * trade.quantity for trade in self.trades
        )

        # Market impact costs
        total_market_impact = sum(
            abs(trade.market_impact) * trade.quantity for trade in self.trades
        )

        # Total traded value
        total_traded_value = sum(trade.quantity * trade.price for trade in self.trades)

        # Cost ratios
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
        total_cost_rate = (
            total_cost / total_traded_value if total_traded_value > 0 else 0.0
        )

        # Analysis by symbol
        cost_by_symbol = {}
        for symbol in set(trade.symbol for trade in self.trades):
            symbol_trades = [t for t in self.trades if t.symbol == symbol]
            symbol_commission = sum(t.commission for t in symbol_trades)
            symbol_slippage = sum(abs(t.slippage) * t.quantity for t in symbol_trades)
            symbol_market_impact = sum(
                abs(t.market_impact) * t.quantity for t in symbol_trades
            )
            symbol_value = sum(t.quantity * t.price for t in symbol_trades)

            cost_by_symbol[symbol] = {
                "commission": symbol_commission,
                "slippage": symbol_slippage,
                "market_impact": symbol_market_impact,
                "total_cost": symbol_commission
                + symbol_slippage
                + symbol_market_impact,
                "traded_value": symbol_value,
                "cost_rate": (
                    (symbol_commission + symbol_slippage + symbol_market_impact)
                    / symbol_value
                    if symbol_value > 0
                    else 0.0
                ),
            }

        result = {
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
            "trade_count": len(self.trades),
        }

        logger.info(
            f"Trading cost analysis: Total cost rate {total_cost_rate:.4%}, Commission {commission_rate:.4%}, Slippage {slippage_rate:.4%}"
        )
        return result

    def calculate_risk_metrics(self) -> dict:
        """
        Calculates risk-adjusted return metrics
        """
        returns = self.calculate_returns()

        if len(returns) < 2:
            return {}

        # Basic statistics
        total_return = (
            (self.portfolio_values[-1][1] / self.initial_capital - 1)
            if self.portfolio_values
            else 0.0
        )
        annualized_return = (
            (1 + total_return) ** (252 / len(returns)) - 1 if len(returns) > 0 else 0.0
        )
        volatility = returns.std() * np.sqrt(252)

        # Sharpe Ratio
        risk_free_rate = 0.02  # Assume a 2% annual risk-free rate
        excess_returns = returns - risk_free_rate / 252
        sharpe_ratio = (
            excess_returns.mean() / returns.std() * np.sqrt(252)
            if returns.std() > 0
            else 0.0
        )

        # Maximum Drawdown
        portfolio_df = pd.DataFrame(
            self.portfolio_values, columns=["timestamp", "value"]
        )
        portfolio_df.set_index("timestamp", inplace=True)
        cumulative_returns = portfolio_df["value"] / self.initial_capital
        running_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - running_max) / running_max
        max_drawdown = drawdown.min()

        # Calmar Ratio
        calmar_ratio = (
            annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0.0
        )

        # Sortino Ratio
        downside_returns = returns[returns < 0]
        downside_deviation = (
            downside_returns.std() * np.sqrt(252) if len(downside_returns) > 0 else 0.0
        )
        sortino_ratio = (
            (annualized_return - risk_free_rate) / downside_deviation
            if downside_deviation > 0
            else 0.0
        )

        # VaR和CVaR
        var_95 = np.percentile(returns, 5)
        cvar_95 = (
            returns[returns <= var_95].mean()
            if len(returns[returns <= var_95]) > 0
            else 0.0
        )

        # Win rate and profit factor
        if self.trades:
            profitable_trades = []
            losing_trades = []

            # Calculate PnL for closing trades using an average cost basis
            # Note: This method is primarily suited for long-only strategies
            positions_tracker = {}
            for trade in self.trades:
                symbol = trade.symbol
                if symbol not in positions_tracker:
                    positions_tracker[symbol] = {"quantity": 0.0, "cost_basis": 0.0}

                if trade.side == "buy":
                    old_quantity = positions_tracker[symbol]["quantity"]
                    old_cost = positions_tracker[symbol]["cost_basis"] * old_quantity
                    new_cost = trade.quantity * trade.price + trade.commission

                    positions_tracker[symbol]["quantity"] += trade.quantity
                    if positions_tracker[symbol]["quantity"] > 0:
                        positions_tracker[symbol]["cost_basis"] = (
                            old_cost + new_cost
                        ) / positions_tracker[symbol]["quantity"]

                elif positions_tracker[symbol]["quantity"] > 0:
                    cost_basis = positions_tracker[symbol]["cost_basis"]
                    pnl = (
                        trade.price - cost_basis
                    ) * trade.quantity - trade.commission

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

        result = {
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
            "total_trades": len(self.trades),
            "analysis_period_days": (
                (
                    max(trade.timestamp for trade in self.trades)
                    - min(trade.timestamp for trade in self.trades)
                ).days
                if self.trades
                else 0
            ),
        }

        logger.info(
            f"Risk metrics: Sharpe Ratio {sharpe_ratio:.2f}, Max Drawdown {max_drawdown:.2%}, Win Rate {win_rate:.2%}"
        )
        return result

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
                        "information_ratio": benchmark_report.get(
                            "information_ratio"
                        ),
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

    def plot_performance_charts(self, save_path: str = None):
        """
        Plot performance charts

        Args:
            save_path: Save path, if None then display charts
        """
        if not self.portfolio_values:
            logger.warning("No portfolio value data available for plotting")
            return

        # Create subplots
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle("Algorithmic Trading Performance Analysis", fontsize=16)

        # 1. Portfolio Value Over Time
        portfolio_df = pd.DataFrame(
            self.portfolio_values, columns=["timestamp", "value"]
        )
        portfolio_df.set_index("timestamp", inplace=True)

        axes[0, 0].plot(portfolio_df.index, portfolio_df["value"], label="Strategy")
        if self.benchmark_returns is not None and not self.benchmark_returns.empty:
            benchmark_curve = (1 + self.benchmark_returns).cumprod()
            benchmark_curve = benchmark_curve.reindex(
                portfolio_df.index, method="ffill"
            )
            if benchmark_curve.dropna().empty:
                logger.warning(
                    "Benchmark curve could not be aligned for plotting; skipping overlay."
                )
            else:
                scaled_benchmark = (
                    benchmark_curve
                    * (self.initial_capital / benchmark_curve.dropna().iloc[0])
                )
                axes[0, 0].plot(
                    scaled_benchmark.index,
                    scaled_benchmark,
                    label=self.benchmark_name,
                    linestyle="--",
                )
        axes[0, 0].axhline(
            y=self.initial_capital,
            color="r",
            linestyle="--",
            alpha=0.7,
            label="Initial Capital",
        )
        axes[0, 0].set_title("Portfolio Value Over Time")
        axes[0, 0].set_ylabel("Value")
        axes[0, 0].legend()
        axes[0, 0].grid(True, alpha=0.3)

        # 2. Drawdown Curve
        cumulative_returns = portfolio_df["value"] / self.initial_capital
        running_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - running_max) / running_max

        axes[0, 1].fill_between(drawdown.index, drawdown, 0, alpha=0.3, color="red")
        axes[0, 1].plot(drawdown.index, drawdown, color="red")
        axes[0, 1].set_title("Drawdown Curve")
        axes[0, 1].set_ylabel("Drawdown Ratio")
        axes[0, 1].grid(True, alpha=0.3)

        # 3. Returns Distribution
        returns = self.calculate_returns()
        if len(returns) > 0:
            axes[1, 0].hist(returns, bins=50, alpha=0.7, edgecolor="black")
            axes[1, 0].axvline(
                returns.mean(),
                color="red",
                linestyle="--",
                label=f"Mean: {returns.mean():.4f}",
            )
            axes[1, 0].set_title("Returns Distribution")
            axes[1, 0].set_xlabel("Daily Returns")
            axes[1, 0].set_ylabel("Frequency")
            axes[1, 0].legend()
            axes[1, 0].grid(True, alpha=0.3)

        # 4. Rolling Sharpe Ratio
        if len(returns) >= 30:
            rolling_sharpe = (
                returns.rolling(window=30).mean()
                / returns.rolling(window=30).std()
                * np.sqrt(252)
            )
            axes[1, 1].plot(rolling_sharpe.index, rolling_sharpe)
            axes[1, 1].axhline(y=0, color="black", linestyle="-", alpha=0.3)
            axes[1, 1].axhline(
                y=1, color="green", linestyle="--", alpha=0.7, label="Sharpe Ratio = 1"
            )
            axes[1, 1].set_title("Rolling Sharpe Ratio (30 Days)")
            axes[1, 1].set_ylabel("Sharpe Ratio")
            axes[1, 1].legend()
            axes[1, 1].grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches="tight")
            logger.info(f"Performance chart saved to: {save_path}")
        else:
            plt.show()

        plt.close()
