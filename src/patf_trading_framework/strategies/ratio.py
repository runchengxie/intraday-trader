"""Momentum strategy comparing price to a long-term moving average."""

import pandas as pd

from .base import BaseStrategy
from .utils import compute_ratio


class CustomRatioStrategy(BaseStrategy):
    params = (
        ("long_ma_period", 50),
        ("buy_threshold", 0.98),
        ("sell_threshold", 1.02),
        ("exit_threshold", 1.0),
    )

    def __init__(self):
        super().__init__()
        self.long_ma = compute_ratio(self.dataclose, period=self.p.long_ma_period)
        self.current_ratio = None

    def _current_ratio(self) -> float:
        self.current_ratio = self.dataclose[0] / self.long_ma[0]
        return self.current_ratio

    def indicators_ready(self) -> bool:
        return not (pd.isna(self.long_ma[0]) or self.long_ma[0] == 0)

    def generate_signal(self) -> int:
        ratio = self._current_ratio()
        if ratio < self.p.buy_threshold:
            return 1
        if ratio > self.p.sell_threshold:
            return -1
        return 0

    def should_exit(self) -> bool:
        ratio = self._current_ratio()
        if self.position.size > 0:
            return ratio >= self.p.exit_threshold
        if self.position.size < 0:
            return ratio <= self.p.exit_threshold
        return False

    def enter_position(self, direction: int):
        action = "BUY" if direction > 0 else "SELL"
        ratio = self._current_ratio()
        self.log(
            f"{action} CREATE, Close: {self.dataclose[0]:.2f}, Ratio: {ratio:.4f}"
        )
        return self.place_entry(direction)

    def exit_position(self):
        side = "LONG" if self.position.size > 0 else "SHORT"
        ratio = self._current_ratio()
        self.log(f"CLOSE {side}, Close: {self.dataclose[0]:.2f}, Ratio: {ratio:.4f}")
        return super().exit_position()
