import logging
from pathlib import Path
from typing import List, Optional

import pandas as pd
from sqlalchemy import Column, DateTime, Float, String, create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


# --- ORM Models for our tables ---
class MarketData(Base):
    __tablename__ = "market_data"
    timestamp = Column(DateTime, nullable=False, primary_key=True)
    symbol = Column(String, nullable=False, primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)


class TradeLog(Base):
    __tablename__ = "trade_logs"
    timestamp = Column(DateTime, nullable=False, primary_key=True)
    order_id = Column(String, primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    commission = Column(Float)
    pnl = Column(Float)


class PerformanceSnapshot(Base):
    __tablename__ = "performance_snapshots"
    timestamp = Column(DateTime, nullable=False, primary_key=True)
    portfolio_value = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)


class DBHandler:
    def __init__(self, db_config: dict):
        self.backend = db_config.get("backend", "postgresql").lower()
        self.engine = None
        self.Session = None
        self.db_url: Optional[str] = None
        self.storage_dir: Optional[Path] = None
        self.sqlite_path: Optional[Path] = None

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
            self.db_url = f"sqlite:///{db_path}"
            self.engine = create_engine(
                self.db_url,
                pool_pre_ping=True,
                future=True,
                connect_args={"check_same_thread": False},
            )
            self.Session = sessionmaker(bind=self.engine)
        elif self.backend == "parquet":
            storage_path = db_config.get("path") or Path("output") / "cache"
            storage_path = Path(storage_path).expanduser()
            if not storage_path.is_absolute():
                storage_path = Path.cwd() / storage_path
            storage_path.mkdir(parents=True, exist_ok=True)
            self.storage_dir = storage_path
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
    def initialize_db(self):
        """Creates tables for SQL backends. File-based backends need no setup."""
        if self.backend == "parquet":
            logger.info("Parquet backend selected; no database initialization required.")
            return

        if not self.engine:
            raise RuntimeError("SQL backend selected but no engine was created.")

        try:
            Base.metadata.create_all(self.engine)
            logger.info("Tables created successfully (if they didn't exist).")

            if self.backend in {"postgres", "postgresql"}:
                self._ensure_timescale_hypertables()
        except ProgrammingError as e:
            if (
                self.backend in {"postgres", "postgresql"}
                and "timescaledb_information.hypertables" in str(e)
            ):
                logger.info("TimescaleDB extension not found. Enabling it now.")
                with self.engine.connect() as conn:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb;"))
                    conn.commit()
                self._ensure_timescale_hypertables()
            else:
                logger.error("A database programming error occurred: %s", e, exc_info=True)
                raise
        except Exception as e:
            logger.error("Error initializing database: %s", e, exc_info=True)
            raise

    def _ensure_timescale_hypertables(self):
        """Convert SQL tables to Timescale hypertables when using PostgreSQL."""
        with self.engine.connect() as conn:
            check_hypertable_sql = text(
                "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'market_data';"
            )
            if not conn.execute(check_hypertable_sql).scalar_one_or_none():
                conn.execute(
                    text(
                        "SELECT create_hypertable('market_data', 'timestamp', if_not_exists => TRUE);"
                    )
                )
                logger.info("'market_data' table converted to a hypertable.")
            else:
                logger.info("'market_data' is already a hypertable.")

            check_hypertable_sql_trades = text(
                "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'trade_logs';"
            )
            if not conn.execute(check_hypertable_sql_trades).scalar_one_or_none():
                conn.execute(
                    text(
                        "SELECT create_hypertable('trade_logs', 'timestamp', if_not_exists => TRUE, chunk_time_interval => INTERVAL '7 days');"
                    )
                )
                logger.info("'trade_logs' table converted to a hypertable.")
            else:
                logger.info("'trade_logs' is already a hypertable.")

            check_hypertable_sql_perf = text(
                "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'performance_snapshots';"
            )
            if not conn.execute(check_hypertable_sql_perf).scalar_one_or_none():
                conn.execute(
                    text(
                        "SELECT create_hypertable('performance_snapshots', 'timestamp', if_not_exists => TRUE, chunk_time_interval => INTERVAL '7 days');"
                    )
                )
                logger.info("'performance_snapshots' table converted to a hypertable.")
            else:
                logger.info("'performance_snapshots' is already a hypertable.")

            conn.commit()

    # ------------------------------------------------------------------
    # Market data helpers
    # ------------------------------------------------------------------
    def save_market_data(self, df: pd.DataFrame, symbol: str):
        """Saves market data to the configured backend."""
        if df.empty:
            return

        df_to_save = df.copy()
        df_to_save["symbol"] = symbol
        df_to_save.index.name = "timestamp"

        if self.backend == "parquet":
            self._save_market_data_parquet(df_to_save)
            return

        df_to_save = df_to_save.reset_index()
        df_to_save.rename(
            columns={"index": "timestamp", "time": "timestamp"},
            inplace=True,
            errors="ignore",
        )

        temp_table_name = "temp_market_data_upload"
        df_to_save.to_sql(temp_table_name, self.engine, if_exists="replace", index=False)

        if self.backend == "sqlite":
            upsert_statement = text(
                f"""
                INSERT OR IGNORE INTO market_data (timestamp, symbol, open, high, low, close, volume)
                SELECT timestamp, symbol, open, high, low, close, volume FROM {temp_table_name};
            """
            )
        else:
            upsert_statement = text(
                f"""
                INSERT INTO market_data (timestamp, symbol, open, high, low, close, volume)
                SELECT timestamp, symbol, open, high, low, close, volume FROM {temp_table_name}
                ON CONFLICT (timestamp, symbol) DO NOTHING;
            """
            )

        rows_inserted = 0
        try:
            with self.engine.begin() as conn:
                result = conn.execute(upsert_statement)
                if result.rowcount and result.rowcount > 0:
                    rows_inserted = result.rowcount
        finally:
            with self.engine.begin() as conn:
                conn.execute(text(f"DROP TABLE IF EXISTS {temp_table_name};"))

        logger.info(
            "Upsert operation complete for %s. %d new rows inserted.",
            symbol,
            rows_inserted,
        )

    def _save_market_data_parquet(self, df: pd.DataFrame):
        path = self._parquet_table_path("market_data")
        df = df.reset_index()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        if path.exists():
            existing = pd.read_parquet(path)
            existing["timestamp"] = pd.to_datetime(
                existing["timestamp"], utc=True, errors="coerce"
            )
            combined = pd.concat([existing, df], ignore_index=True)
            combined.drop_duplicates(subset=["timestamp", "symbol"], keep="last", inplace=True)
        else:
            combined = df
        combined.sort_values(["symbol", "timestamp"], inplace=True)
        combined.to_parquet(path, index=False)
        logger.info("Stored %d rows to %s", len(df), path)

    def get_market_data(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Retrieves market data from the configured backend."""
        if self.backend == "parquet":
            return self._get_market_data_parquet(symbol, start_date, end_date)

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
            logger.error("Error getting market data for %s: %s", symbol, e, exc_info=True)
            return pd.DataFrame()

    def _get_market_data_parquet(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        path = self._parquet_table_path("market_data")
        if not path.exists():
            return pd.DataFrame()
        df = pd.read_parquet(path)
        df = df[df["symbol"] == symbol]
        return self._postprocess_market_df(df, start_date=start_date, end_date=end_date)

    # ------------------------------------------------------------------
    # Trade log helpers
    # ------------------------------------------------------------------
    def get_trade_logs(self, start_date, end_date):
        if self.backend == "parquet":
            df = self._load_parquet_table("trade_logs")
            if df.empty:
                return []
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            mask = (df["timestamp"] >= pd.to_datetime(start_date)) & (
                df["timestamp"] <= pd.to_datetime(end_date)
            )
            filtered = df.loc[mask]
            return [TradeLog(**row) for row in filtered.to_dict(orient="records")]

        session = self.Session()
        try:
            query = (
                session.query(TradeLog)
                .filter(TradeLog.timestamp >= start_date, TradeLog.timestamp <= end_date)
                .order_by(TradeLog.timestamp)
            )
            return query.all()
        except Exception as e:
            logger.error("Error fetching trade logs: %s", e, exc_info=True)
            return []
        finally:
            session.close()

    def get_performance_snapshots(self, start_date, end_date):
        if self.backend == "parquet":
            df = self._load_parquet_table("performance_snapshots")
            if df.empty:
                return []
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            mask = (df["timestamp"] >= pd.to_datetime(start_date)) & (
                df["timestamp"] <= pd.to_datetime(end_date)
            )
            filtered = df.loc[mask]
            return [
                PerformanceSnapshot(**row) for row in filtered.to_dict(orient="records")
            ]

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

    def log_trade_record(self, trade: TradeLog):
        """Logs a single trade to the backend."""
        if self.backend == "parquet":
            df = self._load_parquet_table("trade_logs")
            trade_dict = {
                "timestamp": pd.to_datetime(trade.timestamp, utc=True),
                "order_id": trade.order_id,
                "symbol": trade.symbol,
                "side": trade.side,
                "quantity": trade.quantity,
                "price": trade.price,
                "commission": trade.commission,
                "pnl": trade.pnl,
            }
            df = pd.concat([df, pd.DataFrame([trade_dict])], ignore_index=True)
            df.sort_values("timestamp", inplace=True)
            self._write_parquet_table("trade_logs", df)
            logger.info("Logged trade %s for %s (filesystem backend).", trade.order_id, trade.symbol)
            return

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

    def get_trade_logs_as_df(self, start_date, end_date) -> pd.DataFrame:
        """Fetches trade logs as a pandas DataFrame."""
        if self.backend == "parquet":
            df = self._load_parquet_table("trade_logs")
            if df.empty:
                return df
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            mask = (df["timestamp"] >= pd.to_datetime(start_date)) & (
                df["timestamp"] <= pd.to_datetime(end_date)
            )
            return df.loc[mask]

        query = text(
            "SELECT * FROM trade_logs WHERE timestamp BETWEEN :start AND :end ORDER BY timestamp DESC"
        )
        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(query, conn, params={"start": start_date, "end": end_date})
            return df
        except Exception as e:
            logger.error("Error fetching trade logs as DataFrame: %s", e, exc_info=True)
            return pd.DataFrame()

    def get_performance_snapshots_as_df(self, start_date, end_date) -> pd.DataFrame:
        """Fetches performance snapshots as a pandas DataFrame."""
        if self.backend == "parquet":
            df = self._load_parquet_table("performance_snapshots")
            if df.empty:
                return df
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            mask = (df["timestamp"] >= pd.to_datetime(start_date)) & (
                df["timestamp"] <= pd.to_datetime(end_date)
            )
            return df.loc[mask]

        query = text(
            "SELECT * FROM performance_snapshots WHERE timestamp BETWEEN :start AND :end ORDER BY timestamp ASC"
        )
        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(query, conn, params={"start": start_date, "end": end_date})
            return df
        except Exception as e:
            logger.error(
                "Error fetching performance snapshots as DataFrame: %s",
                e,
                exc_info=True,
            )
            return pd.DataFrame()

    def log_performance_snapshot(self, snapshot: PerformanceSnapshot):
        """Logs a portfolio performance snapshot."""
        if self.backend == "parquet":
            df = self._load_parquet_table("performance_snapshots")
            snapshot_dict = {
                "timestamp": pd.to_datetime(snapshot.timestamp, utc=True),
                "portfolio_value": snapshot.portfolio_value,
                "cash": snapshot.cash,
            }
            df = pd.concat([df, pd.DataFrame([snapshot_dict])], ignore_index=True)
            df.sort_values("timestamp", inplace=True)
            self._write_parquet_table("performance_snapshots", df)
            logger.debug(
                "Logged performance snapshot at %s (filesystem backend).",
                snapshot.timestamp,
            )
            return

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
    # Shared helpers
    # ------------------------------------------------------------------
    def _postprocess_market_df(
        self,
        df: pd.DataFrame,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        if df.empty:
            return df

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df.set_index("timestamp", inplace=True)

        if not df.empty:
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")
            else:
                df.index = df.index.tz_convert("America/New_York")

            if isinstance(df.index, pd.DatetimeIndex):
                try:
                    inferred = pd.infer_freq(df.index)
                    if inferred:
                        df.index = pd.DatetimeIndex(df.index, tz=df.index.tz, freq=inferred)
                        df.index.name = "timestamp"
                except Exception:
                    pass

            for col in ["open", "high", "low", "volume"]:
                if col in df.columns and pd.api.types.is_float_dtype(df[col]):
                    s = df[col].dropna()
                    if not s.empty and ((s % 1) == 0).all():
                        df[col] = df[col].astype("int64")

        if start_date or end_date:
            start_ts = pd.Timestamp(start_date) if start_date else None
            end_ts = pd.Timestamp(end_date) if end_date else None
            if start_ts is not None and start_ts.tzinfo is None:
                start_ts = start_ts.tz_localize("UTC").tz_convert("America/New_York")
            if end_ts is not None and end_ts.tzinfo is None:
                end_ts = end_ts.tz_localize("UTC").tz_convert("America/New_York")
            if start_ts:
                df = df[df.index >= start_ts]
            if end_ts:
                df = df[df.index < end_ts]

        if not df.empty:
            logger.info("Loaded %d data points for %s from storage.", len(df), df.iloc[0].get("symbol", "?"))
        return df

    def _parquet_table_path(self, name: str) -> Path:
        if not self.storage_dir:
            raise RuntimeError("Parquet backend not configured with a storage directory.")
        return self.storage_dir / f"{name}.parquet"

    def _load_parquet_table(self, name: str) -> pd.DataFrame:
        path = self._parquet_table_path(name)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def _write_parquet_table(self, name: str, df: pd.DataFrame):
        path = self._parquet_table_path(name)
        df.to_parquet(path, index=False)


__all__: List[str] = [
    "DBHandler",
    "MarketData",
    "TradeLog",
    "PerformanceSnapshot",
]
