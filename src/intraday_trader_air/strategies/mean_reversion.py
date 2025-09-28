"""Mean reversion strategy driven by rolling Z-Score."""

from __future__ import annotations

import math
import statistics
from collections import deque
from typing import Deque

from .base import BaseStrategy


class MeanReversionZScoreStrategy(BaseStrategy):
    params = (
        ("zscore_period", 20),
        ("zscore_upper", 2.0),
        ("zscore_lower", -2.0),
        ("exit_threshold", 0.0),
        ("order_type", "market"),
        ("limit_price_offset_pct", 0.0005),
        ("force_exit_on_last_bar", True),
    )

    def __init__(self):
        super().__init__()
        self._price_history: Deque[float] = deque(maxlen=self.p.zscore_period)
        self._zscore: float = math.nan
        self._sma: float = math.nan
        self._stdev: float = math.nan
        self._bar_index: int = -1

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _current_price_input(self) -> float:
        if self.p.use_filtered_price and self._filtered_price_series is not None:
            idx = min(self._bar_index, len(self._filtered_price_series) - 1)
            value = self._filtered_price_series.iloc[idx]
            return float(value)
        return float(self.dataclose[0])

    def _update_statistics(self) -> None:
        price = self._current_price_input()
        self._price_history.append(price)

        if len(self._price_history) < self.p.zscore_period:
            self._zscore = math.nan
            self._sma = math.nan
            self._stdev = math.nan
            return

        self._sma = statistics.fmean(self._price_history)
        try:
            self._stdev = statistics.stdev(self._price_history)
        except statistics.StatisticsError:
            self._stdev = 0.0

        denom = self._stdev if self._stdev > 0 else 1e-6
        self._zscore = (price - self._sma) / denom

    # ------------------------------------------------------------------
    # Backtrader hooks
    # ------------------------------------------------------------------
    def prenext(self):
        self._bar_index += 1
        self._update_statistics()
        super().next()

    def nextstart(self):
        self._bar_index += 1
        self._update_statistics()
        super().next()

    def next(self):
        self._bar_index += 1
        self._update_statistics()
        super().next()

    def indicators_ready(self) -> bool:
        return not math.isnan(self._zscore)

    def generate_signal(self) -> int:
        current_z = self._zscore
        if current_z < self.p.zscore_lower:
            return 1
        if current_z > self.p.zscore_upper:
            return -1
        return 0

    def should_exit(self) -> bool:
        current_z = self._zscore
        exit_threshold = self.p.exit_threshold
        if self.position.size > 0:
            return current_z >= exit_threshold
        if self.position.size < 0:
            return current_z <= exit_threshold
        return False

    def enter_position(self, direction: int):
        order_type = self.p.order_type
        limit_offset_pct = self.p.limit_price_offset_pct if order_type == "limit" else None
        action = "BUY" if direction > 0 else "SELL"
        price = (
            self.compute_limit_price(direction, limit_offset_pct)
            if limit_offset_pct is not None
            else self.dataclose[0]
        )
        self.log(
            f"{action} CREATE ({order_type.upper()}), Price: {price:.2f}, Z-Score: {self._zscore:.2f}"
        )
        return self.place_entry(
            direction,
            order_type=order_type,
            limit_offset_pct=limit_offset_pct,
        )

    def exit_position(self):
        side = "LONG" if self.position.size > 0 else "SHORT"
        self.log(
            f"CLOSE {side}, Close: {self.dataclose[0]:.2f}, Z-Score: {self._zscore:.2f}"
        )
        return super().exit_position()
