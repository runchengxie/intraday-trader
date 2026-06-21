"""Benchmark-relative performance calculations."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_relative_performance(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    benchmark_name: str = "Benchmark",
) -> dict:
    """Alpha, beta, tracking error, and information ratio vs benchmark.

    Args:
        portfolio_returns: Strategy daily returns.
        benchmark_returns: Benchmark daily returns (aligned index).
        benchmark_name: Label for the benchmark (used in output dict).

    Returns:
        dict or empty dict if insufficient data.
    """
    if benchmark_returns is None or benchmark_returns.empty:
        return {}

    combined = pd.concat(
        [
            portfolio_returns.rename("portfolio"),
            benchmark_returns.rename("benchmark"),
        ],
        axis=1,
        join="inner",
    ).dropna()

    if combined.empty:
        return {}

    port = combined["portfolio"]
    bench = combined["benchmark"]

    bench_var = np.var(bench)
    beta = np.cov(port, bench)[0, 1] / bench_var if bench_var > 0 else None
    alpha = port.mean() - (beta * bench.mean() if beta is not None else 0.0)
    active_returns = port - bench
    tracking_error = active_returns.std(ddof=1)
    information_ratio = (
        active_returns.mean() / tracking_error if tracking_error > 0 else None
    )

    cumulative_port = (1 + port).cumprod()
    cumulative_bench = (1 + bench).cumprod()

    result = {
        "benchmark_name": benchmark_name,
        "benchmark_total_return": cumulative_bench.iloc[-1] - 1,
        "strategy_total_return": cumulative_port.iloc[-1] - 1,
        "active_return": cumulative_port.iloc[-1] - cumulative_bench.iloc[-1],
        "alpha": alpha,
        "beta": beta,
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
    }

    logger.info(
        "Relative performance vs %s: alpha %.4f, beta %.4f, IR %s",
        benchmark_name,
        alpha if alpha is not None else float("nan"),
        beta if beta is not None else float("nan"),
        f"{information_ratio:.4f}" if information_ratio is not None else "nan",
    )

    return result
