"""Futu / FutuOpenD market data provider.

Uses ``futu-api`` to fetch historical K-line data through a locally
running FutuOpenD gateway.
"""

from __future__ import annotations

import logging
import os

import pandas as pd

from .protocols import BarRequest

logger = logging.getLogger(__name__)

# Futu KLType string → Futu KLType enum (lazy)
# Phase 2 supports minute and daily bars only.
_FUTU_KTYPE_MAP: dict[str, str] = {
    "1Min": "K_1M",
    "5Min": "K_5M",
    "15Min": "K_15M",
    "30Min": "K_30M",
    "1Hour": "K_60M",
    "1Day": "K_DAY",
}


class FutuMarketDataProvider:
    """Historical K-line bars from FutuOpenD."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        market: str | None = None,
    ) -> None:
        from futu import KLType, OpenQuoteContext

        self._host = host or os.getenv("FUTU_HOST", "127.0.0.1")
        self._port = int(port or os.getenv("FUTU_PORT", "11111"))
        self._market = (market or os.getenv("FUTU_MARKET", "HK")).upper()

        self._KLType = KLType
        self._quote_ctx = OpenQuoteContext(host=self._host, port=self._port)

        logger.info(
            "FutuMarketDataProvider initialised (host=%s:%s, market=%s)",
            self._host,
            self._port,
            self._market,
        )

    def __del__(self) -> None:
        try:
            if hasattr(self, "_quote_ctx") and self._quote_ctx:
                self._quote_ctx.close()
        except Exception:
            pass

    # -- MarketDataProvider interface ---------------------------------------

    def get_bars(self, request: BarRequest) -> pd.DataFrame | None:
        """Fetch OHLCV K-lines from FutuOpenD.

        Note: Futu ``request_history_kline`` does not paginate
        transparently for large date ranges in Phase 2.  For spans
        exceeding ~1000 bars the caller should split the request.
        """
        ktype_str = _FUTU_KTYPE_MAP.get(request.timeframe)
        if ktype_str is None:
            raise ValueError(
                f"Unsupported timeframe: {request.timeframe!r}. "
                f"Supported: {sorted(_FUTU_KTYPE_MAP.keys())}"
            )

        ktype = getattr(self._KLType, ktype_str)
        futu_code = _to_futu_code(request.symbol, self._market)

        try:
            ret, data, _ = self._quote_ctx.request_history_kline(
                futu_code,
                ktype=ktype,
                start=request.start,
                end=request.end,
                max_count=1000,
            )
        except Exception:
            logger.exception(
                "request_history_kline failed for %s (%s)",
                futu_code,
                request.timeframe,
            )
            return None

        from futu import RET_OK

        if ret != RET_OK:
            logger.error(
                "request_history_kline error for %s: %s", futu_code, data
            )
            return None

        if data is None or data.empty:
            return None

        # Normalize to standard OHLCV columns with DatetimeIndex.
        df = data.rename(
            columns={
                "time_key": "date",
                "turnover": "volume",  # Futu uses "turnover" for volume
            }
        ).copy()

        # Keep standard columns only.
        keep = ["date", "open", "high", "low", "close", "volume"]
        available = [c for c in keep if c in df.columns]
        df = df[available]

        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()

        return df


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _to_futu_code(symbol: str, market: str) -> str:
    """Format a ticker to the Futu code convention."""
    s = symbol.upper().strip()
    if "." in s:
        return s
    if market == "US":
        return f"US.{s}"
    if market == "HK":
        return f"HK.{s}"
    if market == "CN":
        return f"SH.{s}" if s.startswith("6") else f"SZ.{s}"
    return s
