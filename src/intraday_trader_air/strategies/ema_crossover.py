"""Trend-following EMA crossover strategy with ADX confirmation."""

import backtrader.indicators as btind
import pandas as pd

from .base import BaseStrategy


class EMACrossoverStrategy(BaseStrategy):
    params = (
        ("ema_short", 12),
        ("ema_long", 26),
        ("adx_period", 14),
        ("adx_threshold", 25.0),
        ("trailing_stop_pct", None),
    )

    def __init__(self):
        super().__init__()
        self.ema_short = btind.EMA(self.dataclose, period=self.params.ema_short)
        self.ema_long = btind.EMA(self.dataclose, period=self.params.ema_long)
        self.adx = btind.ADX(self.datas[0], period=self.params.adx_period)
        self.crossover = btind.CrossOver(self.ema_short, self.ema_long)
        self._highest_close: float | None = None
        self._trailing_stop_price: float | None = None

    def indicators_ready(self) -> bool:
        return not (
            pd.isna(self.ema_short[0])
            or pd.isna(self.ema_long[0])
            or pd.isna(self.adx.adx[0])
        )

    def generate_signal(self) -> int:
        crossed_up = self.crossover > 0
        prev_short = self.ema_short[-1]
        prev_long = self.ema_long[-1]
        prev_adx = self.adx.adx[-1]
        initializing_cross = (
            pd.isna(prev_short) or pd.isna(prev_long) or pd.isna(prev_adx)
        ) and self.ema_short[0] > self.ema_long[0]

        if (crossed_up or initializing_cross) and self.adx.adx[
            0
        ] > self.p.adx_threshold:
            return 1
        return 0

    def should_exit(self) -> bool:
        exit_on_cross = self.crossover < 0
        trailing_stop_hit = False

        if self.position.size > 0 and self._trailing_stop_price is not None:
            try:
                current_price = float(self.dataclose[0])
            except Exception:
                current_price = None
            if current_price is not None and current_price <= self._trailing_stop_price:
                trailing_stop_hit = True

        if trailing_stop_hit:
            self.log(
                "TRAILING STOP HIT, Close: %.2f, Stop: %.2f"
                % (self.dataclose[0], self._trailing_stop_price)
            )

        return exit_on_cross or trailing_stop_hit

    def enter_position(self, direction: int):
        self.log(
            f"BUY CREATE, Close: {self.dataclose[0]:.2f}, ADX: {self.adx.adx[0]:.2f}"
        )
        order = self.place_entry(direction)
        if order is not None:
            self._highest_close = float(self.dataclose[0])
            self._update_trailing_stop(initial=True)
        return order

    def exit_position(self):
        self.log(
            f"EXIT LONG, Close: {self.dataclose[0]:.2f}, ADX: {self.adx.adx[0]:.2f}"
        )
        self._highest_close = None
        self._trailing_stop_price = None
        return super().exit_position()

    def next(self):
        if self.position.size > 0:
            try:
                current_close = float(self.dataclose[0])
            except Exception:
                current_close = None
            if current_close is not None:
                if self._highest_close is None or current_close > self._highest_close:
                    self._highest_close = current_close
                self._update_trailing_stop()
        super().next()

    def _update_trailing_stop(self, *, initial: bool = False) -> None:
        pct = self.p.trailing_stop_pct
        if pct in (None, 0):
            self._trailing_stop_price = None
            return

        if self._highest_close is None:
            return

        stop_price = self._highest_close * (1 - float(pct))
        if initial or self._trailing_stop_price is None:
            self._trailing_stop_price = stop_price
        else:
            self._trailing_stop_price = max(self._trailing_stop_price, stop_price)
