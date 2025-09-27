import logging
import backtrader as bt
import backtrader.indicators as btind
import pandas as pd
import pytz
from backtrader.utils.date import num2date

# --- Logging Setup ---
logger = logging.getLogger(__name__)  # Create logger for this module
# --- End Logging Setup ---

# --- Order Status Mapping ---
STATUS_NAME = {
    bt.Order.Created:   "created",
    bt.Order.Submitted: "submitted",
    bt.Order.Accepted:  "accepted",
    bt.Order.Partial:   "partial",
    bt.Order.Completed: "completed",
    bt.Order.Canceled:  "canceled",
    bt.Order.Expired:   "expired",
    bt.Order.Margin:    "margin",
    bt.Order.Rejected:  "rejected",
}

# --- Order Logger Mixin ---
class OrderLoggerMixin:
    """Deduplicating state machine that only logs on status changes"""
    
    def __init__(self, *args, **kwargs):
        self._last_order_status = {}
        super().__init__(*args, **kwargs)

    def _bar_dt(self):
        try:
            ny = pytz.timezone("America/New_York")
            dt = num2date(self.data.datetime[0], tz=ny)
            return f"{dt:%Y-%m-%d %H:%M}"
        except Exception:
            return "NA"

    def notify_order(self, order):
        if not hasattr(self, "_last_order_status"):   # belt-and-suspenders
            self._last_order_status = {}
        prev = self._last_order_status.get(order.ref)
        cur = order.status
        if prev == cur:
            return
        self._last_order_status[order.ref] = cur

        name = STATUS_NAME.get(cur, str(cur)).upper()
        dt = self._bar_dt()

        if cur == bt.Order.Completed:
            self.log(f"{dt}, ORDER {order.ref} {name}, "
                     f"Price: {order.executed.price:.2f}, "
                     f"Size: {order.executed.size}, "
                     f"Value: {order.executed.value:.2f}, "
                     f"Comm: {order.executed.comm:.2f}")
        elif cur in (bt.Order.Canceled, bt.Order.Expired, bt.Order.Margin, bt.Order.Rejected):
            self.log(f"{dt}, ORDER {order.ref} {name}")
        elif cur == bt.Order.Partial:
            self.log(f"{dt}, ORDER {order.ref} {name}, Filled: {order.executed.size}")
        elif cur == bt.Order.Accepted:
            # For quieter logging: change this line to DEBUG level or return directly
            self.log(f"{dt}, ORDER {order.ref} {name}")
        # Submitted and other states are silent by default


# --- Base Strategy Class ---
class BaseStrategy(bt.Strategy):
    """Base strategy class containing common functionality for all trading strategies"""
    
    params = (
        ("use_filtered_price", False),
        ("printlog", False),
    )

    def log(self, txt, dt=None, doprint=False):
        """Common logging function with timezone-aware datetime"""
        ny = pytz.timezone("America/New_York")
        if dt is None:
            dt = num2date(self.datas[0].datetime[0], tz=ny)
        log_level = logging.INFO if doprint or self.params.printlog else logging.DEBUG
        logger.log(log_level, f"{dt:%Y-%m-%d %H:%M}, {txt}")

    def _init_price_source(self):
        """Initialize price source based on use_filtered_price parameter"""
        if self.p.use_filtered_price and hasattr(self.datas[0], "filtered_close"):
            self.dataclose = self.datas[0].filtered_close
            self.log("Strategy using FILTERED close price.")
        else:
            self.dataclose = self.datas[0].close
            self.log("Strategy using standard close price.")

    def __init__(self):
        super().__init__()
        self._init_price_source()
        # Common member variables initialization
        self.order = None
        self.buyprice = None
        self.buycomm = None

    def notify_trade(self, trade):
        """Common trade notification handler"""
        if not trade.isclosed:
            return
        self.log(
            f"OPERATION PROFIT, GROSS {trade.pnl:.2f}, NET {trade.pnlcomm:.2f}",
            doprint=True,
        )

    def next(self):
        """Template method: handles common early exit logic, delegates to _next_impl"""
        if self.order:
            return
        if not self._next_impl():
            return

    def _next_impl(self):
        """Strategy-specific implementation to be overridden by subclasses"""
        raise NotImplementedError("Subclasses must implement _next_impl method")


# --- EMA Crossover Strategy ---
class EMACrossoverStrategy(OrderLoggerMixin, BaseStrategy):
    """EMA Crossover strategy with ADX filter"""
    
    # backtrader automatically inherits parent class parameters
    params = (
        ("ema_short", 12),
        ("ema_long", 26),
        ("adx_period", 14),
        ("adx_threshold", 25.0),
    )

    def __init__(self):
        super().__init__()  # ensures BaseStrategy and OrderLoggerMixin.__init__ runs
        
        # Strategy-specific indicator calculations
        self.ema_short = btind.EMA(self.dataclose, period=self.params.ema_short)
        self.ema_long = btind.EMA(self.dataclose, period=self.params.ema_long)
        self.adx = btind.ADX(
            self.datas[0], period=self.params.adx_period
        )  # ADX needs the full data feed
        self.crossover = bt.indicators.CrossOver(self.ema_short, self.ema_long)

    def _next_impl(self):
        """EMA Crossover strategy-specific trading logic"""
        # Check for NaN values in indicators
        if (
            pd.isna(self.ema_short[0])
            or pd.isna(self.ema_long[0])
            or pd.isna(self.adx.adx[0])
        ):
            return False

        adx_threshold = self.p.adx_threshold

        # Entry conditions
        if not self.position:
            if self.crossover > 0 and self.adx.adx[0] > adx_threshold:
                self.log(
                    f"BUY CREATE, Close: {self.dataclose[0]:.2f}, ADX: {self.adx.adx[0]:.2f}"
                )
                self.order = self.buy()
        # Exit conditions
        elif self.crossover < 0:
            self.log(
                f"SELL CREATE (Exit), Close: {self.dataclose[0]:.2f}, ADX: {self.adx.adx[0]:.2f}"
            )
            self.order = self.sell()
        
        return True


# --- Mean Reversion Z-Score Strategy ---
class MeanReversionZScoreStrategy(OrderLoggerMixin, BaseStrategy):
    """Mean reversion strategy based on Z-Score with market/limit order support"""
    
    # backtrader automatically inherits parent class parameters
    params = (
        ("zscore_period", 20),
        ("zscore_upper", 2.0),
        ("zscore_lower", -2.0),
        ("exit_threshold", 0.0),
        ("order_type", "market"),  # 'market' or 'limit'
        ("limit_price_offset_pct", 0.0005),  # 0.05% offset for limit orders
    )

    def __init__(self):
        super().__init__()  # ensures BaseStrategy and OrderLoggerMixin.__init__ runs
        
        # Strategy-specific indicator calculations
        self.sma = btind.SMA(self.dataclose, period=self.p.zscore_period)
        self.stdev = btind.StdDev(self.dataclose, period=self.p.zscore_period)
        
        epsilon = 1e-6
        self.zscore = (self.dataclose - self.sma) / (self.stdev + epsilon)
        
        # Get order type from params
        self.order_type = self.p.order_type

    def _next_impl(self):
        """Mean reversion strategy-specific trading logic"""
        # Check for NaN values in indicators
        if pd.isna(self.zscore[0]):
            return False

        current_zscore = self.zscore[0]
        zscore_lower_threshold = self.p.zscore_lower
        zscore_upper_threshold = self.p.zscore_upper
        exit_threshold = self.p.exit_threshold

        # Entry conditions
        if not self.position:
            if current_zscore < zscore_lower_threshold:
                if self.order_type == 'limit':
                    limit_price = self.dataclose[0] * (1 + self.p.limit_price_offset_pct)
                    self.log(f"BUY CREATE (Limit), Price: {limit_price:.2f}, Z-Score: {current_zscore:.2f}")
                    self.order = self.buy(exectype=bt.Order.Limit, price=limit_price)
                else:
                    self.log(f"BUY CREATE (Market), Z-Score: {current_zscore:.2f}")
                    self.order = self.buy()

            elif current_zscore > zscore_upper_threshold:
                if self.order_type == 'limit':
                    limit_price = self.dataclose[0] * (1 - self.p.limit_price_offset_pct)
                    self.log(f"SELL CREATE (Limit), Price: {limit_price:.2f}, Z-Score: {current_zscore:.2f}")
                    self.order = self.sell(exectype=bt.Order.Limit, price=limit_price)
                else:
                    self.log(f"SELL CREATE (Market), Z-Score: {current_zscore:.2f}")
                    self.order = self.sell()
        
        # Exit conditions
        elif self.position.size > 0 and current_zscore >= exit_threshold:
            self.log(
                f"CLOSE LONG (Z >= Exit), Close: {self.dataclose[0]:.2f}, Z-Score: {current_zscore:.2f}"
            )
            self.order = self.close()
        elif self.position.size < 0 and current_zscore <= exit_threshold:
            self.log(
                f"CLOSE SHORT (Z <= Exit), Close: {self.dataclose[0]:.2f}, Z-Score: {current_zscore:.2f}"
            )
            self.order = self.close()
        
        return True


# --- Custom Ratio Strategy ---
class CustomRatioStrategy(OrderLoggerMixin, BaseStrategy):
    """Custom ratio strategy based on short-term price vs long-term average"""
    
    # backtrader automatically inherits parent class parameters
    params = (
        ("long_ma_period", 50),
        ("buy_threshold", 0.98),
        ("sell_threshold", 1.02),
        ("exit_threshold", 1.0),
    )

    def __init__(self):
        super().__init__()  # ensures BaseStrategy and OrderLoggerMixin.__init__ runs
        
        # Strategy-specific indicator calculations
        self.long_ma = btind.SMA(self.dataclose, period=self.p.long_ma_period)
        self.current_ratio = None

    def _next_impl(self):
        """Custom ratio strategy-specific trading logic"""
        # Check for NaN values or zero division
        if pd.isna(self.long_ma[0]) or self.long_ma[0] == 0:
            return False

        self.current_ratio = self.dataclose[0] / self.long_ma[0]

        buy_threshold = self.p.buy_threshold
        sell_threshold = self.p.sell_threshold
        exit_threshold = self.p.exit_threshold

        # Entry conditions
        if not self.position:
            if self.current_ratio < buy_threshold:
                self.log(
                    f"BUY CREATE (Ratio < Buy Thr), Close: {self.dataclose[0]:.2f}, Ratio: {self.current_ratio:.4f}"
                )
                self.order = self.buy()
            elif self.current_ratio > sell_threshold:
                self.log(
                    f"SELL CREATE (Ratio > Sell Thr), Close: {self.dataclose[0]:.2f}, Ratio: {self.current_ratio:.4f}"
                )
                self.order = self.sell()
        
        # Exit conditions
        elif self.position.size > 0 and self.current_ratio >= exit_threshold:
            self.log(
                f"CLOSE LONG (Ratio >= Exit Thr), Close: {self.dataclose[0]:.2f}, Ratio: {self.current_ratio:.4f}"
            )
            self.order = self.close()
        elif self.position.size < 0 and self.current_ratio <= exit_threshold:
            self.log(
                f"CLOSE SHORT (Ratio <= Exit Thr), Close: {self.dataclose[0]:.2f}, Ratio: {self.current_ratio:.4f}"
            )
            self.order = self.close()
        
        return True
