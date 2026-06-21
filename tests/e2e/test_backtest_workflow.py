1|import pytest
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|
3|bt = pytest.importorskip("backtrader")
4|pd = pytest.importorskip("pandas")
5|
6|from intraday_trader_air.backtest.engine import BacktestRequest, run_backtest
7|from intraday_trader_air.strategies import CustomRatioStrategy
8|
9|
10|def test_full_backtest_run_with_trades():
11|    """
12|    Tests the entire backtest process for a strategy that should execute trades.
13|    This verifies that data loading, strategy execution, and analysis work together.
14|    """
15|    # Create a dataset where the CustomRatioStrategy will definitely trigger
16|    close_prices = [100] * 50 + [
17|        103,
18|        104,
19|        100,
20|    ]  # Exceeds the 1.02 sell threshold, then reverts
21|    data = {
22|        "open": close_prices,
23|        "high": close_prices,
24|        "low": close_prices,
25|        "close": close_prices,
26|        "volume": [1000] * len(close_prices),
27|        "openinterest": [0] * len(close_prices),
28|    }
29|    df = pd.DataFrame(
30|        data,
31|        index=pd.to_datetime(
32|            pd.date_range(start="2023-01-01", periods=len(close_prices))
33|        ),
34|    )
35|    data_feed = bt.feeds.PandasData(dataname=df)
36|
37|    # Use a simple configuration
38|    params = {"long_ma_period": 50, "sell_threshold": 1.02, "exit_threshold": 1.0}
39|
40|    _, analysis_results = run_backtest(
41|        BacktestRequest(
42|            strategy_cls=CustomRatioStrategy,
43|            data_feed=data_feed,
44|            initial_cash=100000,
45|            commission=0.001,
46|            single_run_params=params,
47|            strategy_name="FunctionalTestRatio",
48|        )
49|    )
50|
51|    assert analysis_results is not None
52|    assert "Final Value" in analysis_results
53|    assert analysis_results["Total Trades"] > 0
54|    # In this specific scenario (sell high, cover at the mean), a profit is expected
55|    assert analysis_results["Final Value"] > 100000
56|

