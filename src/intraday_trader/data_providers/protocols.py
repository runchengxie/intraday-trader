"""Market data provider protocol and standard types.

All data-fetching code works through :class:`MarketDataProvider` —
it never sees Alpaca REST objects or Futu OpenQuoteContext directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import pandas as pd

# ---------------------------------------------------------------------------
# Standard bar format
# ---------------------------------------------------------------------------

# Columns every ``get_bars`` result MUST include:
REQUIRED_BAR_COLUMNS = ["open", "high", "low", "close", "volume"]

# Optional columns that may be present (e.g. Alpaca provides trade_count, vwap):
OPTIONAL_BAR_COLUMNS = ["trade_count", "vwap"]


@dataclass
class BarRequest:
    """Normalised request for historical OHLCV bars."""

    symbol: str
    timeframe: str  # "1Min" | "5Min" | "15Min" | "1Day" | ...
    start: str  # ISO date string "YYYY-MM-DD"
    end: str  # ISO date string "YYYY-MM-DD"
    adjustment: str = "raw"  # "raw" | "split" | "dividend" | "all"


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MarketDataProvider(Protocol):
    """Protocol every market-data backend must satisfy.

    Phase 2 covers historical OHLCV bars only.  Real-time streaming
    (tick / bar push) will be added in Phase 3.
    """

    def get_bars(self, request: BarRequest) -> pd.DataFrame | None:
        """Return OHLCV bars for *request*, or None on failure.

        The returned DataFrame must have a DatetimeIndex and include at
        least the columns listed in :data:`REQUIRED_BAR_COLUMNS`.
        """
        ...
