"""CLI entry points for running intraday-trader backtests."""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path

import backtrader as bt
import pandas as pd
from alpaca_trade_api.rest import REST, TimeFrame
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from intraday_trader.backtest.engine import BacktestRequest, run_backtest
from intraday_trader.configuration import (
    AppConfig,
    ConfigurationError,
    StrategyConfig,
    load_app_config,
)
from intraday_trader.data_utils import apply_kalman_filter, fetch_historical_data
from intraday_trader.db_handler import DBHandler
from intraday_trader.logging_utils import ensure_directory, setup_logging
from intraday_trader.strategies import REGISTRY
from intraday_trader.strategies.buy_and_hold import BuyAndHoldStrategy

_LOGGER = logging.getLogger(__name__)


@dataclass
class RuntimeContext:
    """Objects shared across CLI subcommands after initialisation."""

    config: AppConfig
    api: REST
    db_handler: DBHandler | None
    price_frame: pd.DataFrame
    log_file: Path


def _build_common_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yml"),
        help="Path to the configuration YAML file",
    )
    parser.add_argument(
        "--strategy",
        dest="strategies",
        action="append",
        help="Restrict the run to one or more strategy keys defined in config.yml",
    )
    parser.add_argument(
        "--no-benchmark",
        action="store_true",
        help="Skip the benchmark run even if enabled in the configuration",
    )
    return parser


def _initialise_runtime(config_path: Path) -> RuntimeContext:
    load_dotenv(dotenv_path=config_path.with_name(".env"))
    try:
        config = load_app_config(config_path)
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc

    ensure_directory(config.paths.output_dir)
    ensure_directory(config.paths.log_dir)
    ensure_directory(config.paths.chart_dir)
    ensure_directory(config.paths.cache_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = config.paths.log_dir / f"trading_log_{timestamp}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    stream_handler = logging.StreamHandler()
    setup_logging(config.logging, handlers=[file_handler, stream_handler])
    _LOGGER.info("Log file created: %s", log_file)

    db_handler = None
    if config.database is not None:
        try:
            db_handler = DBHandler(
                {
                    "backend": config.database.backend,
                    "path": config.database.path,
                    "host": config.database.host,
                    "port": config.database.port,
                    "user": config.database.user,
                    "password": config.database.password,
                    "dbname": config.database.dbname,
                }
            )
            db_handler.initialize_db()
        except Exception as exc:  # pragma: no cover - defensive logging path
            _LOGGER.error(
                "Failed to initialise database handler, continuing without DB: %s", exc
            )
            db_handler = None

    api = _create_alpaca_client()

    price_frame = _load_price_frame(
        config=config,
        api=api,
        db_handler=db_handler,
    )

    return RuntimeContext(
        config=config,
        api=api,
        db_handler=db_handler,
        price_frame=price_frame,
        log_file=log_file,
    )


def _create_alpaca_client() -> REST:
    api_key = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not api_key or not secret_key:
        raise SystemExit(
            "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
        )

    client = REST(api_key, secret_key, base_url=base_url, api_version="v2")
    retry_strategy = Retry(
        total=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    client._session.mount("https://", adapter)
    client._session.mount("http://", adapter)
    _LOGGER.info("Initialised Alpaca client with retries for HTTP errors")
    return client


def _resample_price_data(
    bars: pd.DataFrame, frequency: str, require_full_fields: bool
) -> pd.DataFrame:
    """Resample raw minute data into the configured timeframe.

    The helper gracefully degrades when ``trade_count`` or ``vwap`` columns are
    missing in cached datasets by reconstructing a volume-weighted average price
    from the available OHLC data.  When ``require_full_fields`` is enabled the
    function raises instead of silently backfilling so that operators can run a
    data backfill.
    """

    if bars.empty:
        return bars

    working = bars.copy()

    for column in ("open", "high", "low", "close", "volume"):
        if column not in working.columns:
            raise SystemExit(f"Input data is missing required column '{column}'")

    aggregation: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }

    if "trade_count" in working.columns:
        aggregation["trade_count"] = "sum"
    else:
        _LOGGER.warning(
            "trade_count column missing in source data; leaving values as NA "
            "after resample",
        )

    if "vwap" in working.columns:
        price_basis = working["vwap"].astype(float)
    else:
        _LOGGER.warning(
            "VWAP column missing in source data; approximating using typical price"
        )
        price_basis = (
            working["high"].astype(float)
            + working["low"].astype(float)
            + working["close"].astype(float)
        ) / 3.0

    working["__dollar_volume__"] = price_basis * working["volume"].astype(float)

    resampled = (
        working.resample(frequency, label="right", closed="right")
        .agg({**aggregation, "__dollar_volume__": "sum"})
        .dropna(subset=["open", "high", "low", "close", "volume"], how="any")
    )

    with pd.option_context("mode.use_inf_as_na", True):
        resampled["vwap"] = resampled["__dollar_volume__"] / resampled["volume"]

    resampled.drop(columns="__dollar_volume__", inplace=True)

    if "trade_count" not in resampled.columns:
        resampled["trade_count"] = pd.NA

    if require_full_fields:
        required = ("vwap", "trade_count")
        missing = [col for col in required if resampled[col].isna().all()]
        if missing:
            raise SystemExit(
                "Resampled dataset is missing required columns: "
                + ", ".join(missing)
                + ". Run 'intraday data backfill' to populate them."
            )

    return resampled


def _load_price_frame(
    config: AppConfig,
    api: REST,
    db_handler: DBHandler | None,
) -> pd.DataFrame:
    _LOGGER.info(
        "Fetching %s data between %s and %s (adjustment=%s)",
        config.data.ticker,
        config.data.start_date,
        config.data.end_date,
        config.data.adjustment,
    )

    bars = fetch_historical_data(
        api,
        config.data.ticker,
        TimeFrame.Minute,
        config.data.start_date,
        config.data.end_date,
        cache_dir=str(config.paths.cache_dir),
        db_handler=db_handler,
        adjustment=config.data.adjustment,
    )

    if bars is None or bars.empty:
        raise SystemExit(
            f"Unable to fetch market data for {config.data.ticker}. "
            "Check configuration.",
        )

    _LOGGER.debug("Raw data preview:\n%s", bars.head())

    resampled = _resample_price_data(
        bars,
        config.data.resample_frequency,
        config.data.require_full_fields,
    )

    if resampled.empty:
        raise SystemExit("Resampled dataset is empty; cannot continue backtest")

    resampled["filtered_close"] = apply_kalman_filter(resampled["close"])
    if "openinterest" not in resampled.columns:
        resampled["openinterest"] = 0

    buf = StringIO()
    resampled.info(buf=buf)
    _LOGGER.info("Resampled dataset info:\n%s", buf.getvalue())
    return resampled


def _strategy_selection(
    config: AppConfig, requested: Sequence[str] | None
) -> list[StrategyConfig]:
    if not requested:
        return list(config.strategies)

    known = {strategy.key: strategy for strategy in config.strategies}
    missing = [key for key in requested if key not in known]
    if missing:
        raise SystemExit(f"Unknown strategy keys requested: {', '.join(missing)}")
    return [known[key] for key in requested]


def _instantiate_strategy_class(config: StrategyConfig):
    try:
        return REGISTRY[config.class_name]
    except KeyError as exc:  # pragma: no cover - defensive logging path
        raise SystemExit(
            f"Strategy class '{config.class_name}' not found in registry"
        ) from exc


def _clone_data_feed(price_frame: pd.DataFrame) -> bt.feeds.PandasData:
    return bt.feeds.PandasData(dataname=price_frame.copy())


def _risk_config(app_config: AppConfig) -> dict:
    return (
        dict(app_config.live_trading.get("risk_limits", {}))
        if app_config.live_trading
        else {}
    )


def _run_benchmark(
    runtime: RuntimeContext,
    price_frame: pd.DataFrame,
    skip: bool,
) -> tuple[list[str], dict[str, dict[str, object]], dict[str, bt.Cerebro]]:
    names: list[str] = []
    results: dict[str, dict[str, object]] = {}
    instances: dict[str, bt.Cerebro] = {}

    bench_cfg = runtime.config.benchmark
    if skip or not bench_cfg.enabled:
        return names, results, instances

    _LOGGER.info("===== Benchmark: %s =====", bench_cfg.name)
    cerebro, metrics = run_backtest(
        BacktestRequest(
            strategy_cls=BuyAndHoldStrategy,
            data_feed=_clone_data_feed(price_frame),
            initial_cash=runtime.config.backtest.initial_cash,
            commission=runtime.config.backtest.commission,
            slippage_perc=runtime.config.backtest.slippage_perc,
            risk_config=_risk_config(runtime.config),
            single_run_params={"size_pct": bench_cfg.size_pct},
            strategy_name=bench_cfg.name,
        )
    )

    if bench_cfg.total_return:
        metrics.update(
            _compute_benchmark_total_return(
                runtime, price_frame, metrics, bench_cfg.size_pct
            )
        )

    names.append(bench_cfg.name)
    results[bench_cfg.name] = metrics
    instances[bench_cfg.name] = cerebro
    return names, results, instances


def _fetch_dividends(runtime: RuntimeContext) -> pd.DataFrame:
    if not hasattr(runtime.api, "get_dividends"):
        _LOGGER.debug(
            "Alpaca client has no get_dividends method; skipping dividend fetch"
        )
        return pd.DataFrame()

    try:
        response = runtime.api.get_dividends(
            runtime.config.data.ticker,
            start=runtime.config.data.start_date,
            end=runtime.config.data.end_date,
        )
    except Exception as exc:  # pragma: no cover - network errors are non-deterministic
        _LOGGER.warning("Failed to fetch dividend data: %s", exc)
        return pd.DataFrame()

    if hasattr(response, "df"):
        df = response.df
    else:
        df = pd.DataFrame(response)
    if df.empty:
        return df

    df = df.copy()
    for column in ("ex_date", "payable_date"):
        if column in df.columns:
            df[column] = pd.to_datetime(df[column], errors="coerce")
    return df


def _compute_benchmark_total_return(
    runtime: RuntimeContext,
    price_frame: pd.DataFrame,
    metrics: dict[str, object],
    size_pct: float,
) -> dict[str, object]:
    dividends = _fetch_dividends(runtime)
    if dividends.empty or "cash" not in dividends.columns:
        _LOGGER.info("No dividend data available for total return calculation")
        return {"Total Return Mode": "price"}

    invested_cash = runtime.config.backtest.initial_cash * size_pct
    first_price = price_frame["close"].iloc[0]
    if first_price <= 0:
        return {"Total Return Mode": "price"}

    shares = invested_cash / first_price
    dividend_cash = float(dividends["cash"].fillna(0).sum()) * shares
    final_value = metrics.get("Final Value", invested_cash)
    total_value = final_value + dividend_cash
    total_return = (total_value / invested_cash) - 1 if invested_cash else 0.0
    return {
        "Total Return Mode": "price+dividend",
        "Dividend Cash": dividend_cash,
        "Final Value (Total Return)": total_value,
        "Total Return (%)": total_return * 100,
    }


def _run_strategies(
    runtime: RuntimeContext,
    price_frame: pd.DataFrame,
    strategies: Iterable[StrategyConfig],
) -> tuple[list[str], dict[str, dict[str, object]], dict[str, bt.Cerebro]]:
    names: list[str] = []
    results: dict[str, dict[str, object]] = {}
    instances: dict[str, bt.Cerebro] = {}
    risk_cfg = _risk_config(runtime.config)

    for strategy in strategies:
        _LOGGER.info("===== Strategy: %s =====", strategy.name)
        strategy_cls = _instantiate_strategy_class(strategy)
        cerebro, metrics = run_backtest(
            BacktestRequest(
                strategy_cls=strategy_cls,
                data_feed=_clone_data_feed(price_frame),
                initial_cash=runtime.config.backtest.initial_cash,
                commission=runtime.config.backtest.commission,
                slippage_perc=runtime.config.backtest.slippage_perc,
                risk_config=risk_cfg,
                single_run_params=strategy.params,
                strategy_name=strategy.name,
            )
        )
        names.append(strategy.name)
        results[strategy.name] = metrics
        instances[strategy.name] = cerebro
    return names, results, instances


def _run_optimisation(
    runtime: RuntimeContext,
    price_frame: pd.DataFrame,
    strategies: Iterable[StrategyConfig],
) -> dict[str, pd.DataFrame | None]:
    cpu_count = multiprocessing.cpu_count()
    maxcpus = runtime.config.backtest.max_cpus
    maxcpus = min(maxcpus, cpu_count)
    _LOGGER.info("Using %s CPU cores for optimisation", maxcpus)

    outputs: dict[str, pd.DataFrame | None] = {}
    risk_cfg = _risk_config(runtime.config)

    for strategy in strategies:
        if not strategy.opt_ranges:
            _LOGGER.info(
                "Strategy %s has no opt_ranges defined; skipping optimisation",
                strategy.name,
            )
            outputs[strategy.name] = None
            continue

        _LOGGER.info("===== Optimising: %s =====", strategy.name)
        strategy_cls = _instantiate_strategy_class(strategy)
        opt_params = dict(strategy.params)
        opt_params.update(strategy.opt_ranges)
        result = run_backtest(
            BacktestRequest(
                strategy_cls=strategy_cls,
                data_feed=_clone_data_feed(price_frame),
                initial_cash=runtime.config.backtest.initial_cash,
                commission=runtime.config.backtest.commission,
                slippage_perc=runtime.config.backtest.slippage_perc,
                risk_config=risk_cfg,
                optimize=True,
                opt_param_names=list(strategy.opt_ranges.keys()),
                opt_param_values=opt_params,
                strategy_name=strategy.name,
                maxcpus=maxcpus,
            )
        )
        outputs[strategy.name] = result
    return outputs


def _log_comparison(names: list[str], results: dict[str, dict[str, object]]) -> None:
    if not names:
        _LOGGER.warning("No strategies or benchmarks executed")
        return

    header = f"{'Metric':<25}" + "".join(f" | {name:<30}" for name in names)
    separator = "-" * len(header)
    _LOGGER.info(header)
    _LOGGER.info(separator)

    first = results[names[0]]
    for metric in first:
        row = f"{metric:<25}"
        for name in names:
            val = results.get(name, {}).get(metric, "N/A")
            if isinstance(val, (int, float)):
                cell = f"{val:,.2f}"
            else:
                cell = str(val)
            row += f" | {cell:<30}"
        _LOGGER.info(row)
    _LOGGER.info(separator.replace("-", "="))


def run_command(argv: Sequence[str] | None = None) -> int:
    parser = _build_common_parser("Run one pass of each configured backtest strategy")
    args = parser.parse_args(argv)
    runtime = _initialise_runtime(args.config)

    benchmark_names, benchmark_results, benchmark_instances = _run_benchmark(
        runtime, runtime.price_frame, args.no_benchmark
    )
    strategy_configs = _strategy_selection(runtime.config, args.strategies)
    strategy_names, strategy_results, strategy_instances = _run_strategies(
        runtime, runtime.price_frame, strategy_configs
    )

    names = benchmark_names + strategy_names
    results = benchmark_results | strategy_results
    _log_comparison(names, results)
    _generate_charts(runtime, benchmark_instances | strategy_instances)
    return 0


def optimise_command(argv: Sequence[str] | None = None) -> int:
    parser = _build_common_parser(
        "Run parameter optimisation for configured strategies"
    )
    args = parser.parse_args(argv)
    runtime = _initialise_runtime(args.config)
    strategy_configs = _strategy_selection(runtime.config, args.strategies)
    outputs = _run_optimisation(runtime, runtime.price_frame, strategy_configs)
    for name, df in outputs.items():
        if df is None or getattr(df, "empty", True):
            _LOGGER.warning("No optimisation output for %s", name)
        else:
            _LOGGER.info(
                "Top optimisation results for %s:\n%s",
                name,
                df.sort_values(by="Final Value", ascending=False).head(10).to_string(),
            )
    return 0


def benchmark_command(argv: Sequence[str] | None = None) -> int:
    parser = _build_common_parser("Run only the configured benchmark backtest")
    args = parser.parse_args(argv)
    runtime = _initialise_runtime(args.config)
    names, results, instances = _run_benchmark(
        runtime, runtime.price_frame, args.no_benchmark
    )
    _log_comparison(names, results)
    _generate_charts(runtime, instances)
    return 0


def _generate_charts(runtime: RuntimeContext, instances: dict[str, bt.Cerebro]) -> None:
    charts_dir = runtime.config.paths.chart_dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for name, cerebro in instances.items():
        if cerebro is None:
            continue
        try:
            figs = cerebro.plot(
                style="candlestick",
                barup="green",
                bardown="red",
                returnfig=True,
            )
            if not figs or not figs[0]:
                _LOGGER.warning("Failed to generate chart for %s", name)
                continue
            filename = charts_dir / f"{name.replace(' ', '_')}_{timestamp}.png"
            figs[0][0].savefig(filename, dpi=300, bbox_inches="tight")
            _LOGGER.info("Saved chart: %s", filename)
        except Exception as exc:  # pragma: no cover - plotting is best effort
            _LOGGER.error("Chart generation failed for %s: %s", name, exc)


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - legacy CLI
    """Legacy entry point preserving the old behaviour of sequential tasks."""

    parser = _build_common_parser(
        "Run benchmark, strategies, and optimisation sequentially"
    )
    args = parser.parse_args(argv)
    runtime = _initialise_runtime(args.config)
    strategy_configs = _strategy_selection(runtime.config, args.strategies)

    benchmark_names, benchmark_results, benchmark_instances = _run_benchmark(
        runtime, runtime.price_frame, args.no_benchmark
    )
    strategy_names, strategy_results, strategy_instances = _run_strategies(
        runtime, runtime.price_frame, strategy_configs
    )
    _run_optimisation(runtime, runtime.price_frame, strategy_configs)

    names = benchmark_names + strategy_names
    results = benchmark_results | strategy_results
    _log_comparison(names, results)
    _generate_charts(runtime, benchmark_instances | strategy_instances)
    return 0


def extend_pandas_data(df: pd.DataFrame) -> bt.feeds.PandasData:
    """Convert a DataFrame with OHLCV(+vwap+trade_count) to a Backtrader feed."""
    return bt.feeds.PandasData(dataname=df)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
