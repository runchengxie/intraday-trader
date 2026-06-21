1|from __future__ import annotations
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|
3|import pandas as pd
4|import pytest
5|from sqlalchemy import text
6|
7|from intraday_trader_air.db_handler import DBHandler
8|
9|
10|def _parquet_engine_available() -> bool:
11|    for module_name in ("pyarrow", "fastparquet"):
12|        try:
13|            __import__(module_name)
14|            return True
15|        except ImportError:
16|            continue
17|    return False
18|
19|
20|def _sample_dataframe(index):
21|    return pd.DataFrame(
22|        {
23|            "open": [101.0, 102.0],
24|            "high": [102.0, 103.0],
25|            "low": [100.5, 101.5],
26|            "close": [101.5, 102.5],
27|            "volume": [1000, 1200],
28|        },
29|        index=index,
30|    )
31|
32|
33|def test_sqlite_uses_insert_or_replace_when_upsert_unavailable(tmp_path):
34|    db_path = tmp_path / "market.db"
35|    handler = DBHandler({"backend": "sqlite", "path": db_path})
36|    handler.initialize_db()
37|
38|    handler._sqlite_supports_upsert = False
39|
40|    index = pd.date_range(
41|        "2023-01-01 09:30", periods=2, freq="min", tz="America/New_York"
42|    )
43|    df = _sample_dataframe(index)
44|
45|    handler.save_market_data(df, "AAPL")
46|
47|    updated = df.iloc[[0]].copy()
48|    updated.loc[index[0], "close"] = 999.0
49|    handler.save_market_data(updated, "AAPL")
50|
51|    with handler.engine.connect() as conn:
52|        stored = pd.read_sql(text("SELECT * FROM market_data ORDER BY timestamp"), conn)
53|
54|    assert len(stored) == 2
55|    stored["timestamp"] = pd.to_datetime(stored["timestamp"])
56|    stored_sorted = stored.sort_values("timestamp").reset_index(drop=True)
57|    assert pytest.approx(stored_sorted.loc[0, "close"]) == 999.0
58|
59|
60|def test_empty_dataframe_is_ignored_sqlite(tmp_path):
61|    db_path = tmp_path / "market.db"
62|    handler = DBHandler({"backend": "sqlite", "path": db_path})
63|    handler.initialize_db()
64|
65|    handler.save_market_data(pd.DataFrame(), "AAPL")
66|
67|    with handler.engine.connect() as conn:
68|        row_count = conn.execute(text("SELECT COUNT(*) FROM market_data"))
69|        assert row_count.scalar_one() == 0
70|
71|
72|def test_parquet_upsert_deduplicates_rows(tmp_path):
73|    if not _parquet_engine_available():
74|        pytest.skip("pyarrow or fastparquet is required for parquet storage tests")
75|
76|    storage_dir = tmp_path / "parquet"
77|    handler = DBHandler({"backend": "parquet", "path": storage_dir})
78|
79|    index = pd.date_range(
80|        "2023-01-02 09:30", periods=2, freq="min", tz="America/New_York"
81|    )
82|    df = _sample_dataframe(index)
83|
84|    handler.save_market_data(df, "AAPL")
85|
86|    modified = df.copy()
87|    modified.loc[index[0], "close"] = 555.5
88|    handler.save_market_data(modified.iloc[[0]], "AAPL")
89|
90|    parquet_path = handler._parquet_table_path("market_data")
91|    stored = pd.read_parquet(parquet_path)
92|
93|    assert len(stored) == 2
94|    stored_sorted = stored.sort_values("timestamp").reset_index(drop=True)
95|    assert pytest.approx(stored_sorted.loc[0, "close"]) == 555.5
96|
