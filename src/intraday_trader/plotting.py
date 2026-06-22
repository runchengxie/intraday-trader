"""Plotting utilities for performance visualization."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_equity_vs_benchmark(
    portfolio_values: Iterable[tuple[datetime, float]],
    benchmark_returns: pd.Series | None,
    initial_capital: float,
    *,
    title: str = "Strategy vs Benchmark",
    out_path: str | Path | None = None,
    exposure: pd.Series | None = None,
    buy_markers: pd.Series | None = None,
    sell_markers: pd.Series | None = None,
    show: bool = False,
) -> Path | None:
    """Plot equity curve, benchmark, drawdowns, and optional exposure."""

    df = (
        pd.DataFrame(list(portfolio_values), columns=["ts", "equity"])
        .set_index("ts")
        .sort_index()
    )
    if df.empty:
        return None

    equity_norm = df["equity"] / float(initial_capital)

    bench_norm: pd.Series | None = None
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        bench_curve = (1 + pd.Series(benchmark_returns).dropna()).cumprod()
        bench_curve = bench_curve.reindex(df.index).ffill()
        if bench_curve.notna().any():
            first = bench_curve.dropna().iloc[0]
            bench_norm = bench_curve / first if first != 0 else bench_curve

    def drawdown_of(series: pd.Series) -> pd.Series:
        rollmax = series.cummax()
        return series / rollmax - 1.0

    dd_equity = drawdown_of(equity_norm)
    dd_bench = drawdown_of(bench_norm) if bench_norm is not None else None

    returns = df["equity"].pct_change().dropna()
    if len(returns) > 1:
        risk_free = 0.02
        std = returns.std()
        sharpe = (
            ((returns.mean() - risk_free / 252) / std) * np.sqrt(252)
            if std > 0
            else 0.0
        )
        total_ret = equity_norm.iloc[-1] - 1.0
        years = max(len(returns) / 252.0, 1e-6)
        cagr = (1.0 + total_ret) ** (1.0 / years) - 1.0
        mdd = dd_equity.min()
    else:
        sharpe = 0.0
        cagr = 0.0
        mdd = 0.0
        total_ret = 0.0

    alpha = None
    info_ratio = None
    if bench_norm is not None:
        combined = pd.concat(
            [
                returns.rename("strategy"),
                bench_norm.pct_change().dropna().rename("benchmark"),
            ],
            axis=1,
        ).dropna()
        if not combined.empty:
            excess = combined["strategy"] - combined["benchmark"]
            std_excess = excess.std()
            if std_excess > 0:
                info_ratio = excess.mean() / std_excess * np.sqrt(252)
            alpha = excess.mean() * 252

    fig = plt.figure(figsize=(14, 9))
    gs = fig.add_gridspec(3, 1, height_ratios=[2.2, 1.0, 0.7], hspace=0.25)

    ax_top = fig.add_subplot(gs[0])
    ax_dd = fig.add_subplot(gs[1], sharex=ax_top)
    ax_expo = fig.add_subplot(gs[2], sharex=ax_top)

    ax_top.plot(equity_norm.index, equity_norm, label="Strategy", linewidth=1.6)
    if bench_norm is not None:
        bench_aligned = bench_norm.reindex(equity_norm.index).dropna()
        if not bench_aligned.empty:
            ax_top.plot(
                bench_aligned.index,
                bench_aligned,
                label="Buy & Hold",
                linestyle="--",
                linewidth=1.3,
            )
            common = equity_norm.reindex(bench_aligned.index)
            diff = common - bench_aligned
            ax_top.fill_between(
                bench_aligned.index,
                bench_aligned,
                common,
                where=diff > 0,
                alpha=0.15,
            )

            last_bench = bench_aligned.iloc[-1]
        else:
            last_bench = bench_norm.dropna().iloc[-1]
    else:
        bench_aligned = pd.Series(dtype=float)
        last_bench = None

    if buy_markers is not None and not buy_markers.empty:
        buys = buy_markers.reindex(df.index).dropna()
        ax_top.scatter(buys.index, equity_norm.reindex(buys.index), marker="^", s=25)
    if sell_markers is not None and not sell_markers.empty:
        sells = sell_markers.reindex(df.index).dropna()
        ax_top.scatter(sells.index, equity_norm.reindex(sells.index), marker="v", s=25)

    ax_top.set_ylabel("Cumulative return (×)")
    ax_top.set_title(title)
    ax_top.grid(alpha=0.25)

    last_x = equity_norm.index[-1]
    ax_top.annotate(
        f"{equity_norm.iloc[-1]:.2f}×",
        xy=(last_x, equity_norm.iloc[-1]),
        xytext=(6, 0),
        textcoords="offset points",
        va="center",
    )
    if last_bench is not None:
        ax_top.annotate(
            f"{last_bench:.2f}×",
            xy=(last_x, last_bench),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
        )

    ax_top.legend(ncol=2, frameon=False, loc="upper left")

    ax_dd.fill_between(dd_equity.index, dd_equity, 0, alpha=0.25)
    ax_dd.plot(dd_equity.index, dd_equity, linewidth=1.0)
    if dd_bench is not None:
        ax_dd.plot(
            dd_bench.index,
            dd_bench,
            linewidth=1.0,
            linestyle=":",
            label="B&H DD",
        )
        ax_dd.legend(frameon=False, loc="lower left")
    ax_dd.set_ylabel("Drawdown")
    ax_dd.grid(alpha=0.25)

    if exposure is not None and not exposure.empty:
        exp = exposure.reindex(df.index).ffill().clip(lower=0, upper=1)
        ax_expo.fill_between(exp.index, 0, exp, alpha=0.2)
        ax_expo.plot(exp.index, exp, linewidth=0.8)
        ax_expo.set_ylabel("Exposure")
        ax_expo.set_ylim(0, 1)
    else:
        ax_expo.axis("off")

    locator = mdates.AutoDateLocator(minticks=5, maxticks=10)
    formatter = mdates.ConciseDateFormatter(locator)
    for axis in (ax_top, ax_dd, ax_expo):
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(formatter)

    stat_lines = [
        f"Total: {total_ret * 100:.1f}%",
        f"CAGR: {cagr * 100:.1f}%",
        f"Sharpe: {sharpe:.2f}",
        f"MaxDD: {mdd * 100:.1f}%",
    ]
    if alpha is not None and info_ratio is not None:
        stat_lines.extend(
            [
                f"Alpha: {alpha * 100:.1f}%",
                f"IR: {info_ratio:.2f}",
            ]
        )

    ax_top.text(
        0.99,
        0.02,
        "\n".join(stat_lines),
        transform=ax_top.transAxes,
        ha="right",
        va="bottom",
        fontsize=10,
        bbox=dict(
            boxstyle="round,pad=0.4",
            facecolor="white",
            alpha=0.7,
            edgecolor="none",
        ),
    )

    fig.tight_layout()

    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=160, bbox_inches="tight")
    if show and out_path is None:
        plt.show()
    plt.close(fig)
    return Path(out_path) if out_path else None


def plot_from_analyzer(
    analyzer,
    *,
    out_path: str | Path | None = None,
    title: str | None = None,
    show: bool = False,
):
    """Convenience wrapper to draw charts directly from a performance analyzer."""

    return plot_equity_vs_benchmark(
        analyzer.portfolio_values,
        analyzer.benchmark_returns,
        analyzer.initial_capital,
        title=title or getattr(analyzer, "benchmark_name", "Strategy vs Benchmark"),
        out_path=out_path,
        show=show,
    )
