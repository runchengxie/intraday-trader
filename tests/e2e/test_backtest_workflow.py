import pytest

bt = pytest.importorskip("backtrader")
pd = pytest.importorskip("pandas")

from intraday_trader_air.backtest.engine import BacktestRequest, run_backtest
from intraday_trader_air.strategies import CustomRatioStrategy


def test_full_backtest_run_with_trades():
    """
    Tests the entire backtest process for a strategy that should execute trades.
    This verifies that data loading, strategy execution, and analysis work together.
    """
    # Create a dataset where the CustomRatioStrategy will definitely trigger
    close_prices = [100] * 50 + [103, 104, 100] # Exceeds the 1.02 sell threshold, then reverts
    data = {'open': close_prices, 'high': close_prices, 'low': close_prices, 'close': close_prices, 'volume': [1000]*len(close_prices), 'openinterest': [0]*len(close_prices)}
    df = pd.DataFrame(data, index=pd.to_datetime(pd.date_range(start='2023-01-01', periods=len(close_prices))))
    data_feed = bt.feeds.PandasData(dataname=df)

    # Use a simple configuration
    params = {'long_ma_period': 50, 'sell_threshold': 1.02, 'exit_threshold': 1.0}

    cerebro, analysis_results = run_backtest(
        BacktestRequest(
            strategy_cls=CustomRatioStrategy,
            data_feed=data_feed,
            initial_cash=100000,
            commission=0.001,
            single_run_params=params,
            strategy_name="FunctionalTestRatio",
        )
    )

    assert analysis_results is not None
    assert 'Final Value' in analysis_results
    assert analysis_results['Total Trades'] > 0
    # In this specific scenario (sell high, cover at the mean), a profit is expected
    assert analysis_results['Final Value'] > 100000
