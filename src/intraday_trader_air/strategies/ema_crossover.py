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
    )

    def __init__(self):
        super().__init__()
        self.ema_short = btind.EMA(self.dataclose, period=self.params.ema_short)
        self.ema_long = btind.EMA(self.dataclose, period=self.params.ema_long)
        self.adx = btind.ADX(self.datas[0], period=self.params.adx_period)
        self.crossover = btind.CrossOver(self.ema_short, self.ema_long)

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
            (pd.isna(prev_short) or pd.isna(prev_long) or pd.isna(prev_adx))
            and self.ema_short[0] > self.ema_long[0]
        )

        if (crossed_up or initializing_cross) and self.adx.adx[0] > self.p.adx_threshold:
            return 1
        return 0

    def should_exit(self) -> bool:
        return self.crossover < 0

    def enter_position(self, direction: int):
        self.log(
            f"BUY CREATE, Close: {self.dataclose[0]:.2f}, ADX: {self.adx.adx[0]:.2f}"
        )
        return self.place_entry(direction)

    def exit_position(self):
        self.log(
            f"EXIT LONG, Close: {self.dataclose[0]:.2f}, ADX: {self.adx.adx[0]:.2f}"
        )
        return super().exit_position()
