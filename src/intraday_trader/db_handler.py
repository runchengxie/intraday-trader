"""Database handler — unified façade over SQL and Parquet backends.

Delegates Parquet operations to ``storage.ParquetStore`` and SQL operations
to the local SQLAlchemy session machinery.  ORM models are imported from
``storage.models`` and re-exported for backward compatibility.
"""

from __future__ import annotations

import logging
import typing
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from intraday_trader.storage.models import (
    Base,
    MarketData,
    PerformanceSnapshot,
    TradeLog,
)
from intraday_trader.storage.parquet import ParquetStore

logger = logging.getLogger(__name__)


class DBHandler:
    """Unified read / write façade for market data, trade logs, and snapshots.

    Supports three backends selected via ``db_config["backend"]``:

    * ``"sqlite"`` — local SQLite file
    * ``"postgresql"`` — PostgreSQL with optional TimescaleDB hypertables
    * ``"parquet"`` — filesystem-only Parquet files (no database required)
    """

    def __init__(self, db_config: dict) -> None:
        self.backend = db_config.get("backend", "postgresql").lower()
        self.engine = None
        self.Session = None
        self.db_url: str | None = None
        self._parquet: ParquetStore | None = None

        self._sqlite_supports_upsert: bool | None = None
        self._sqlite_version: str | None = None

        if self.backend in {"postgres", "postgresql"}:
            self.db_url = (
                f"postgresql+psycopg2://{db_config['user']}:{db_config['password']}"
                f"@{db_config['host']}:{db_config['port']}/{db_config['dbname']}"
            )
            self.engine = create_engine(self.db_url, pool_pre_ping=True)
            self.Session = sessionmaker(bind=self.engine)
        elif self.backend == "sqlite":
            db_path = db_config.get("path") or db_config.get("dbname") or "trading.db"
            db_path = Path(db_path).expanduser()
            if not db_path.is_absolute():
                db_path = Path.cwd() / db_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.sqlite_path = db_path
            self.storage_dir = db_path.parent  # backward compat
            self.db_url = f"sqlite:///{db_path}"
            self.engine = create_engine(
                self.db_url,
                pool_pre_ping=True,
                future=True,
                connect_args={"check_same_thread": False},
            )
            self.Session = sessionmaker(bind=self.engine)
            self._detect_sqlite_capabilities()
        elif self.backend == "parquet":
            storage_path = db_config.get("path") or Path("output") / "cache"
            storage_path = Path(storage_path).expanduser()
            if not storage_path.is_absolute():
                storage_path = Path.cwd() / storage_path
            self._parquet = ParquetStore(storage_path)
            self.storage_dir = storage_path  # backward compat — tests may read this
            self.sqlite_path = None  # backward compat — tests may read this
        else:
            raise ValueError(f"Unsupported database backend: {self.backend}")

        logger.info(
            "DBHandler initialized for backend '%s'%s",
            self.backend,
            f" at {self.db_url}" if self.db_url else " using filesystem storage",
        )

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def initialize_db(self) -> None:
        """Create tables for SQL backends.  Parquet needs no setup."""
        if self.backend == "parquet":
            logger.info(
                "Parquet backend selected; no database initialization required."
            )
            return

        if not self.engine:
            raise RuntimeError("SQL backend selected but no engine was created.")

        try:
            Base.metadata.create_all(self.engine)
            logger.info("Tables created successfully (if they didn't exist).")

            if self.backend in {"postgres", "postgresql"}:
                self._ensure_timescale_hypertables()

            self._ensure_market_data_columns()
        except ProgrammingError as e:
            if self.backend in {
                "postgres",
                "postgresql",
            } and "timescaledb_information.hypertables" in str(e):
                logger.info("TimescaleDB extension not found. Enabling it now.")
                with self.engine.connect() as conn:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb;"))
                    conn.commit()
                self._ensure_timescale_hypertables()
            else:
                logger.error(
                    "A database programming error occurred: %s", e, exc_info=True
                )
                raise
        except Exception as e:
            logger.error("Error initializing database: %s", e, exc_info=True)
            raise

    def _ensure_timescale_hypertables(self) -> None:
        """Convert SQL tables to Timescale hypertables (PostgreSQL only)."""
        hypertables = {
            "market_data": None,
            "trade_logs": "INTERVAL '7 days'",
            "performance_snapshots": "INTERVAL '7 days'",
        }
        with self.engine.connect() as conn:
            for table, chunk_interval in hypertables.items():
                check = text(
                    "SELECT 1 FROM timescaledb_information.hypertables "
                    f"WHERE hypertable_name = '{table}';"
                )
                if not conn.execute(check).scalar_one_or_none():
                    chunk = (
                        f", chunk_time_interval => {chunk_interval}"
                        if chunk_interval
                        else ""
                    )
                    conn.execute(
                        text(
                            f"SELECT create_hypertable('{table}', 'timestamp', "
                            f"if_not_exists => TRUE{chunk});"
                        )
                    )
                    logger.info("'%s' table converted to a hypertable.", table)
                else:
                    logger.info("'%s' is already a hypertable.", table)
            conn.commit()

    def _ensure_market_data_columns(self) -> None:
        """Add ``trade_count`` and ``vwap`` columns if they don't exist yet."""
        if self.backend == "parquet" or not self.engine:
            return

        index_statement = text(
            "CREATE INDEX IF NOT EXISTS idx_market_data_symbol_ts "
            "ON market_data (symbol, timestamp);"
        )

        with self.engine.begin() as conn:
            if self.backend == "sqlite":
                existing = {
                    row[1]
                    for row in conn.execute(text("PRAGMA table_info('market_data');"))
                }
            else:
                existing = {
                    row[0]
                    for row in conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'market_data';"
                        )
                    )
                }

            for column, sql_type in (("trade_count", "INTEGER"), ("vwap", "REAL")):
                if column not in existing:
                    conn.execute(
                        text(f"ALTER TABLE market_data ADD COLUMN {column} {sql_type};")
                    )
                    logger.info(
                        "Added missing column '%s' to market_data table.", column
                    )

            conn.execute(index_statement)

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def save_market_data(self, df: pd.DataFrame, symbol: str) -> None:
        """Persist market data to the configured backend."""
        if df.empty:
            return

        df_to_save = df.copy()
        df_to_save["symbol"] = symbol
        df_to_save.index.name = "timestamp"

        if self.backend == "parquet":
            assert self._parquet is not None
            self._parquet.save_market_data(df_to_save)
            return

        df_to_save = df_to_save.reset_index()
        df_to_save.rename(
            columns={"index": "timestamp", "time": "timestamp"},
            inplace=True,
            errors="ignore",
        )

        for column, default in ("trade_count", 0), ("vwap", None):
            if column not in df_to_save.columns:
                df_to_save[column] = default

        temp_table_name = "temp_market_data_upload"
        df_to_save.to_sql(
            temp_table_name, self.engine, if_exists="replace", index=False
        )

        rows_inserted = 0
        try:
            rows_inserted = self._execute_market_data_upsert(temp_table_name)
        finally:
            with self.engine.begin() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS {temp_table_name};"))

        logger.info(
            "Upsert operation complete for %s. %d new rows inserted.",
            symbol,
            rows_inserted,
        )

    # -- backward-compat internal helpers (used by tests) ----------------

    def _parquet_table_path(self, name: str) -> Path:
        """Backward-compat: delegate to ParquetStore."""
        if self._parquet is None:
            raise RuntimeError(
                "Parquet backend not configured with a storage directory."
            )
        return self._parquet._table_path(name)

    def _load_parquet_table(self, name: str) -> pd.DataFrame:
        """Backward-compat: delegate to ParquetStore."""
        if self._parquet is None:
            return pd.DataFrame()
        return self._parquet._load_table(name)

    def _write_parquet_table(self, name: str, df: pd.DataFrame) -> None:
        """Backward-compat: delegate to ParquetStore."""
        if self._parquet is not None:
            self._parquet._write_table(name, df)

    def _detect_sqlite_capabilities(self) -> None:
        if self.backend != "sqlite" or not self.engine:
            return

        try:
            with self.engine.connect() as conn:
                version = conn.execute(text("select sqlite_version();")).scalar()
        except Exception as exc:
            logger.warning(
                "Could not determine sqlite_version(): falling back to INSERT OR "
                "REPLACE. Error: %s",
                exc,
            )
            self._sqlite_supports_upsert = False
            return

        if isinstance(version, str):
            self._sqlite_version = version
            parts = [int(p) for p in version.split(".") if p.isdigit()][:3]
            while len(parts) < 3:
                parts.append(0)
            self._sqlite_supports_upsert = tuple(parts) >= (3, 24, 0)
        else:
            self._sqlite_version = str(version)
            self._sqlite_supports_upsert = False

        if not self._sqlite_supports_upsert:
            logger.info(
                "SQLite %s lacks native DO UPDATE support; using INSERT OR REPLACE.",
                self._sqlite_version or "unknown version",
            )

    def _build_market_data_upsert(self, temp_table_name: str):
        if self.backend == "sqlite" and not self._sqlite_supports_upsert:
            return text(
                f"""
                INSERT OR REPLACE INTO market_data
                    (timestamp, symbol, open, high, low, close, volume, trade_count, vwap)
                SELECT timestamp, symbol, open, high, low, close, volume, trade_count, vwap
                FROM {temp_table_name};
                """
            )

        return text(
            f"""
            INSERT INTO market_data
                (timestamp, symbol, open, high, low, close, volume, trade_count, vwap)
            SELECT timestamp, symbol, open, high, low, close, volume, trade_count, vwap
            FROM {temp_table_name}
            ON CONFLICT (timestamp, symbol) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                trade_count = EXCLUDED.trade_count,
                vwap = EXCLUDED.vwap;
            """
        )

    def _execute_market_data_upsert(self, temp_table_name: str) -> int:
        if not self.engine:
            return 0

        upsert_statement = self._build_market_data_upsert(temp_table_name)
        try:
            with self.engine.begin() as conn:
                result = conn.execute(upsert_statement)
        except OperationalError as exc:
            if self._should_retry_sqlite_upsert(exc):
                logger.warning(
                    "SQLite does not support DO UPDATE syntax; retrying with "
                    "INSERT OR REPLACE. Error: %s",
                    exc,
                )
                self._sqlite_supports_upsert = False
                upsert_statement = self._build_market_data_upsert(temp_table_name)
                with self.engine.begin() as conn:
                    result = conn.execute(upsert_statement)
            else:
                raise

        if result.rowcount and result.rowcount > 0:
            return result.rowcount
        return 0

    def _should_retry_sqlite_upsert(self, exc: OperationalError) -> bool:
        if self.backend != "sqlite":
            return False
        if not self._sqlite_supports_upsert:
            return False
        message = str(exc).lower()
        return "syntax error" in message and "do update" in message

    # ------------------------------------------------------------------
    # Market data retrieval
    # ------------------------------------------------------------------

    def get_market_data(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Retrieve market data from the configured backend."""
        if self.backend == "parquet":
            assert self._parquet is not None
            df = self._parquet.get_market_data(symbol)
            return self._postprocess_market_df(
                df, start_date=start_date, end_date=end_date
            )

        query = text(
            """
            SELECT * FROM market_data
            WHERE symbol = :symbol AND timestamp >= :start AND timestamp < :end
            ORDER BY timestamp;
            """
        )
        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(
                    query,
                    conn,
                    params={"symbol": symbol, "start": start_date, "end": end_date},
                )
            return self._postprocess_market_df(df)
        except Exception as e:
            logger.error(
                "Error getting market data for %s: %s", symbol, e, exc_info=True
            )
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Trade logs
    # ------------------------------------------------------------------

    def get_trade_logs(self, start_date, end_date):
        """Fetch trade logs, returned as ORM objects for SQL, list for parquet."""
        if self.backend == "parquet":
            assert self._parquet is not None
            df = self._parquet.read_trade_logs(start_date, end_date)
            if df.empty:
                return []
            return [TradeLog(**row) for row in df.to_dict(orient="records")]

        assert self.Session is not None  # SQL backend
        session = self.Session()
        try:
            query = (
                session.query(TradeLog)
                .filter(
                    TradeLog.timestamp >= start_date, TradeLog.timestamp <= end_date
                )
                .order_by(TradeLog.timestamp)
            )
            return query.all()
        except Exception as e:
            logger.error("Error fetching trade logs: %s", e, exc_info=True)
            return []
        finally:
            session.close()

    def get_trade_logs_as_df(self, start_date, end_date) -> pd.DataFrame:
        """Fetch trade logs as a pandas DataFrame."""
        if self.backend == "parquet":
            assert self._parquet is not None
            return self._parquet.read_trade_logs(start_date, end_date)

        query = text(
            "SELECT * FROM trade_logs WHERE timestamp BETWEEN :start AND :end "
            "ORDER BY timestamp DESC"
        )
        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(
                    query, conn, params={"start": start_date, "end": end_date}
                )
            return df
        except Exception as e:
            logger.error("Error fetching trade logs as DataFrame: %s", e, exc_info=True)
            return pd.DataFrame()

    def log_trade_record(self, trade: TradeLog) -> None:
        """Persist a single trade record."""
        if self.backend == "parquet":
            assert self._parquet is not None
            self._parquet.write_trade_record(
                {
                    "timestamp": trade.timestamp,
                    "order_id": trade.order_id,
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "quantity": trade.quantity,
                    "price": trade.price,
                    "commission": trade.commission,
                    "pnl": trade.pnl,
                }
            )
            return

        assert self.Session is not None  # SQL backend
        session = self.Session()
        try:
            session.add(trade)
            session.commit()
            logger.info("Logged trade %s for %s.", trade.order_id, trade.symbol)
        except Exception as e:
            session.rollback()
            logger.error("Error logging trade %s: %s", trade.order_id, e, exc_info=True)
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Performance snapshots
    # ------------------------------------------------------------------

    def get_performance_snapshots(self, start_date, end_date):
        """Fetch performance snapshots, returned as ORM objects for SQL."""
        if self.backend == "parquet":
            assert self._parquet is not None
            df = self._parquet.read_snapshots(start_date, end_date)
            if df.empty:
                return []
            return [PerformanceSnapshot(**row) for row in df.to_dict(orient="records")]

        assert self.Session is not None  # SQL backend
        session = self.Session()
        try:
            query = (
                session.query(PerformanceSnapshot)
                .filter(
                    PerformanceSnapshot.timestamp >= start_date,
                    PerformanceSnapshot.timestamp <= end_date,
                )
                .order_by(PerformanceSnapshot.timestamp)
            )
            return query.all()
        except Exception as e:
            logger.error("Error fetching performance snapshots: %s", e, exc_info=True)
            return []
        finally:
            session.close()

    def get_performance_snapshots_as_df(self, start_date, end_date) -> pd.DataFrame:
        """Fetch performance snapshots as a pandas DataFrame."""
        if self.backend == "parquet":
            assert self._parquet is not None
            return self._parquet.read_snapshots(start_date, end_date)

        query = text(
            "SELECT * FROM performance_snapshots "
            "WHERE timestamp BETWEEN :start AND :end ORDER BY timestamp ASC"
        )
        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(
                    query, conn, params={"start": start_date, "end": end_date}
                )
            return df
        except Exception as e:
            logger.error(
                "Error fetching performance snapshots as DataFrame: %s",
                e,
                exc_info=True,
            )
            return pd.DataFrame()

    def log_performance_snapshot(self, snapshot: PerformanceSnapshot) -> None:
        """Persist a single performance snapshot."""
        if self.backend == "parquet":
            assert self._parquet is not None
            self._parquet.write_snapshot(
                {
                    "timestamp": snapshot.timestamp,
                    "portfolio_value": snapshot.portfolio_value,
                    "cash": snapshot.cash,
                }
            )
            return

        assert self.Session is not None  # SQL backend
        session = self.Session()
        try:
            session.add(snapshot)
            session.commit()
            logger.debug("Logged performance snapshot at %s.", snapshot.timestamp)
        except Exception as e:
            session.rollback()
            logger.error("Error logging performance snapshot: %s", e, exc_info=True)
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Shared post-processing
    # ------------------------------------------------------------------

    def _postprocess_market_df(
        self,
        df: pd.DataFrame,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Normalize index, timezone, and optional date range filter."""
        if df.empty:
            return df

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df.set_index("timestamp", inplace=True)

        if not df.empty:
            if df.index.tz is None:
                df.index = df.index.tz_localize("America/New_York")
            else:
                df.index = df.index.tz_convert("America/New_York")

            if isinstance(df.index, pd.DatetimeIndex):
                try:
                    inferred = pd.infer_freq(df.index)
                    if inferred:
                        df.index = pd.DatetimeIndex(
                            df.index, tz=df.index.tz, freq=inferred
                        )
                        df.index.name = "timestamp"
                except Exception:
                    pass

        if start_date or end_date:
            start_ts = pd.Timestamp(start_date) if start_date else None
            end_ts = pd.Timestamp(end_date) if end_date else None
            if start_ts is not None and start_ts.tzinfo is None:
                start_ts = start_ts.tz_localize("America/New_York")
            if end_ts is not None and end_ts.tzinfo is None:
                end_ts = end_ts.tz_localize("America/New_York")
            if start_ts:
                df = typing.cast(pd.DataFrame, df[df.index >= start_ts])
            if end_ts:
                df = typing.cast(pd.DataFrame, df[df.index < end_ts])

        if not df.empty:
            logger.info(
                "Loaded %d data points for %s from storage.",
                len(df),
                df.iloc[0].get("symbol", "?"),
            )

        for column in ("trade_count", "vwap"):
            if column not in df.columns:
                df[column] = pd.NA
        return df


# Re-export for backward compatibility — everything that used to live here.
__all__ = [
    "Base",
    "DBHandler",
    "MarketData",
    "PerformanceSnapshot",
    "TradeLog",
]
