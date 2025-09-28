"""Mean reversion strategy driven by rolling Z-Score."""

import pandas as pd

from .base import BaseStrategy
from .utils import compute_zscore


class MeanReversionZScoreStrategy(BaseStrategy):
    params = (
        ("zscore_period", 20),
        ("zscore_upper", 2.0),
        ("zscore_lower", -2.0),
        ("exit_threshold", 0.0),
        ("order_type", "market"),
        ("limit_price_offset_pct", 0.0005),
    )

    def __init__(self):
        super().__init__()
        self.zscore, self.sma, self.stdev = compute_zscore(
            self.dataclose, period=self.p.zscore_period
        )

    def indicators_ready(self) -> bool:
        return not pd.isna(self.zscore[0])

    def generate_signal(self) -> int:
        current_z = self.zscore[0]
        if current_z < self.p.zscore_lower:
            return 1
        if current_z > self.p.zscore_upper:
            return -1
        return 0

    def should_exit(self) -> bool:
        current_z = self.zscore[0]
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
            f"{action} CREATE ({order_type.upper()}), Price: {price:.2f}, Z-Score: {self.zscore[0]:.2f}"
        )
        return self.place_entry(
            direction,
            order_type=order_type,
            limit_offset_pct=limit_offset_pct,
        )

    def exit_position(self):
        side = "LONG" if self.position.size > 0 else "SHORT"
        self.log(
            f"CLOSE {side}, Close: {self.dataclose[0]:.2f}, Z-Score: {self.zscore[0]:.2f}"
        )
        return super().exit_position()
