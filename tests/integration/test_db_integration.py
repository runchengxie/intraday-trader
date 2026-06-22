import logging

# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
from datetime import datetime, timedelta
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from dataclasses import asdict

from dotenv import load_dotenv
from sqlalchemy import inspect, text

from intraday_trader.configuration import load_app_config
from intraday_trader.db_handler import (
    DBHandler,
    PerformanceSnapshot,
    TradeLog,
)

project_root = Path(__file__).resolve().parent.parent.parent

pytestmark = pytest.mark.integration

# --- Test Logging Configuration ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# --- Pytest Fixtures ---


@pytest.fixture(scope="module")
def db_handler():
    """
    Pytest fixture: Initializes the DBHandler and creates the database schema.
    Crucially, it handles tearing down the schema after all tests in the module are complete.
    This ensures a clean environment for every test run.
    """
    handler = None
    try:
        # --- Setup ---
        # Load config to get database connection details
        load_dotenv(dotenv_path=project_root / ".env")
        config = load_app_config(project_root / "config.yml")
        db_config = (
            asdict(config.database) if config.database else {"backend": "sqlite"}
        )

        if db_config.get("backend", "sqlite").lower() == "sqlite":
            tmp_db_path = project_root / "output" / "test_trading.db"
            tmp_db_path.parent.mkdir(parents=True, exist_ok=True)
            if tmp_db_path.exists():
                tmp_db_path.unlink()
            db_config["path"] = str(tmp_db_path)

        handler = DBHandler(db_config)
        logger.info("Initializing test database schema...")
        handler.initialize_db()

        # Yield the handler to the tests
        yield handler

    finally:
        # --- Teardown ---
        if not handler:
            return

        if handler.engine:
            logger.info("Tearing down test database: dropping all tables...")
            with handler.engine.connect() as connection:
                connection.execute(text("DROP TABLE IF EXISTS market_data;"))
                connection.execute(text("DROP TABLE IF EXISTS trade_logs;"))
                connection.execute(text("DROP TABLE IF EXISTS performance_snapshots;"))
                connection.commit()
            logger.info("Test database tables dropped successfully.")
            if (
                handler.backend == "sqlite"
                and handler.sqlite_path
                and handler.sqlite_path.exists()
            ):
                handler.sqlite_path.unlink(missing_ok=True)
        elif handler.backend == "parquet" and handler.storage_dir:
            for artifact in handler.storage_dir.glob("*.parquet"):
                artifact.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def sample_market_data():
    """Creates a standard, reusable Pandas DataFrame for testing market data functions."""
    dates = pd.to_datetime(
        pd.date_range(start="2023-01-01", periods=5, freq="min", tz="America/New_York")
    )
    data = {
        "open": [100.0, 101.0, 102.0, 103.0, 104.0],
        "high": [101.0, 102.0, 103.0, 104.0, 105.0],
        "low": [99.0, 100.0, 101.0, 102.0, 103.0],
        "close": [100.5, 101.5, 102.5, 103.5, 104.5],
        "volume": [1000.0, 1100.0, 1200.0, 1300.0, 1400.0],
    }
    df = pd.DataFrame(data, index=dates)
    df.index.name = "timestamp"
    return df


# --- Integration Tests ---


def test_db_connection_and_initialization(db_handler):
    """
    Tests if the DBHandler can connect to the database and if the tables
    and TimescaleDB hypertables are created successfully.
    """
    logger.info("--- [Test Case: Database Connection and Initialization] ---")
    assert db_handler is not None, "DBHandler instance should be created."
    if db_handler.engine:
        inspector = inspect(db_handler.engine)
        assert inspector.has_table("market_data"), "Table 'market_data' should exist."
        assert inspector.has_table("trade_logs"), "Table 'trade_logs' should exist."
        assert inspector.has_table("performance_snapshots"), (
            "Table 'performance_snapshots' should exist."
        )

        if db_handler.backend in {"postgres", "postgresql"}:
            with db_handler.engine.connect() as conn:
                is_hypertable = conn.execute(
                    text(
                        "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'market_data';"
                    )
                ).scalar_one_or_none()
                assert is_hypertable == 1, "'market_data' should be a hypertable."
    else:
        # Parquet backend: ensure storage directory exists
        assert db_handler.backend == "parquet"
        assert db_handler.storage_dir is not None and db_handler.storage_dir.exists()

    logger.info("Database connection, table, and hypertable initialization verified.")


def test_save_and_get_market_data(db_handler, sample_market_data):
    """
    Tests the core functionality of saving a DataFrame of market data and
    retrieving it, ensuring the data remains identical.
    """
    logger.info("--- [Test Case: Save and Get Market Data] ---")
    symbol = "TEST_SAVE_GET"

    # Act: Save the data, then retrieve it
    logger.info(f"Saving sample market data for symbol: {symbol}")
    db_handler.save_market_data(sample_market_data, symbol)
    retrieved_df = db_handler.get_market_data(symbol, "2023-01-01", "2023-01-02")

    # Assert: The retrieved data should be identical to the saved data
    assert not retrieved_df.empty, "Retrieved data should not be empty."
    pd.testing.assert_frame_equal(
        retrieved_df[sample_market_data.columns], sample_market_data
    )
    logger.info("Save and get market data functionality verified.")


def test_market_data_upsert_logic(db_handler, sample_market_data):
    """
    Tests the UPSERT logic to ensure that saving duplicate or overlapping
    data does not create redundant rows in the database.
    """
    logger.info("--- [Test Case: Market Data Upsert Logic] ---")
    symbol = "TEST_UPSERT"

    # Act 1: First save
    logger.info("Performing first save operation...")
    db_handler.save_market_data(sample_market_data, symbol)
    count_after_first_save = len(
        db_handler.get_market_data(symbol, "2023-01-01", "2023-01-02")
    )
    assert count_after_first_save == 5, "Should have 5 rows after first save."

    # Act 2: Second save with the exact same data
    logger.info("Performing second save with identical data...")
    db_handler.save_market_data(sample_market_data, symbol)
    count_after_second_save = len(
        db_handler.get_market_data(symbol, "2023-01-01", "2023-01-02")
    )

    # Assert
    assert count_after_second_save == 5, (
        "Row count should remain 5, proving ON CONFLICT worked."
    )
    logger.info("Upsert logic verified. No duplicate rows were inserted.")


def test_log_and_get_trade_record(db_handler):
    """Tests logging a single trade record via the ORM and retrieving it."""
    logger.info("--- [Test Case: Log and Get Trade Record] ---")
    now = datetime.utcnow()
    test_order_id = f"test_trade_{int(now.timestamp())}"

    # Arrange: Create an ORM object
    trade = TradeLog(
        timestamp=now,
        order_id=test_order_id,
        symbol="TEST_TRADE",
        side="buy",
        quantity=10,
        price=150.5,
        commission=1.0,
    )

    # Act: Log the trade and then fetch it back
    logger.info(f"Logging a test trade with order_id: {test_order_id}")
    db_handler.log_trade_record(trade)
    trades_df = db_handler.get_trade_logs_as_df(
        now - timedelta(minutes=1), now + timedelta(minutes=1)
    )

    # Assert
    assert not trades_df.empty, "Trade logs DataFrame should not be empty."
    assert test_order_id in trades_df["order_id"].values, (
        "The test trade should be in the retrieved data."
    )
    logger.info("Trade log and retrieval via DataFrame verified.")


def test_log_and_get_performance_snapshot(db_handler):
    """Tests logging a single performance snapshot and retrieving it."""
    logger.info("--- [Test Case: Log and Get Performance Snapshot] ---")
    now = datetime.utcnow()

    # Arrange
    snapshot = PerformanceSnapshot(
        timestamp=now, portfolio_value=105000.75, cash=25000.25
    )

    # Act
    logger.info(f"Logging a test performance snapshot at {now.isoformat()}")
    db_handler.log_performance_snapshot(snapshot)
    snapshots_df = db_handler.get_performance_snapshots_as_df(
        now - timedelta(minutes=1), now + timedelta(minutes=1)
    )

    # Assert
    assert not snapshots_df.empty, (
        "Performance snapshots DataFrame should not be empty."
    )
    assert snapshots_df["portfolio_value"].iloc[0] == pytest.approx(105000.75)
    logger.info("Performance snapshot log and retrieval verified.")
