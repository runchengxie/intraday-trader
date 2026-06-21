"""Core building blocks shared across trading strategies."""

from __future__ import annotations

import logging

import backtrader as bt
import pytz
from backtrader.utils.autodict import AutoOrderedDict
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
        elif cur in (
            bt.Order.Canceled,
            bt.Order.Expired,
            bt.Order.Margin,
            bt.Order.Rejected,
        ):
            self.log(f"{dt}, ORDER {order.ref} {name}")
        elif cur == bt.Order.Partial:
            self.log(f"{dt}, ORDER {order.ref} {name}, Filled: {order.executed.size}")
        elif cur == bt.Order.Accepted:
            self.log(f"{dt}, ORDER {order.ref} {name}")

        if cur in (
            bt.Order.Completed,
            bt.Order.Canceled,
            bt.Order.Expired,
            bt.Order.Margin,
            bt.Order.Rejected,
        ) and hasattr(self, "order"):
            self.order = None


class BaseStrategy(OrderLoggerMixin, bt.Strategy):
    """Template strategy that centralises shared plumbing."""

    params = (
        ("use_filtered_price", False),
        ("printlog", False),
        ("force_exit_on_last_bar", False),
        ("size_pct", None),
    )

    def __init__(self):
        super().__init__()
        self._logger = logging.getLogger(self.__class__.__module__)
        self._init_price_source()
        self.order = None
        self.buyprice = None
        self.buycomm = None
        self._forced_liquidation_done = False

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
        data = self.datas[0]
        self._filtered_price_series: pd.Series | None = None

        if self.p.use_filtered_price and hasattr(data, "filtered_close"):
            self.dataclose = data.filtered_close
            self.log("Strategy using FILTERED close price.")
            return

        # Fallback: PandasData may carry the column in the raw DataFrame even if
        # Backtrader didn't map it to a dedicated line.
        raw_source = getattr(getattr(data, "p", None), "dataname", None)
        if (
            self.p.use_filtered_price
            and hasattr(raw_source, "__getitem__")
            and "filtered_close" in getattr(raw_source, "columns", [])
        ):
            try:
                import pandas as pd  # Local import to avoid hard dependency at module load

                column = raw_source["filtered_close"]
                if not isinstance(column, pd.Series):
                    column = pd.Series(column)
                self._filtered_price_series = column.reset_index(drop=True)
                self.log("Strategy using FILTERED close price (DataFrame column).")
            except Exception:
                self._filtered_price_series = None

        self.dataclose = data.close
        if self._filtered_price_series is None:
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
        computed_size = (
            size if size is not None else self._default_position_size(direction)
        )
        if computed_size == 0:
            self.log(
                "Skipping order because computed size is zero; check size_pct and available cash."
            )
            return None
        kwargs["size"] = computed_size

        if direction > 0:
            return self.buy(**kwargs)
        if direction < 0:
            return self.sell(**kwargs)
        raise ValueError("Direction must be +1 or -1 when placing an order")

    def compute_limit_price(self, direction: int, limit_offset_pct: float) -> float:
        offset = abs(limit_offset_pct)
        base_price = self.dataclose[0]
        return base_price * (1 + offset) if direction > 0 else base_price * (1 - offset)

    def _default_position_size(self, direction: int) -> int:
        """Calculate the default position size using ``size_pct`` of capital."""

        if self.p.size_pct is None:
            return 1 if direction > 0 else -1

        try:
            price = float(self.dataclose[0])
        except Exception:
            return 0

        if price <= 0:
            return 0

        alloc_pct = max(0.0, float(self.p.size_pct))
        if alloc_pct == 0.0:
            return 0

        if direction > 0:
            cash = float(self.broker.getcash())
            target_value = cash * min(alloc_pct, 1.0)
            size = int(target_value / price)
        else:
            portfolio_value = float(self.broker.getvalue())
            target_value = portfolio_value * min(alloc_pct, 1.0)
            size = int(target_value / price)

        if size <= 0:
            return 0
        return size if direction > 0 else -size

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

        # Backtrader does not automatically flatten positions on the last bar.
        # Force a liquidation so test fixtures and reports have closed trades.
        if (
            self.p.force_exit_on_last_bar
            and not self.order
            and self.position
            and len(self) >= len(self.data)
            and not self._forced_liquidation_done
        ):
            self.log("Final bar reached; force-closing open position.")
            self.order = self.exit_position()
            self._forced_liquidation_done = True

    def stop(self):
        analyzer = getattr(self.analyzers, "trades", None)
        if analyzer is None:
            return super().stop()

        analysis = analyzer.get_analysis()
        if not isinstance(analysis, AutoOrderedDict):
            return super().stop()

        total_block = analysis.get("total", {})
        open_trades = total_block.get("open", 0)

        analysis.setdefault("won", AutoOrderedDict())
        analysis.setdefault("lost", AutoOrderedDict())
        analysis["won"].setdefault("total", analysis["won"].get("total", 0))
        analysis["lost"].setdefault("total", analysis["lost"].get("total", 0))

        if open_trades and self.position.size != 0:
            entry_price = getattr(self.position, "price", None)
            try:
                current_price = float(self.dataclose[0])
            except Exception:
                current_price = None

            if entry_price is not None and current_price is not None:
                pnl = (current_price - entry_price) * self.position.size
                if pnl > 0:
                    analysis["won"]["total"] += open_trades
                elif pnl < 0:
                    analysis["lost"]["total"] += open_trades

        return super().stop()
