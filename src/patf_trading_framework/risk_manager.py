import logging
from collections import deque
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)


class RiskManager:
    """
    A comprehensive risk management module that includes Value at Risk (VaR)
    calculation, liquidity checks, and market data validation.
    """

    def __init__(self, risk_config: dict):
        self.config = risk_config

        # VaR parameters
        self.var_window = self.config.get('var_window', 252)
        self.var_confidence = self.config.get('var_confidence_level', 0.05)

        # Data history deques
        self.price_history = deque(maxlen=self.var_window)
        self.volume_history = deque(maxlen=self.var_window)
        self.returns_history = deque(maxlen=self.var_window)

        # Anomaly detection thresholds from config
        self.price_jump_threshold = self.config.get('price_jump_threshold', 0.05)
        self.volume_spike_threshold = self.config.get('volume_spike_threshold', 3.0)
        self.min_liquidity_volume = self.config.get('min_liquidity_volume', 1000)

        logger.info(
            f"RiskManager initialized with config: VaR window={self.var_window}, "
            f"confidence level={1-self.var_confidence:.1%}, "
            f"Max Participation={self.config.get('max_order_participation_ratio', 'N/A')}, "
            f"Max Gross Exposure={self.config.get('max_gross_exposure', 'N/A')}"
        )

    def update_market_data(
        self, price: float, volume: float, timestamp: datetime = None
    ):
        """
        Updates market data and performs real-time risk checks.

        Args:
            price: The current price.
            volume: The current trading volume.
            timestamp: The timestamp of the data point.

        Returns:
            A dictionary containing the results of the risk checks.
        """
        if timestamp is None:
            timestamp = datetime.now()

        # Calculate returns
        if len(self.price_history) > 0:
            return_rate = (price - self.price_history[-1]) / self.price_history[-1]
            self.returns_history.append(return_rate)

        # Update historical data
        self.price_history.append(price)
        self.volume_history.append(volume)

        # Perform risk checks
        risk_alerts = self._perform_risk_checks(price, volume, timestamp)

        return risk_alerts

    def _perform_risk_checks(
        self, price: float, volume: float, timestamp: datetime
    ) -> dict:
        """
        Performs a series of comprehensive risk checks.
        """
        alerts = {
            "timestamp": timestamp,
            "price_jump_alert": False,
            "volume_spike_alert": False,
            "liquidity_alert": False,
            "data_quality_alert": False,
            "messages": [],
        }

        # 1. Price jump detection
        if len(self.returns_history) > 0:
            latest_return = abs(self.returns_history[-1])
            if latest_return > self.price_jump_threshold:
                alerts["price_jump_alert"] = True
                alerts["messages"].append(
                    f"Significant price jump: {latest_return:.2%}"
                )
                logger.warning(f"Significant price jump detected: {latest_return:.2%}")

        # 2. Volume spike detection
        if len(self.volume_history) >= 10:
            # Exclude the current value for a more stable average
            avg_volume = np.mean(list(self.volume_history)[:-1])
            if volume > avg_volume * self.volume_spike_threshold:
                alerts["volume_spike_alert"] = True
                alerts["messages"].append(
                    f"Unusual volume spike: {volume/avg_volume:.1f}x the average"
                )
                logger.warning(
                    f"Volume spike detected: {volume/avg_volume:.1f}x the average volume"
                )

        # 3. Liquidity check
        if volume < self.min_liquidity_volume:
            alerts["liquidity_alert"] = True
            alerts["messages"].append(
                f"Insufficient liquidity: Volume {volume} is below the minimum "
                f"requirement of {self.min_liquidity_volume}"
            )
            logger.warning(f"Low liquidity warning: Volume is only{volume}")

        # 4. Data quality check
        if price <= 0 or volume < 0:
            alerts["data_quality_alert"] = True
            alerts["messages"].append(
                f"Data quality issue: Invalid price {price} or volume {volume}"
            )
            logger.error(
                f"Data quality issue: Invalid price {price} or volume {volume}"
            )

        return alerts

    def calculate_var(self, portfolio_value: float, method: str = "historical") -> dict:
        """
        Calculates the Value at Risk (VaR).

        Args:
            portfolio_value: The total value of the portfolio.
            method: The calculation method to use ('historical' or 'parametric').

        Returns:
            A dictionary containing the VaR calculation results.
        """
        if len(self.returns_history) < 30:
            logger.warning("Insufficient historical data to calculate reliable VaR.")
            return {
                "var": None,
                "method": method,
                "confidence": 1 - self.var_confidence,
            }

        returns_array = np.array(self.returns_history)

        if method == "historical":
            var_return = np.percentile(returns_array, self.var_confidence * 100)
            var_amount = abs(var_return * portfolio_value)

        elif method == "parametric":
            mean_return = np.mean(returns_array)
            std_return = np.std(returns_array)
            # Assume returns are normally distributed
            from scipy.stats import norm

            var_return = norm.ppf(self.var_confidence, mean_return, std_return)
            var_amount = abs(var_return * portfolio_value)

        else:
            raise ValueError(f"Unsupported VaR calculation method: {method}")

        # Calculate rolling VaR
        rolling_var = self._calculate_rolling_var(portfolio_value, method)

        result = {
            "var": var_amount,
            "var_percentage": abs(var_return),
            "method": method,
            "confidence": 1 - self.var_confidence,
            "portfolio_value": portfolio_value,
            "rolling_var": rolling_var,
            "data_points": len(returns_array),
        }

        logger.info(f"VaR calculated: {var_amount:.2f} ({abs(var_return):.2%})")
        return result

    # --- Liquidity and Impact Check ---
    def check_liquidity_and_impact(
        self,
        order_size: float,
        recent_avg_volume: float | None,
        current_volatility: float | None,
        bid_ask_spread_pct: float | None = None,
    ) -> tuple[bool, dict]:
        """
        Pre-trade check for liquidity constraints and estimated market impact.

        Args:
            order_size (float): The quantity of the proposed order.
            recent_avg_volume (float): The recent average trading volume for the asset.
            current_volatility (float): The recent price volatility (std dev of returns).
            bid_ask_spread_pct (Optional[float]): The current bid-ask spread as a percentage.

        Returns:
            Tuple[bool, Dict]: A tuple containing a boolean (True if passed) and a details dictionary.
        """
        details = {
            "warnings": [],
            "participation_ratio": 0.0,
            "estimated_impact_pct": 0.0,
            "total_estimated_impact_cost": 0.0,
        }
        passed = True

        max_participation_ratio = self.config.get("max_order_participation_ratio", 0.02)
        if recent_avg_volume and recent_avg_volume > 0:
            participation_ratio = abs(order_size) / max(recent_avg_volume, 1.0)
            details["participation_ratio"] = float(participation_ratio)
            if participation_ratio > max_participation_ratio:
                passed = False
                details["warnings"].append(
                    f"Order rejected: Participation ratio {participation_ratio:.2%} exceeds limit of {max_participation_ratio:.2%}."
                )
        else:
            passed = False
            details["warnings"].append("Order rejected: No reliable recent average volume available.")

        if bid_ask_spread_pct is not None:
            max_spread = self.config.get("max_bid_ask_spread_pct", 0.005)
            if bid_ask_spread_pct > max_spread:
                passed = False
                details["warnings"].append(
                    f"Order rejected: Bid-ask spread {bid_ask_spread_pct:.3%} exceeds limit of {max_spread:.3%}."
                )

        impact_coefficient = self.config.get("market_impact_coefficient", 0.5)
        if (
            recent_avg_volume
            and recent_avg_volume > 0
            and current_volatility
            and current_volatility > 0
        ):
            estimated_impact_pct = float(
                impact_coefficient
                * current_volatility
                * np.sqrt(abs(order_size) / recent_avg_volume)
            )
            details["estimated_impact_pct"] = estimated_impact_pct

            lookback_prices = [price for price in list(self.price_history)[-5:] if price is not None]
            if lookback_prices:
                avg_price = float(np.mean(lookback_prices))
                details["total_estimated_impact_cost"] = (
                    estimated_impact_pct * abs(order_size) * avg_price
                )

        if not passed:
            logger.warning(
                "Liquidity/Impact check FAILED. Reasons: %s",
                "; ".join(details["warnings"]),
            )

        return passed, details

    # --- Leverage and Exposure Check ---
    def check_leverage_and_exposure(
        self,
        proposed_trade_value: float,
        portfolio_value: float,
        gross_position_value: float,
        cash: float,
    ) -> tuple[bool, list[str]]:
        """
        Pre-trade check for leverage and exposure limits.

        Args:
            proposed_trade_value (float): The absolute value of the proposed trade.
            portfolio_value (float): The current total equity of the portfolio.
            gross_position_value (float): The current gross value of all positions (sum of absolutes).
            cash (float): The current cash balance.

        Returns:
            Tuple[bool, List[str]]: A tuple containing a boolean (True if passed) and a list of warnings.
        """
        warnings = []
        passed = True

        # Ensure portfolio value is positive to avoid division by zero
        if portfolio_value <= 0:
            passed = False
            warnings.append("Cannot trade with zero or negative portfolio value.")
            return passed, warnings

        # 1. Gross Exposure Check (fatal if breached)
        max_gross_exposure = self.config.get("max_gross_exposure", 1.5)
        new_gross_position_value = gross_position_value + proposed_trade_value
        new_gross_exposure = new_gross_position_value / portfolio_value

        if new_gross_exposure > max_gross_exposure:
            passed = False
            warnings.append(
                f"Order rejected: New gross exposure {new_gross_exposure:.2%} "
                f"would exceed limit of {max_gross_exposure:.2%}."
            )

        # 2. Buying Power / Cash (warning-level)
        if proposed_trade_value > cash:
            warnings.append(
                f"Trade value ${proposed_trade_value:,.2f} may exceed cash ${cash:,.2f}."
            )

        if not passed:
            logger.warning(f"Leverage/Exposure check FAILED. Reasons: {'; '.join(warnings)}")

        return passed, warnings

    def _calculate_rolling_var(
        self, portfolio_value: float, method: str, window: int = 30
    ) -> list[float]:
        """
        Calculates the rolling VaR over a specified window.
        """
        if len(self.returns_history) < window:
            return []

        rolling_vars = []
        returns_array = np.array(self.returns_history)

        for i in range(window, len(returns_array) + 1):
            window_returns = returns_array[i - window : i]

            if method == "historical":
                var_return = np.percentile(window_returns, self.var_confidence * 100)
            elif method == "parametric":
                mean_return = np.mean(window_returns)
                std_return = np.std(window_returns)
                from scipy.stats import norm

                var_return = norm.ppf(self.var_confidence, mean_return, std_return)

            var_amount = abs(var_return * portfolio_value)
            rolling_vars.append(var_amount)

        return rolling_vars

    def check_liquidity_risk(
        self,
        symbol: str,
        order_size: float,
        current_volume: float,
        bid_ask_spread: float = None,
    ) -> dict:
        """
        Assesses liquidity risk for a potential trade.

        Args:
            symbol: The symbol of the asset.
            order_size: The size of the proposed order.
            current_volume: The current market volume for the asset.
            bid_ask_spread: The current bid-ask spread, as a decimal (e.g., 0.01 for 1%).

        Returns:
            A dictionary containing the liquidity risk assessment.
        """
        assessment = {
            "symbol": symbol,
            "liquidity_score": "UNKNOWN",
            "market_impact_estimate": 0.0,
            "recommended_max_order": 0.0,
            "warnings": [],
        }

        # Calculate the order's proportion of the total volume
        if current_volume > 0:
            volume_ratio = abs(order_size) / current_volume

            # Assign a liquidity score
            if volume_ratio < 0.01:  # Less than 1% of volume
                assessment["liquidity_score"] = "HIGH"
                # Estimate market impact using a simple model
                assessment["market_impact_estimate"] = volume_ratio * 0.1
            elif volume_ratio < 0.05:  # 1-5%
                assessment["liquidity_score"] = "MEDIUM"
                assessment["market_impact_estimate"] = volume_ratio * 0.2
                assessment["warnings"].append("Moderate liquidity risk detected.")
            else:  # Greater than 5%
                assessment["liquidity_score"] = "LOW"
                assessment["market_impact_estimate"] = volume_ratio * 0.5
                assessment["warnings"].append(
                    "High liquidity risk. Consider splitting the order into smaller chunks."
                )

            # Recommend a maximum order size (e.g., not to exceed 2% of volume)
            assessment["recommended_max_order"] = current_volume * 0.02

        # Check the bid-ask spread
        if bid_ask_spread is not None:
            if bid_ask_spread > 0.01:  # Spread greater than 1%
                assessment["warnings"].append(
                    f"High bid-ask spread: {bid_ask_spread:.2%}"
                )

        logger.info(
            f"Liquidity assessment for {symbol}: {assessment['liquidity_score']}. "
            f"Estimated market impact: {assessment['market_impact_estimate']:.2%}"
        )
        return assessment

    def validate_market_data(
        self,
        price: float,
        volume: float,
        previous_price: float = None,
        futures_price: float = None,
    ) -> dict:
        """
        Validates market data for quality and reasonableness.

        Args:
            price: The current price.
            volume: The trading volume.
            previous_price: The price from the previous period for comparison.
            futures_price: The corresponding futures price, if applicable.

        Returns:
            A dictionary with validation results.
        """
        validation = {"is_valid": True, "errors": [], "warnings": []}

        # Basic data sanity checks
        if price <= 0:
            validation["is_valid"] = False
            validation["errors"].append(f"Invalid price: {price}")

        if volume < 0:
            validation["is_valid"] = False
            validation["errors"].append(f"Invalid volume: {volume}")

        # Price sanity check
        if previous_price is not None and previous_price > 0:
            price_change = abs(price - previous_price) / previous_price
            if price_change > 0.2:  # 20% change threshold
                validation["warnings"].append(
                    f"Unusual price change detected: {price_change:.2%}"
                )

        # Futures vs. spot price check
        if futures_price is not None and futures_price > 0:
            price_diff = abs(futures_price - price) / price
            if price_diff > 0.05:  # 5% difference threshold
                validation["warnings"].append(
                    f"Unusual spread between futures and spot price: {price_diff:.2%}"
                )

        # Futures vs. spot price check
        if len(self.volume_history) >= 5:
            avg_volume = np.mean(list(self.volume_history)[-5:])
            if volume > avg_volume * 10:  # 10x spike
                validation["warnings"].append(
                    f"Unusual volume spike: {volume/avg_volume:.1f}x the recent average"
                )

        return validation

    def get_risk_summary(self, portfolio_value: float) -> dict:
        """
        Generates a summary report of key risk metrics
        """
        summary = {
            "timestamp": datetime.now(),
            "portfolio_value": portfolio_value,
            "data_points": len(self.returns_history),
            "var_analysis": None,
            "recent_alerts": [],
            "risk_metrics": {},
        }

        # VaR analysis
        if len(self.returns_history) >= 30:
            summary["var_analysis"] = self.calculate_var(portfolio_value)

        # Other risk metrics
        if len(self.returns_history) > 0:
            returns_array = np.array(self.returns_history)
            summary["risk_metrics"] = {
                "volatility": np.std(returns_array),
                "max_drawdown": self._calculate_max_drawdown(),
                "sharpe_ratio": self._calculate_sharpe_ratio(returns_array),
                "skewness": self._calculate_skewness(returns_array),
                "kurtosis": self._calculate_kurtosis(returns_array),
            }

        return summary

    def _calculate_max_drawdown(self) -> float:
        """
        Calculates the maximum drawdown from the price history
        """
        if len(self.price_history) < 2:
            return 0.0

        prices = np.array(self.price_history, dtype=float)
        # Use price relatives starting at 1 to ensure drawdowns from the
        # initial price are captured correctly
        cumulative = prices / prices[0]
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        return abs(drawdown.min())

    def _calculate_sharpe_ratio(
        self, returns: np.ndarray, risk_free_rate: float = 0.02
    ) -> float:
        """
        Calculates the annualized Sharpe ratio
        """
        if len(returns) == 0:
            return 0.0

        # Daily risk-free rate
        excess_returns = returns - risk_free_rate / 252
        if np.std(excess_returns) == 0:
            return 0.0

        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)

    def _calculate_skewness(self, returns: np.ndarray) -> float:
        """
        Calculates the skewness of the returns distribution
        """
        if len(returns) < 3:
            return 0.0

        from scipy.stats import skew

        return skew(returns)

    def _calculate_kurtosis(self, returns: np.ndarray) -> float:
        """
        Calculates the excess kurtosis of the returns distribution
        """
        if len(returns) < 4:
            return 0.0

        from scipy.stats import kurtosis

        return kurtosis(returns)
