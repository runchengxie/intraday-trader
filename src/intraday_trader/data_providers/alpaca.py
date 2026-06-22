"""Alpaca market data provider.

Wraps an ``alpaca_trade_api.rest.REST`` client and translates
:class:`~intraday_trader.data_providers.protocols.BarRequest` into
Alpaca ``get_bars()`` calls.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

import pandas as pd
from alpaca_trade_api.rest import REST, TimeFrame
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .protocols import BarRequest

logger = logging.getLogger(__name__)

# Alpaca timeframe string → TimeFrame enum
_ALPACA_TIMEFRAME_MAP: dict[str, TimeFrame] = {
    "1Min": TimeFrame.Minute,
    "5Min": TimeFrame(5, TimeFrame.Minute),
    "15Min": TimeFrame(15, TimeFrame.Minute),
    "30Min": TimeFrame(30, TimeFrame.Minute),
    "1Hour": TimeFrame.Hour,
    "1Day": TimeFrame.Day,
}


class AlpacaMarketDataProvider:
    """Historical bars from Alpaca Markets REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        resolved_key = api_key or os.getenv("APCA_API_KEY_ID", "")
        resolved_secret = secret_key or os.getenv("APCA_API_SECRET_KEY", "")
        resolved_url = base_url or os.getenv(
            "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
        )

        if not resolved_key or not resolved_secret:
            raise ValueError(
                "Alpaca API credentials missing. "
                "Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
            )

        self._api = REST(
            resolved_key,
            resolved_secret,
            base_url=resolved_url,
            api_version="v2",
        )
        self._add_retries()

        logger.info(
            "AlpacaMarketDataProvider initialised (base_url=%s)", resolved_url
        )

    # -- MarketDataProvider interface ---------------------------------------

    def get_bars(self, request: BarRequest) -> pd.DataFrame | None:
        """Fetch OHLCV bars from Alpaca."""
        tf = _ALPACA_TIMEFRAME_MAP.get(request.timeframe)
        if tf is None:
            raise ValueError(
                f"Unsupported timeframe: {request.timeframe!r}. "
                f"Supported: {sorted(_ALPACA_TIMEFRAME_MAP.keys())}"
            )

        start_iso = pd.Timestamp(request.start, tz="US/Eastern").isoformat()
        end_iso = (
            pd.Timestamp(request.end, tz="US/Eastern") + timedelta(days=1)
        ).isoformat()

        try:
            bars = self._api.get_bars(
                request.symbol,
                tf,
                start=start_iso,
                end=end_iso,
                adjustment=request.adjustment,
            ).df

            if bars is None or bars.empty:
                return None

            # Normalize timezone: Alpaca returns UTC timestamps, convert to ET.
            bars = bars.copy()
            if bars.index.tz is None:
                bars.index = bars.index.tz_localize("UTC")
            bars.index = bars.index.tz_convert("US/Eastern")

            return bars

        except Exception:
            logger.exception(
                "Failed to fetch bars for %s (%s, %s → %s)",
                request.symbol,
                request.timeframe,
                request.start,
                request.end,
            )
            return None

    # -- helpers ------------------------------------------------------------

    def _add_retries(self) -> None:
        retry_strategy = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "DELETE", "PATCH"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._api._session.mount("https://", adapter)
        self._api._session.mount("http://", adapter)
