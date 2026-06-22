"""Multi-provider market data layer (Phase 2).

Exports:
    - ``protocols``: standard data types and the MarketDataProvider protocol.
    - ``factory.create_data_provider``: instantiate the configured provider.
    - ``AlpacaMarketDataProvider``, ``FutuMarketDataProvider``: concrete providers.
"""

from .alpaca import AlpacaMarketDataProvider
from .factory import create_data_provider
from .futu import FutuMarketDataProvider

__all__ = [
    "AlpacaMarketDataProvider",
    "FutuMarketDataProvider",
    "create_data_provider",
]
