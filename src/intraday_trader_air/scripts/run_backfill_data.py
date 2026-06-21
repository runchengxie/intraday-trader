"""CLI helper for backfilling optional market data fields."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from alpaca_trade_api.rest import REST, TimeFrame
from dotenv import load_dotenv

from intraday_trader_air.configuration import (
    AppConfig,
    ConfigurationError,
    load_app_config,
)
from intraday_trader_air.data_utils import ensure_price_columns, fetch_api_bars
from intraday_trader_air.db_handler import DBHandler
from intraday_trader_air.logging_utils import ensure_directory, setup_logging

_LOGGER = logging.getLogger(__name__)


def _create_alpaca_client() -> REST:
    api_key = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not api_key or not secret_key:
        raise SystemExit(
            "Alpaca credentials missing. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY."
        )

    return REST(api_key, secret_key, base_url=base_url, api_version="v2")


def _parse_symbols(raw: str | None, default: str) -> list[str]:
    if raw:
        parts = [segment.strip().upper() for segment in raw.split(",")]
        return [part for part in parts if part]
    return [default]


def _parse_fields(raw: str | None) -> set[str]:
    if not raw:
        return {"trade_count", "vwap"}
    if raw.strip().lower() == "all":
        return {"trade_count", "vwap"}
    return {segment.strip().lower() for segment in raw.split(",") if segment.strip()}


def _parse_chunk(raw: str) -> pd.Timedelta:
    try:
        delta = pd.to_timedelta(raw)
    except ValueError as exc:  # pragma: no cover - argparse validation
        message = f"Invalid chunk duration '{raw}': {exc}"
        raise argparse.ArgumentTypeError(message) from exc
    if delta <= pd.Timedelta(0):
        raise argparse.ArgumentTypeError("Chunk duration must be positive")
    return delta


def _chunk_range(
    start: pd.Timestamp, end: pd.Timestamp, step: pd.Timedelta
) -> Iterable[Window]:
    current = start
    while current < end:
        chunk_end = min(current + step, end)
        yield current, chunk_end
        current = chunk_end


def _configure_logging(app_config: AppConfig) -> None:
    ensure_directory(app_config.paths.log_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = app_config.paths.log_dir / f"backfill_{timestamp}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    stream_handler = logging.StreamHandler()
    setup_logging(app_config.logging, handlers=[file_handler, stream_handler])
    _LOGGER.info("Log file created: %s", log_file)


@dataclass(slots=True)
class BackfillOptions:
    chunk: pd.Timedelta
    adjustment: str
    required_fields: set[str]
    max_retries: int


Window = tuple[pd.Timestamp, pd.Timestamp]


class BackfillRunner:
    def __init__(self, api: REST, db_handler: DBHandler, options: BackfillOptions):
        self._api = api
        self._db_handler = db_handler
        self._options = options

    def run(self, symbol: str, start: str, end: str) -> None:
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end) + pd.Timedelta(days=1)

        _LOGGER.info(
            "Backfilling %s between %s and %s in %s chunks",
            symbol,
            start,
            end,
            self._options.chunk,
        )

        for window in _chunk_range(start_ts, end_ts, self._options.chunk):
            self._backfill_window(symbol, window)

    def _backfill_window(self, symbol: str, window: Window) -> None:
        start_ts, end_ts = window
        start_str = start_ts.strftime("%Y-%m-%d")
        end_str = (end_ts - timedelta(days=1)).strftime("%Y-%m-%d")

        for attempt in range(1, self._options.max_retries + 1):
            bars = fetch_api_bars(
                self._api,
                symbol,
                TimeFrame.Minute,
                start_str,
                end_str,
                adjustment=self._options.adjustment,
            )
            if bars is None or bars.empty:
                _LOGGER.warning(
                    "No data returned for %s between %s and %s (attempt %s/%s)",
                    symbol,
                    start_str,
                    end_str,
                    attempt,
                    self._options.max_retries,
                )
                continue

            bars = ensure_price_columns(bars)
            missing = [
                field
                for field in self._options.required_fields
                if field not in bars.columns
            ]
            if missing:
                _LOGGER.warning(
                    "Fetched data missing required fields %s for %s (%s to %s)",
                    ", ".join(missing),
                    symbol,
                    start_str,
                    end_str,
                )

            self._db_handler.save_market_data(bars, symbol)
            _LOGGER.info(
                "Stored %d rows for %s between %s and %s",
                len(bars),
                symbol,
                start_str,
                end_str,
            )
            return

        _LOGGER.error(
            "Failed to backfill %s between %s and %s after %s attempts",
            symbol,
            start_str,
            end_str,
            self._options.max_retries,
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill market data columns (trade_count, vwap) from Alpaca"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yml"),
        help="Path to the application configuration file",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        help="Comma separated list of symbols to backfill (defaults to config ticker)",
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Override start date (YYYY-MM-DD). Defaults to data.start_date",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="Override end date (YYYY-MM-DD). Defaults to data.end_date",
    )
    parser.add_argument(
        "--fields",
        type=str,
        help="Comma separated list of fields to enforce (trade_count,vwap or 'all')",
    )
    parser.add_argument(
        "--chunk",
        type=_parse_chunk,
        default="5D",
        help="Duration of each API request window (default: 5D)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Number of retries per chunk when the API returns no data",
    )

    args = parser.parse_args(argv)

    load_dotenv(args.config.with_name(".env"))

    try:
        config = load_app_config(args.config)
    except ConfigurationError as exc:
        raise SystemExit(str(exc))

    _configure_logging(config)

    db_config = config.database
    if db_config is None:
        raise SystemExit("Database configuration is required for backfilling")

    db_handler = DBHandler(
        {
            "backend": db_config.backend,
            "path": db_config.path,
            "host": db_config.host,
            "port": db_config.port,
            "user": db_config.user,
            "password": db_config.password,
            "dbname": db_config.dbname,
        }
    )
    db_handler.initialize_db()

    api = _create_alpaca_client()

    symbols = _parse_symbols(args.symbols, config.data.ticker)
    start = args.start or config.data.start_date
    end = args.end or config.data.end_date
    required_fields = _parse_fields(args.fields)

    options = BackfillOptions(
        chunk=args.chunk,
        adjustment=config.data.adjustment,
        required_fields=required_fields,
        max_retries=args.max_retries,
    )
    runner = BackfillRunner(api, db_handler, options)

    for symbol in symbols:
        runner.run(symbol, start, end)

    _LOGGER.info("Backfill complete for %s", ", ".join(symbols))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
