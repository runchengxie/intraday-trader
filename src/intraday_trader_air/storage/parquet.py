"""File-system Parquet storage for market data, trade logs, and performance snapshots."""

from __future__ import annotations

import logging
import typing
from pathlib import Path

import pandas as pd  # type: ignore

logger = logging.getLogger(__name__)


class ParquetStore:
    """Read / write market data, trade logs, and performance snapshots as Parquet files.

    Designed to be used as a drop-in backend by ``DBHandler`` when
    ``backend == "parquet"``, without requiring SQLAlchemy or a running
    database server.
    """

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir
        storage_dir.mkdir(parents=True, exist_ok=True)

    # -- path helpers ----------------------------------------------------

    def _table_path(self, name: str) -> Path:
        return self.storage_dir / f"{name}.parquet"

    def _load_table(self, name: str) -> pd.DataFrame:
        path = self._table_path(name)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)  # pyright: ignore[reportUnknownMemberType]

    def _write_table(self, name: str, df: pd.DataFrame) -> None:
        path = self._table_path(name)
        df.to_parquet(path, index=False)  # pyright: ignore[reportUnknownMemberType]

    # -- market data -----------------------------------------------------

    def save_market_data(self, df: pd.DataFrame) -> None:
        """Persist a DataFrame of market data rows (must contain ``symbol`` column)."""
        path = self._table_path("market_data")
        df = df.reset_index()
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")  # pyright: ignore[reportUnknownMemberType]
        if "trade_count" not in df.columns:
            df["trade_count"] = 0
        if "vwap" not in df.columns:
            df["vwap"] = None
        if path.exists():
            existing = pd.read_parquet(path)  # pyright: ignore[reportUnknownMemberType]
            existing["timestamp"] = pd.to_datetime(  # pyright: ignore[reportUnknownMemberType]
                existing["timestamp"], errors="coerce"
            )
            combined = pd.concat([existing, df], ignore_index=True)
            combined.drop_duplicates(
                subset=["timestamp", "symbol"], keep="last", inplace=True
            )
        else:
            combined = df
        combined.sort_values(["symbol", "timestamp"], inplace=True)  # pyright: ignore[reportUnknownMemberType]
        combined.to_parquet(path, index=False)  # pyright: ignore[reportUnknownMemberType]
        logger.info("Stored %d rows to %s", len(df), path)

    def get_market_data(
        self, symbol: str, start_date: str | None = None, end_date: str | None = None
    ) -> pd.DataFrame:
        """Load market data for *symbol*, optionally filtered by date range."""
        path = self._table_path("market_data")
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path)  # pyright: ignore[reportUnknownMemberType]
        df = typing.cast(pd.DataFrame, df[df["symbol"] == symbol])
        return df

    # -- trade logs ------------------------------------------------------

    def write_trade_record(self, record: dict) -> None:
        """Append a single trade record (dict with standard columns)."""
        df = self._load_table("trade_logs")
        record["timestamp"] = pd.to_datetime(record["timestamp"], utc=True)  # pyright: ignore[reportUnknownMemberType]
        df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
        df.sort_values("timestamp", inplace=True)  # pyright: ignore[reportUnknownMemberType]
        self._write_table("trade_logs", df)
        logger.info(
            "Logged trade %s for %s (filesystem backend).",
            record.get("order_id"),  # pyright: ignore[reportUnknownMemberType]
            record.get("symbol"),  # pyright: ignore[reportUnknownMemberType]
        )

    def read_trade_logs(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return trade logs within the date window as a DataFrame."""
        df = self._load_table("trade_logs")
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")  # pyright: ignore[reportUnknownMemberType]
        mask = (df["timestamp"] >= pd.to_datetime(start_date)) & (  # pyright: ignore[reportUnknownMemberType]
            df["timestamp"] <= pd.to_datetime(end_date)  # pyright: ignore[reportUnknownMemberType]
        )
        return df.loc[mask]

    # -- performance snapshots -------------------------------------------

    def write_snapshot(self, snapshot: dict) -> None:
        """Append a single performance snapshot (dict with timestamp, portfolio_value, cash)."""
        df = self._load_table("performance_snapshots")
        snapshot["timestamp"] = pd.to_datetime(snapshot["timestamp"], utc=True)  # pyright: ignore[reportUnknownMemberType]
        df = pd.concat([df, pd.DataFrame([snapshot])], ignore_index=True)
        df.sort_values("timestamp", inplace=True)  # pyright: ignore[reportUnknownMemberType]
        self._write_table("performance_snapshots", df)
        logger.debug(
            "Logged performance snapshot at %s (filesystem backend).",
            snapshot["timestamp"],
        )

    def read_snapshots(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return performance snapshots within the date window as a DataFrame."""
        df = self._load_table("performance_snapshots")
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")  # pyright: ignore[reportUnknownMemberType]
        mask = (df["timestamp"] >= pd.to_datetime(start_date)) & (  # pyright: ignore[reportUnknownMemberType]
            df["timestamp"] <= pd.to_datetime(end_date)  # pyright: ignore[reportUnknownMemberType]
        )
        return df.loc[mask]
