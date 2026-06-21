"""Strategy package exposing built-in trading strategies and registry."""

from .base import BaseStrategy, OrderLoggerMixin
from .buy_and_hold import BuyAndHoldStrategy
from .ema_crossover import EMACrossoverStrategy
from .mean_reversion import MeanReversionZScoreStrategy
from .ratio import CustomRatioStrategy

REGISTRY = {
    "ema_crossover": EMACrossoverStrategy,
    "mean_reversion": MeanReversionZScoreStrategy,
    "custom_ratio": CustomRatioStrategy,
    "buy_and_hold": BuyAndHoldStrategy,
    "EMACrossoverStrategy": EMACrossoverStrategy,
    "MeanReversionZScoreStrategy": MeanReversionZScoreStrategy,
    "CustomRatioStrategy": CustomRatioStrategy,
    "BuyAndHoldStrategy": BuyAndHoldStrategy,
}

BuyAndHold = BuyAndHoldStrategy
EMACrossover = EMACrossoverStrategy
MeanReversion = MeanReversionZScoreStrategy
RatioStrategy = CustomRatioStrategy

__all__ = [
    "REGISTRY",
    "BaseStrategy",
    "BuyAndHold",
    "BuyAndHoldStrategy",
    "CustomRatioStrategy",
    "EMACrossover",
    "EMACrossoverStrategy",
    "MeanReversion",
    "MeanReversionZScoreStrategy",
    "OrderLoggerMixin",
    "RatioStrategy",
]
