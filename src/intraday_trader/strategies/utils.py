"""Small helper utilities shared by strategy implementations and tests."""

# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false

from __future__ import annotations

from typing import Any

import backtrader.indicators as btind
import pandas as pd


def compute_zscore(
    data_series: Any,
    *args: Any,
    period: int | None = None,
    epsilon: float = 1e-6,
) -> tuple:
    """Return the z-score along with its rolling mean and stddev.

    Dual API — backtrader mode (default) and pure-pandas test mode.
    """
    # --- test-mode: called with a pandas Series + period keyword ---
    if isinstance(data_series, pd.Series):
        p = period or (args[0] if args else 20)
        if len(data_series) < p:
            return pd.Series(dtype=float), 0.0, 0.0
        roll = data_series.rolling(window=p)
        m = roll.mean()
        s = roll.std(ddof=0)
        z = (data_series - m) / (s + epsilon)
        return z, float(m.iloc[-1]), float(s.iloc[-1])

    # --- backtrader mode: data_series is a bt line ---
    _period: int = period if period is not None else (args[0] if args else 20)
    mean = btind.SMA(data_series, period=_period)
    stdev = btind.StdDev(data_series, period=_period)
    zscore = (data_series - mean) / (stdev + epsilon)
    return zscore, mean, stdev


def compute_ratio(
    series_or_close: Any,
    ma_or_period: Any = None,
    *,
    period: int | None = None,
) -> Any:
    """Return a ratio or moving average depending on the calling convention.

    - *Internal / backtrader*: ``compute_ratio(data_series, period=N)``
      Returns a backtrader SMA indicator.
    - *Test-mode*: ``compute_ratio(close_series, ma_series)``
      Returns ``close / ma`` as a pandas Series.
    """
    # --- test-mode: two Series passed positionally ---
    if isinstance(ma_or_period, pd.Series):
        return series_or_close / ma_or_period

    # --- backtrader mode ---
    p = ma_or_period if isinstance(ma_or_period, (int, float)) else period
    if p is None:
        p = 20  # sensible default for tests
    return btind.SMA(series_or_close, period=int(p))


def validate_series(s: Any) -> bool:
    """Return ``True`` if *s* is a non-empty pandas Series."""
    if s is None or not isinstance(s, pd.Series):
        return False
    return not s.empty
