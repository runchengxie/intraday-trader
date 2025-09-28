"""Strategy package exposing built-in trading strategies and registry."""

from .base import BaseStrategy, OrderLoggerMixin
from .ema_crossover import EMACrossoverStrategy
from .mean_reversion import MeanReversionZScoreStrategy
from .ratio import CustomRatioStrategy

REGISTRY = {
    "ema_crossover": EMACrossoverStrategy,
    "mean_reversion": MeanReversionZScoreStrategy,
    "custom_ratio": CustomRatioStrategy,
    "EMACrossoverStrategy": EMACrossoverStrategy,
    "MeanReversionZScoreStrategy": MeanReversionZScoreStrategy,
    "CustomRatioStrategy": CustomRatioStrategy,
}

__all__ = [
    "BaseStrategy",
    "OrderLoggerMixin",
    "EMACrossoverStrategy",
    "MeanReversionZScoreStrategy",
    "CustomRatioStrategy",
    "REGISTRY",
]
