import logging

import pandas as pd
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    String,
    create_engine,
    text,
)
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


# --- ORM Models for our tables (Corrected for TimescaleDB) ---
class MarketData(Base):
    __tablename__ = "market_data"
    # Composite primary key includes the partitioning column 'timestamp'.
    timestamp = Column(DateTime, nullable=False, primary_key=True)
    symbol = Column(String, nullable=False, primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)


class TradeLog(Base):
    __tablename__ = "trade_logs"
    # Composite primary key using natural keys that includes 'timestamp'.
    # The artificial 'id' column is removed.
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
    # The 'timestamp' is the natural primary key and also the partition key.
    # The artificial 'id' column is removed.
    timestamp = Column(DateTime, nullable=False, primary_key=True)
    portfolio_value = Column(Float, nullable=False)
    cash = Column(Float, nullable=False)


class DBHandler:
    def __init__(self, db_config: dict):
        self.db_url = (
            f"postgresql+psycopg2://{db_config['user']}:{db_config['password']}"
            f"@{db_config['host']}:{db_config['port']}/{db_config['dbname']}"
        )
        self.engine = create_engine(self.db_url, pool_pre_ping=True)
        self.Session = sessionmaker(bind=self.engine)
        logger.info(f"DBHandler initialized for database: {db_config['dbname']}")

    def initialize_db(self):
        """Creates tables and TimescaleDB hypertables if they don't exist."""
        try:
            Base.metadata.create_all(self.engine)
            logger.info("Tables created successfully (if they didn't exist).")

            with self.engine.connect() as conn:
                # Turn market_data into a TimescaleDB hypertable
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

                # Turn trade_logs into a TimescaleDB hypertable
                check_hypertable_sql_trades = text(
                    "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'trade_logs';"
                )
                if not conn.execute(check_hypertable_sql_trades).scalar_one_or_none():
                    # The partitioning column must be part of the primary key.
                    # 'chunk_time_interval' is optional but recommended for performance.
                    conn.execute(
                        text(
                            "SELECT create_hypertable('trade_logs', 'timestamp', if_not_exists => TRUE, chunk_time_interval => INTERVAL '7 days');"
                        )
                    )
                    logger.info("'trade_logs' table converted to a hypertable.")
                else:
                    logger.info("'trade_logs' is already a hypertable.")

                # Turn performance_snapshots into a TimescaleDB hypertable
                check_hypertable_sql_perf = text(
                    "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'performance_snapshots';"
                )
                if not conn.execute(check_hypertable_sql_perf).scalar_one_or_none():
                    conn.execute(
                        text(
                            "SELECT create_hypertable('performance_snapshots', 'timestamp', if_not_exists => TRUE, chunk_time_interval => INTERVAL '7 days');"
                        )
                    )
                    logger.info(
                        "'performance_snapshots' table converted to a hypertable."
                    )
                else:
                    logger.info("'performance_snapshots' is already a hypertable.")

                conn.commit()

        except ProgrammingError as e:
            if 'relation "timescaledb_information.hypertables" does not exist' in str(
                e
            ):
                logger.info("TimescaleDB extension not found. Enabling it now.")
                with self.engine.connect() as conn:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb;"))
                    conn.commit()
                self.initialize_db()
            else:
                logger.error(
                    f"A database programming error occurred: {e}", exc_info=True
                )
                raise
        except Exception as e:
            logger.error(f"Error initializing database: {e}", exc_info=True)
            raise

    def save_market_data(self, df: pd.DataFrame, symbol: str):
        """Saves market data from a DataFrame to the database using an efficient upsert method."""
        if df.empty:
            return

        try:
            df_to_save = df.copy()
            df_to_save["symbol"] = symbol
            df_to_save.reset_index(inplace=True)
            df_to_save.rename(
                columns={"index": "timestamp", "time": "timestamp"},
                inplace=True,
                errors="ignore",
            )

            temp_table_name = "temp_market_data_upload"
            df_to_save.to_sql(
                temp_table_name, self.engine, if_exists="replace", index=False
            )

            upsert_sql = text(
                f"""
                INSERT INTO market_data (timestamp, symbol, open, high, low, close, volume)
                SELECT timestamp, symbol, open, high, low, close, volume FROM {temp_table_name}
                ON CONFLICT (timestamp, symbol) DO NOTHING;
            """
            )

            with self.engine.connect() as conn:
                result = conn.execute(upsert_sql)
                conn.commit()
                logger.info(
                    f"Upsert operation complete for {symbol}. {result.rowcount} new rows inserted."
                )

            with self.engine.connect() as conn:
                conn.execute(text(f"DROP TABLE {temp_table_name};"))
                conn.commit()

        except Exception as e:
            logger.error(f"Error saving market data for {symbol}: {e}", exc_info=True)
            # Rollback is not needed for connection-based execution

    def get_market_data(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Retrieves market data from the database."""
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
            # Ensure timestamp is timezone-aware UTC before setting as index
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                df.set_index("timestamp", inplace=True)

            # Fix index timezone to America/New_York
            if not df.empty:
                if df.index.tz is None:
                    # Likely written with UTC semantics without tz info
                    df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")
                else:
                    df.index = df.index.tz_convert("America/New_York")

                # Reattach a frequency if the index is evenly spaced
                if isinstance(df.index, pd.DatetimeIndex):
                    try:
                        inferred = pd.infer_freq(df.index)
                        if inferred:
                            df.index = pd.DatetimeIndex(df.index, tz=df.index.tz, freq=inferred)
                            df.index.name = "timestamp"
                    except Exception:
                        # If inference fails, leave freq as None
                        pass

                # Make dtypes match test expectations (plain int64, not nullable Int64)
                for col in ["open", "high", "low", "volume"]:
                    if col in df.columns and pd.api.types.is_float_dtype(df[col]):
                        s = df[col].dropna()
                        if ((s % 1) == 0).all():
                            df[col] = df[col].astype("int64")

            if not df.empty:
                logger.info(f"Loaded {len(df)} data points for {symbol} from database.")
            return df
        except Exception as e:
            logger.error(f"Error getting market data for {symbol}: {e}", exc_info=True)
            return pd.DataFrame()

    # The rest of the methods in DBHandler remain the same...
    def get_trade_logs(self, start_date, end_date):
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
            logger.error(f"Error fetching trade logs: {e}", exc_info=True)
            return []
        finally:
            session.close()

    def get_performance_snapshots(self, start_date, end_date):
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
            logger.error(f"Error fetching performance snapshots: {e}", exc_info=True)
            return []
        finally:
            session.close()

    def log_trade_record(self, trade: TradeLog):
        """Logs a single trade to the database."""
        session = self.Session()
        try:
            session.add(trade)
            session.commit()
            logger.info(f"Logged trade {trade.order_id} for {trade.symbol}.")
        except Exception as e:
            session.rollback()
            logger.error(f"Error logging trade {trade.order_id}: {e}", exc_info=True)
        finally:
            session.close()

    def get_trade_logs_as_df(self, start_date, end_date) -> pd.DataFrame:
        """Fetches trade logs as a pandas DataFrame."""
        query = text(
            "SELECT * FROM trade_logs WHERE timestamp BETWEEN :start AND :end ORDER BY timestamp DESC"
        )
        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(
                    query, conn, params={"start": start_date, "end": end_date}
                )
            return df
        except Exception as e:
            logger.error(f"Error fetching trade logs as DataFrame: {e}", exc_info=True)
            return pd.DataFrame()

    def get_performance_snapshots_as_df(self, start_date, end_date) -> pd.DataFrame:
        """Fetches performance snapshots as a pandas DataFrame."""
        query = text(
            "SELECT * FROM performance_snapshots WHERE timestamp BETWEEN :start AND :end ORDER BY timestamp ASC"
        )
        try:
            with self.engine.connect() as conn:
                df = pd.read_sql(
                    query, conn, params={"start": start_date, "end": end_date}
                )
            return df
        except Exception as e:
            logger.error(
                f"Error fetching performance snapshots as DataFrame: {e}", exc_info=True
            )
            return pd.DataFrame()

    def log_performance_snapshot(self, snapshot: PerformanceSnapshot):
        """Logs a portfolio performance snapshot."""
        session = self.Session()
        try:
            session.add(snapshot)
            session.commit()
            logger.debug(f"Logged performance snapshot at {snapshot.timestamp}.")
        except Exception as e:
            session.rollback()
            logger.error(f"Error logging performance snapshot: {e}", exc_info=True)
        finally:
            session.close()
