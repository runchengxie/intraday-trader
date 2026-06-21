1|import logging
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|from datetime import datetime, timedelta
3|from pathlib import Path
4|
5|import pytest
6|
7|pd = pytest.importorskip("pandas")
8|
9|from dataclasses import asdict
10|
11|from dotenv import load_dotenv
12|from sqlalchemy import inspect, text
13|
14|from intraday_trader_air.configuration import load_app_config
15|from intraday_trader_air.db_handler import (
16|    DBHandler,
17|    PerformanceSnapshot,
18|    TradeLog,
19|)
20|
21|project_root = Path(__file__).resolve().parent.parent.parent
22|
23|pytestmark = pytest.mark.integration
24|
25|# --- Test Logging Configuration ---
26|logging.basicConfig(
27|    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
28|)
29|logger = logging.getLogger(__name__)
30|
31|
32|# --- Pytest Fixtures ---
33|
34|
35|@pytest.fixture(scope="module")
36|def db_handler():
37|    """
38|    Pytest fixture: Initializes the DBHandler and creates the database schema.
39|    Crucially, it handles tearing down the schema after all tests in the module are complete.
40|    This ensures a clean environment for every test run.
41|    """
42|    handler = None
43|    try:
44|        # --- Setup ---
45|        # Load config to get database connection details
46|        load_dotenv(dotenv_path=project_root / ".env")
47|        config = load_app_config(project_root / "config.yml")
48|        db_config = (
49|            asdict(config.database) if config.database else {"backend": "sqlite"}
50|        )
51|
52|        if db_config.get("backend", "sqlite").lower() == "sqlite":
53|            tmp_db_path = project_root / "output" / "test_trading.db"
54|            tmp_db_path.parent.mkdir(parents=True, exist_ok=True)
55|            if tmp_db_path.exists():
56|                tmp_db_path.unlink()
57|            db_config["path"] = str(tmp_db_path)
58|
59|        handler = DBHandler(db_config)
60|        logger.info("Initializing test database schema...")
61|        handler.initialize_db()
62|
63|        # Yield the handler to the tests
64|        yield handler
65|
66|    finally:
67|        # --- Teardown ---
68|        if not handler:
69|            return
70|
71|        if handler.engine:
72|            logger.info("Tearing down test database: dropping all tables...")
73|            with handler.engine.connect() as connection:
74|                connection.execute(text("DROP TABLE IF EXISTS market_data;"))
75|                connection.execute(text("DROP TABLE IF EXISTS trade_logs;"))
76|                connection.execute(text("DROP TABLE IF EXISTS performance_snapshots;"))
77|                connection.commit()
78|            logger.info("Test database tables dropped successfully.")
79|            if (
80|                handler.backend == "sqlite"
81|                and handler.sqlite_path
82|                and handler.sqlite_path.exists()
83|            ):
84|                handler.sqlite_path.unlink(missing_ok=True)
85|        elif handler.backend == "parquet" and handler.storage_dir:
86|            for artifact in handler.storage_dir.glob("*.parquet"):
87|                artifact.unlink(missing_ok=True)
88|
89|
90|@pytest.fixture(scope="module")
91|def sample_market_data():
92|    """Creates a standard, reusable Pandas DataFrame for testing market data functions."""
93|    dates = pd.to_datetime(
94|        pd.date_range(start="2023-01-01", periods=5, freq="min", tz="America/New_York")
95|    )
96|    data = {
97|        "open": [100.0, 101.0, 102.0, 103.0, 104.0],
98|        "high": [101.0, 102.0, 103.0, 104.0, 105.0],
99|        "low": [99.0, 100.0, 101.0, 102.0, 103.0],
100|        "close": [100.5, 101.5, 102.5, 103.5, 104.5],
101|        "volume": [1000.0, 1100.0, 1200.0, 1300.0, 1400.0],
102|    }
103|    df = pd.DataFrame(data, index=dates)
104|    df.index.name = "timestamp"
105|    return df
106|
107|
108|# --- Integration Tests ---
109|
110|
111|def test_db_connection_and_initialization(db_handler):
112|    """
113|    Tests if the DBHandler can connect to the database and if the tables
114|    and TimescaleDB hypertables are created successfully.
115|    """
116|    logger.info("--- [Test Case: Database Connection and Initialization] ---")
117|    assert db_handler is not None, "DBHandler instance should be created."
118|    if db_handler.engine:
119|        inspector = inspect(db_handler.engine)
120|        assert inspector.has_table("market_data"), "Table 'market_data' should exist."
121|        assert inspector.has_table("trade_logs"), "Table 'trade_logs' should exist."
122|        assert inspector.has_table("performance_snapshots"), (
123|            "Table 'performance_snapshots' should exist."
124|        )
125|
126|        if db_handler.backend in {"postgres", "postgresql"}:
127|            with db_handler.engine.connect() as conn:
128|                is_hypertable = conn.execute(
129|                    text(
130|                        "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'market_data';"
131|                    )
132|                ).scalar_one_or_none()
133|                assert is_hypertable == 1, "'market_data' should be a hypertable."
134|    else:
135|        # Parquet backend: ensure storage directory exists
136|        assert db_handler.backend == "parquet"
137|        assert db_handler.storage_dir is not None and db_handler.storage_dir.exists()
138|
139|    logger.info("Database connection, table, and hypertable initialization verified.")
140|
141|
142|def test_save_and_get_market_data(db_handler, sample_market_data):
143|    """
144|    Tests the core functionality of saving a DataFrame of market data and
145|    retrieving it, ensuring the data remains identical.
146|    """
147|    logger.info("--- [Test Case: Save and Get Market Data] ---")
148|    symbol = "TEST_SAVE_GET"
149|
150|    # Act: Save the data, then retrieve it
151|    logger.info(f"Saving sample market data for symbol: {symbol}")
152|    db_handler.save_market_data(sample_market_data, symbol)
153|    retrieved_df = db_handler.get_market_data(symbol, "2023-01-01", "2023-01-02")
154|
155|    # Assert: The retrieved data should be identical to the saved data
156|    assert not retrieved_df.empty, "Retrieved data should not be empty."
157|    pd.testing.assert_frame_equal(
158|        retrieved_df[sample_market_data.columns], sample_market_data
159|    )
160|    logger.info("Save and get market data functionality verified.")
161|
162|
163|def test_market_data_upsert_logic(db_handler, sample_market_data):
164|    """
165|    Tests the UPSERT logic to ensure that saving duplicate or overlapping
166|    data does not create redundant rows in the database.
167|    """
168|    logger.info("--- [Test Case: Market Data Upsert Logic] ---")
169|    symbol = "TEST_UPSERT"
170|
171|    # Act 1: First save
172|    logger.info("Performing first save operation...")
173|    db_handler.save_market_data(sample_market_data, symbol)
174|    count_after_first_save = len(
175|        db_handler.get_market_data(symbol, "2023-01-01", "2023-01-02")
176|    )
177|    assert count_after_first_save == 5, "Should have 5 rows after first save."
178|
179|    # Act 2: Second save with the exact same data
180|    logger.info("Performing second save with identical data...")
181|    db_handler.save_market_data(sample_market_data, symbol)
182|    count_after_second_save = len(
183|        db_handler.get_market_data(symbol, "2023-01-01", "2023-01-02")
184|    )
185|
186|    # Assert
187|    assert count_after_second_save == 5, (
188|        "Row count should remain 5, proving ON CONFLICT worked."
189|    )
190|    logger.info("Upsert logic verified. No duplicate rows were inserted.")
191|
192|
193|def test_log_and_get_trade_record(db_handler):
194|    """Tests logging a single trade record via the ORM and retrieving it."""
195|    logger.info("--- [Test Case: Log and Get Trade Record] ---")
196|    now = datetime.utcnow()
197|    test_order_id = f"test_trade_{int(now.timestamp())}"
198|
199|    # Arrange: Create an ORM object
200|    trade = TradeLog(
201|        timestamp=now,
202|        order_id=test_order_id,
203|        symbol="TEST_TRADE",
204|        side="buy",
205|        quantity=10,
206|        price=150.5,
207|        commission=1.0,
208|    )
209|
210|    # Act: Log the trade and then fetch it back
211|    logger.info(f"Logging a test trade with order_id: {test_order_id}")
212|    db_handler.log_trade_record(trade)
213|    trades_df = db_handler.get_trade_logs_as_df(
214|        now - timedelta(minutes=1), now + timedelta(minutes=1)
215|    )
216|
217|    # Assert
218|    assert not trades_df.empty, "Trade logs DataFrame should not be empty."
219|    assert test_order_id in trades_df["order_id"].values, (
220|        "The test trade should be in the retrieved data."
221|    )
222|    logger.info("Trade log and retrieval via DataFrame verified.")
223|
224|
225|def test_log_and_get_performance_snapshot(db_handler):
226|    """Tests logging a single performance snapshot and retrieving it."""
227|    logger.info("--- [Test Case: Log and Get Performance Snapshot] ---")
228|    now = datetime.utcnow()
229|
230|    # Arrange
231|    snapshot = PerformanceSnapshot(
232|        timestamp=now, portfolio_value=105000.75, cash=25000.25
233|    )
234|
235|    # Act
236|    logger.info(f"Logging a test performance snapshot at {now.isoformat()}")
237|    db_handler.log_performance_snapshot(snapshot)
238|    snapshots_df = db_handler.get_performance_snapshots_as_df(
239|        now - timedelta(minutes=1), now + timedelta(minutes=1)
240|    )
241|
242|    # Assert
243|    assert not snapshots_df.empty, (
244|        "Performance snapshots DataFrame should not be empty."
245|    )
246|    assert snapshots_df["portfolio_value"].iloc[0] == pytest.approx(105000.75)
247|    logger.info("Performance snapshot log and retrieval verified.")
248|

