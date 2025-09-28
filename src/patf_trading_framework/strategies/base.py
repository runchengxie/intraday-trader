"""Core building blocks shared across trading strategies."""

from __future__ import annotations

import logging

import backtrader as bt
import pytz
from backtrader.utils.date import num2date

STATUS_NAME = {
    bt.Order.Created: "created",
    bt.Order.Submitted: "submitted",
    bt.Order.Accepted: "accepted",
    bt.Order.Partial: "partial",
    bt.Order.Completed: "completed",
    bt.Order.Canceled: "canceled",
    bt.Order.Expired: "expired",
    bt.Order.Margin: "margin",
    bt.Order.Rejected: "rejected",
}


class OrderLoggerMixin:
    """Deduplicate order notifications so logs stay readable."""

    def __init__(self, *args, **kwargs):
        self._last_order_status = {}
        super().__init__(*args, **kwargs)

    def _bar_dt(self) -> str:
        try:
            ny = pytz.timezone("America/New_York")
            dt = num2date(self.data.datetime[0], tz=ny)
            return f"{dt:%Y-%m-%d %H:%M}"
        except Exception:
            return "NA"

    def notify_order(self, order):
        prev = self._last_order_status.get(order.ref)
        cur = order.status
        if prev == cur:
            return
        self._last_order_status[order.ref] = cur

        name = STATUS_NAME.get(cur, str(cur)).upper()
        dt = self._bar_dt()

        if cur == bt.Order.Completed:
            self.log(
                f"{dt}, ORDER {order.ref} {name}, Price: {order.executed.price:.2f}, Size: {order.executed.size}, Value: {order.executed.value:.2f}, Comm: {order.executed.comm:.2f}"
            )
        elif cur in (bt.Order.Canceled, bt.Order.Expired, bt.Order.Margin, bt.Order.Rejected):
            self.log(f"{dt}, ORDER {order.ref} {name}")
        elif cur == bt.Order.Partial:
            self.log(f"{dt}, ORDER {order.ref} {name}, Filled: {order.executed.size}")
        elif cur == bt.Order.Accepted:
            self.log(f"{dt}, ORDER {order.ref} {name}")


class BaseStrategy(OrderLoggerMixin, bt.Strategy):
    """Template strategy that centralises shared plumbing."""

    params = (
        ("use_filtered_price", False),
        ("printlog", False),
    )

    def __init__(self):
        super().__init__()
        self._logger = logging.getLogger(self.__class__.__module__)
        self._init_price_source()
        self.order = None
        self.buyprice = None
        self.buycomm = None

    # ------------------------------------------------------------------
    # Common utilities
    # ------------------------------------------------------------------
    def log(self, txt: str, dt=None, doprint: bool = False):
        ny = pytz.timezone("America/New_York")
        if dt is None:
            dt = num2date(self.datas[0].datetime[0], tz=ny)
        log_level = logging.INFO if doprint or self.params.printlog else logging.DEBUG
        logging.getLogger(__name__).log(log_level, f"{dt:%Y-%m-%d %H:%M}, {txt}")

    def _init_price_source(self) -> None:
        if self.p.use_filtered_price and hasattr(self.datas[0], "filtered_close"):
            self.dataclose = self.datas[0].filtered_close
            self.log("Strategy using FILTERED close price.")
        else:
            self.dataclose = self.datas[0].close
            self.log("Strategy using standard close price.")

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(
            f"OPERATION PROFIT, GROSS {trade.pnl:.2f}, NET {trade.pnlcomm:.2f}",
            doprint=True,
        )

    # ------------------------------------------------------------------
    # Hooks to be customised per strategy
    # ------------------------------------------------------------------
    def indicators_ready(self) -> bool:
        """Return True when indicator values for this bar are valid."""

        return True

    def generate_signal(self) -> int:
        """Return 1/-1/0 to request a long/short/flat entry."""

        return 0

    def should_exit(self) -> bool:
        """Return True when the current position should be flattened."""

        return False

    def enter_position(self, direction: int):
        """Submit the default market order for the provided direction."""

        return self.place_entry(direction)

    def exit_position(self):
        """Flatten the current position."""

        return self.close()

    # ------------------------------------------------------------------
    # Shared order helpers
    # ------------------------------------------------------------------
    def place_entry(
        self,
        direction: int,
        *,
        order_type: str = "market",
        limit_offset_pct: float | None = None,
        size: float | None = None,
    ):
        """Place either a market or limit order in the requested direction."""

        kwargs = {}
        if order_type == "limit" and limit_offset_pct is not None:
            price = self.compute_limit_price(direction, limit_offset_pct)
            kwargs["exectype"] = bt.Order.Limit
            kwargs["price"] = price
        if size is not None:
            kwargs["size"] = size

        if direction > 0:
            return self.buy(**kwargs)
        elif direction < 0:
            return self.sell(**kwargs)
        raise ValueError("Direction must be +1 or -1 when placing an order")

    def compute_limit_price(self, direction: int, limit_offset_pct: float) -> float:
        offset = abs(limit_offset_pct)
        base_price = self.dataclose[0]
        return base_price * (1 + offset) if direction > 0 else base_price * (1 - offset)

    # ------------------------------------------------------------------
    # Core template method
    # ------------------------------------------------------------------
    def next(self):
        if self.order:
            return
        if not self.indicators_ready():
            return

        if not self.position:
            signal = self.generate_signal()
            if signal > 0:
                self.order = self.enter_position(1)
            elif signal < 0:
                self.order = self.enter_position(-1)
        elif self.should_exit():
            self.order = self.exit_position()
