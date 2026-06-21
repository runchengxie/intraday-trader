"""Small helper utilities shared by strategy implementations."""

# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false

import backtrader.indicators as btind


def compute_zscore(data_series, *, period: int, epsilon: float = 1e-6) -> tuple:
    """Return the z-score along with its rolling mean and stddev indicators."""

    mean = btind.SMA(data_series, period=period)
    stdev = btind.StdDev(data_series, period=period)
    zscore = (data_series - mean) / (stdev + epsilon)
    return zscore, mean, stdev


def compute_ratio(data_series, *, period: int):
    """Return a moving average suitable for price-to-average comparisons."""

    return btind.SMA(data_series, period=period)
