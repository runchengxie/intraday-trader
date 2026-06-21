from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import text

from intraday_trader_air.db_handler import DBHandler


def _parquet_engine_available() -> bool:
    for module_name in ("pyarrow", "fastparquet"):
        try:
            __import__(module_name)
            return True
        except ImportError:
            continue
    return False


def _sample_dataframe(index):
    return pd.DataFrame(
        {
            "open": [101.0, 102.0],
            "high": [102.0, 103.0],
            "low": [100.5, 101.5],
            "close": [101.5, 102.5],
            "volume": [1000, 1200],
        },
        index=index,
    )


def test_sqlite_uses_insert_or_replace_when_upsert_unavailable(tmp_path):
    db_path = tmp_path / "market.db"
    handler = DBHandler({"backend": "sqlite", "path": db_path})
    handler.initialize_db()

    handler._sqlite_supports_upsert = False

    index = pd.date_range(
        "2023-01-01 09:30", periods=2, freq="min", tz="America/New_York"
    )
    df = _sample_dataframe(index)

    handler.save_market_data(df, "AAPL")

    updated = df.iloc[[0]].copy()
    updated.loc[index[0], "close"] = 999.0
    handler.save_market_data(updated, "AAPL")

    with handler.engine.connect() as conn:
        stored = pd.read_sql(text("SELECT * FROM market_data ORDER BY timestamp"), conn)

    assert len(stored) == 2
    stored["timestamp"] = pd.to_datetime(stored["timestamp"])
    stored_sorted = stored.sort_values("timestamp").reset_index(drop=True)
    assert pytest.approx(stored_sorted.loc[0, "close"]) == 999.0


def test_empty_dataframe_is_ignored_sqlite(tmp_path):
    db_path = tmp_path / "market.db"
    handler = DBHandler({"backend": "sqlite", "path": db_path})
    handler.initialize_db()

    handler.save_market_data(pd.DataFrame(), "AAPL")

    with handler.engine.connect() as conn:
        row_count = conn.execute(text("SELECT COUNT(*) FROM market_data"))
        assert row_count.scalar_one() == 0


def test_parquet_upsert_deduplicates_rows(tmp_path):
    if not _parquet_engine_available():
        pytest.skip("pyarrow or fastparquet is required for parquet storage tests")

    storage_dir = tmp_path / "parquet"
    handler = DBHandler({"backend": "parquet", "path": storage_dir})

    index = pd.date_range(
        "2023-01-02 09:30", periods=2, freq="min", tz="America/New_York"
    )
    df = _sample_dataframe(index)

    handler.save_market_data(df, "AAPL")

    modified = df.copy()
    modified.loc[index[0], "close"] = 555.5
    handler.save_market_data(modified.iloc[[0]], "AAPL")

    parquet_path = handler._parquet_table_path("market_data")
    stored = pd.read_parquet(parquet_path)

    assert len(stored) == 2
    stored_sorted = stored.sort_values("timestamp").reset_index(drop=True)
    assert pytest.approx(stored_sorted.loc[0, "close"]) == 555.5
