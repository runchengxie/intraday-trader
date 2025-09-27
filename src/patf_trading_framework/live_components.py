import collections
import logging

import numpy as np

logger = logging.getLogger(__name__)


class LiveMeanReversionStrategy:
    def __init__(
        self,
        symbol: str,
        zscore_period: int,
        zscore_upper: float,
        zscore_lower: float,
        exit_threshold: float,
        **kwargs,
    ):
        self.symbol = symbol
        self.zscore_period = zscore_period
        self.zscore_upper = zscore_upper
        self.zscore_lower = zscore_lower
        self.exit_threshold = exit_threshold
        self.prices = collections.deque(maxlen=self.zscore_period)
        self.current_zscore = None
        logger.info(
            f"LiveMeanReversionStrategy for {self.symbol} initialized with: "
            f"Period={self.zscore_period}, UpperZ={self.zscore_upper}, "
            f"LowerZ={self.zscore_lower}, ExitThresholdZ={self.exit_threshold}"
        )

    def _calculate_zscore(self):
        if len(self.prices) < self.zscore_period:
            self.current_zscore = None
            logger.debug(
                f"Not enough data for Z-score calculation for {self.symbol}. Have {len(self.prices)}, need {self.zscore_period}"
            )
            return False

        prices_arr = np.array(self.prices)
        sma = np.mean(prices_arr)
        stdev = np.std(prices_arr)

        if stdev < 1e-6:
            self.current_zscore = None
            logger.warning(
                f"Standard deviation for {self.symbol} is too small ({stdev:.4f}) to calculate Z-score reliably."
            )
            return False

        current_price = self.prices[-1]
        self.current_zscore = (current_price - sma) / stdev
        logger.debug(
            f"Calculated Z-score for {self.symbol}: {self.current_zscore:.2f} (Price={current_price:.2f}, SMA={sma:.2f}, StdDev={stdev:.2f})"
        )
        return True

    def get_signal(self, current_price: float, current_position_qty: float):
        self.prices.append(current_price)

        if not self._calculate_zscore() or self.current_zscore is None:
            return "HOLD"

        z = self.current_zscore
        signal = "HOLD"

        if current_position_qty > 0.01:
            if z >= self.exit_threshold:
                logger.info(
                    f"Signal: CLOSE LONG for {self.symbol} (Z-score {z:.2f} >= Exit {self.exit_threshold}, Position: {current_position_qty})"
                )
                signal = "CLOSE"
        elif current_position_qty < -0.01:
            if z <= self.exit_threshold:
                logger.info(
                    f"Signal: CLOSE SHORT for {self.symbol} (Z-score {z:.2f} <= Exit {self.exit_threshold}, Position: {current_position_qty})"
                )
                signal = "CLOSE"

        if signal == "HOLD" and abs(current_position_qty) < 0.01:
            if z < self.zscore_lower:
                logger.info(
                    f"Signal: BUY for {self.symbol} (Z-score {z:.2f} < Lower {self.zscore_lower})"
                )
                signal = "BUY"
            elif z > self.zscore_upper:
                logger.info(
                    f"Signal: SELL for {self.symbol} (Z-score {z:.2f} > Upper {self.zscore_upper})"
                )
                signal = "SELL"

        if signal == "HOLD":
            logger.debug(
                f"Signal: HOLD for {self.symbol} (Z-score {z:.2f}, Position: {current_position_qty})"
            )

        return signal

    def generate_signal(self, market_data: dict) -> str:
        """Generate trading signal based on market data."""
        current_price = market_data.get("price", 0.0)
        # Assume no current position for simplicity, or get from trading state
        current_position_qty = 0.0
        signal = self.get_signal(current_price, current_position_qty)

        # Convert signal format to match expected output
        if signal == "BUY":
            return "buy"
        elif signal == "SELL":
            return "sell"
        elif signal == "CLOSE":
            return "sell" if current_position_qty > 0 else "buy"
        else:
            return "hold"

    def get_signal_confidence(self) -> float:
        """Return confidence level of the current signal based on Z-score magnitude."""
        if self.current_zscore is None:
            return 0.0

        # Confidence based on how far the Z-score is from thresholds
        abs_zscore = abs(self.current_zscore)

        # Higher confidence for stronger signals
        if abs_zscore >= max(abs(self.zscore_upper), abs(self.zscore_lower)):
            return min(0.95, 0.5 + abs_zscore * 0.1)  # Cap at 95%
        elif abs_zscore >= abs(self.exit_threshold):
            return min(0.8, 0.3 + abs_zscore * 0.1)
        else:
            return max(0.1, abs_zscore * 0.2)  # Minimum 10% confidence


class TradingState:
    """Manages the real-time state of the trading bot."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.current_position_qty: float = 0.0
        self.active_order_id: str | None = None
        self.target_position_qty: float = 0.0
        self.last_known_cash: float | None = None
        self.last_known_portfolio_value: float | None = None
        self.last_trade_price: float | None = None
        self.last_bar_close: float | None = None
        self.positions = {symbol: 0.0}
        self.cash = 0.0
        self.latest_prices = {}
        
        # Enhanced order tracking for reconciliation
        self.last_known_stream_status: str | None = None
        self.active_order_client_id: str | None = None
        self.order_status_history = []  # Track status changes for debugging
        self.last_stream_update_time: float | None = None

    def get_position(self, symbol: str) -> float:
        """Get current position for a symbol."""
        return self.positions.get(symbol, 0.0)

    def get_portfolio_value(self) -> float:
        """Calculate total portfolio value (cash + positions)."""
        total_value = self.cash
        for symbol, quantity in self.positions.items():
            if symbol in self.latest_prices:
                total_value += quantity * self.latest_prices[symbol]
        return total_value

    def get_positions(self) -> dict:
        """Get all current positions."""
        return self.positions.copy()

    def update_position(self, new_qty: float):
        logger.info(
            f"Updating position for {self.symbol} from {self.current_position_qty} to {new_qty}"
        )
        self.current_position_qty = new_qty
        self.positions[self.symbol] = new_qty

    def update_cash_and_value(self, cash: float, value: float):
        self.last_known_cash = cash
        self.last_known_portfolio_value = value
        self.cash = cash  # Update cash for portfolio calculation
        logger.debug(f"Updated account state: Cash={cash}, PortfolioValue={value}")

    def set_active_order(self, order_id: str | None, client_order_id: str | None = None):
        logger.info(f"Setting active order ID to: {order_id}, client_order_id: {client_order_id}")
        self.active_order_id = order_id
        self.active_order_client_id = client_order_id
        # Reset stream status when setting new order
        self.last_known_stream_status = None
        
    def update_stream_order_status(self, order_id: str, status: str, timestamp: float = None):
        """Update the last known order status from WebSocket stream"""
        import time
        if timestamp is None:
            timestamp = time.time()
            
        if order_id == self.active_order_id:
            old_status = self.last_known_stream_status
            self.last_known_stream_status = status
            self.last_stream_update_time = timestamp
            
            # Track status history for debugging
            self.order_status_history.append({
                'timestamp': timestamp,
                'order_id': order_id,
                'old_status': old_status,
                'new_status': status,
                'source': 'websocket'
            })
            
            logger.debug(f"Updated stream status for order {order_id}: {old_status} -> {status}")
            
    def clear_active_order(self):
        """Clear active order tracking when order is completed"""
        logger.info(f"Clearing active order tracking for {self.active_order_id}")
        self.active_order_id = None
        self.active_order_client_id = None
        self.last_known_stream_status = None
        self.last_stream_update_time = None

    def update_last_price(self, price: float, source: str):
        if source == "trade":
            self.last_trade_price = price
        elif source == "bar":
            self.last_bar_close = price
        # Also update latest_prices for portfolio calculation
        self.latest_prices[self.symbol] = price
        logger.debug(f"Updated last price ({source}) for {self.symbol} to {price}")
