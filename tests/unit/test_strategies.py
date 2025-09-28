import pytest

pd = pytest.importorskip("pandas")
bt = pytest.importorskip("backtrader")

from intraday_trader_air.strategies import (
    CustomRatioStrategy,
    EMACrossoverStrategy,
    MeanReversionZScoreStrategy,
)


@pytest.fixture
def cerebro_setup():
    """
    Provides a standard, reusable backtrader setup for running a strategy.
    Returns a function that can be called with a strategy, data, and params.
    """
    def _run_strategy(strategy_class, data_df, params={}):
        cerebro = bt.Cerebro(stdstats=False) # Disable standard observers for cleaner output

        # Ensure the DataFrame index is datetime
        data_df.index = pd.to_datetime(data_df.index)

        data_feed = bt.feeds.PandasData(dataname=data_df)
        cerebro.adddata(data_feed)
        cerebro.addstrategy(strategy_class, **params)

        cerebro.broker.set_cash(100000)
        # Use Cheat-on-Close to ensure orders are executed on the same bar a signal is generated
        cerebro.broker.set_coc(True)

        # Add an analyzer to programmatically check the results
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

        # Run the backtest
        results = cerebro.run()
        return results[0] # Return the strategy instance with analyzers

    return _run_strategy

# --- Tests for EMACrossoverStrategy ---

def test_ema_crossover_executes_buy_on_golden_cross_with_high_adx(cerebro_setup):
    """Verify a BUY order is placed on a golden cross when ADX is high."""
    # Arrange: Create data that produces a clear EMA crossover and a high ADX
    # Prices trend strongly upwards to generate a high ADX value.
    prices = [100 + i for i in range(30)]
    data = {
        'open': [p - 1 for p in prices], 'high': [p + 1 for p in prices],
        'low': [p - 2 for p in prices], 'close': prices,
        'volume': [1000] * 30, 'openinterest': [0] * 30
    }
    df = pd.DataFrame(data, index=pd.date_range(start='2023-01-01', periods=30))
    # A low ADX threshold ensures the trade is triggered.
    params = {'ema_short': 5, 'ema_long': 10, 'adx_threshold': 20.0, 'printlog': True}

    # Act
    strat = cerebro_setup(EMACrossoverStrategy, df, params)
    analysis = strat.analyzers.trades.get_analysis()

    # Assert
    assert analysis.total.total > 0
    assert analysis.won.total == 1 # This single trade should be profitable or open
    assert strat.position.size > 0


def test_ema_crossover_ignores_cross_when_adx_is_low(cerebro_setup):
    """Verify NO trade is placed on a crossover if ADX is below the threshold."""
    # Arrange: Create data with a crossover but low volatility (choppy market)
    prices = [100, 101, 100, 101, 102, 101, 102, 103, 102, 101] * 3
    data = {
        'open': prices, 'high': prices, 'low': prices, 'close': prices,
        'volume': [1000] * 30, 'openinterest': [0] * 30
    }
    df = pd.DataFrame(data, index=pd.date_range(start='2023-01-01', periods=30))
    # A high ADX threshold ensures the trade is filtered out.
    params = {'ema_short': 5, 'ema_long': 10, 'adx_threshold': 50.0}

    # Act
    strat = cerebro_setup(EMACrossoverStrategy, df, params)
    analysis = strat.analyzers.trades.get_analysis()

    # Assert
    assert analysis.total.total == 0 # No trades should have been executed
    assert strat.position.size == 0


# --- Tests for MeanReversionZScoreStrategy ---

def test_mean_reversion_executes_buy_on_low_zscore(cerebro_setup):
    """Verify a BUY order is placed when Z-Score drops below the lower threshold."""
    # Arrange: Create data that stays stable, then has a sharp drop.
    prices = [100] * 25 + [90, 91] # Z-score period is 20, so we need >20 stable points
    data = {
        'open': prices, 'high': prices, 'low': prices, 'close': prices,
        'volume': [1000] * 27, 'openinterest': [0] * 27
    }
    df = pd.DataFrame(data, index=pd.date_range(start='2023-01-01', periods=27))
    params = {'zscore_period': 20, 'zscore_lower': -2.0}

    # Act
    strat = cerebro_setup(MeanReversionZScoreStrategy, df, params)
    analysis = strat.analyzers.trades.get_analysis()

    # Assert
    assert analysis.total.total > 0
    assert strat.position.size > 0 # Should have an open long position


def test_mean_reversion_closes_long_position_on_revert(cerebro_setup):
    """Verify a long position is closed when Z-Score reverts to the exit threshold."""
    # Arrange: Data drops to trigger a buy, then reverts to the mean (100).
    prices = [100] * 25 + [90] + [100, 101]
    data = {
        'open': prices, 'high': prices, 'low': prices, 'close': prices,
        'volume': [1000] * 28, 'openinterest': [0] * 28
    }
    df = pd.DataFrame(data, index=pd.date_range(start='2023-01-01', periods=28))
    params = {'zscore_period': 20, 'zscore_lower': -2.0, 'exit_threshold': 0.0}

    # Act
    strat = cerebro_setup(MeanReversionZScoreStrategy, df, params)
    analysis = strat.analyzers.trades.get_analysis()

    # Assert
    assert analysis.total.closed == 1 # One complete round-trip trade
    assert strat.position.size == 0 # Position should be flat at the end


def test_mean_reversion_uses_filtered_price_when_enabled(cerebro_setup):
    """Verify the strategy uses the 'filtered_close' column when configured to do so."""
    # Arrange: 'close' stays flat, but 'filtered_close' drops to trigger a signal.
    base_prices = [100] * 27
    filtered_prices = [100] * 25 + [90, 91]
    data = {
        'open': base_prices, 'high': base_prices, 'low': base_prices, 'close': base_prices,
        'volume': [1000] * 27, 'openinterest': [0] * 27, 'filtered_close': filtered_prices
    }
    df = pd.DataFrame(data, index=pd.date_range(start='2023-01-01', periods=27))
    params = {'use_filtered_price': True, 'zscore_period': 20, 'zscore_lower': -2.0}

    # Act
    strat = cerebro_setup(MeanReversionZScoreStrategy, df, params)
    analysis = strat.analyzers.trades.get_analysis()

    # Assert: A trade should be made based on filtered_close, even though 'close' never moved.
    assert analysis.total.total > 0
    assert strat.position.size > 0


def test_mean_reversion_submits_limit_order(cerebro_setup):
    """Verify that a limit order is submitted when order_type is 'limit'."""
    # Arrange: Same data as the buy signal test.
    prices = [100] * 25 + [90, 91]
    data = {'close': prices, 'open': prices, 'high': prices, 'low': prices, 'volume': [1000]*27, 'openinterest': [0]*27}
    df = pd.DataFrame(data, index=pd.date_range(start='2023-01-01', periods=27))

    # Configure for limit order with a specific offset.
    params = {
        'order_type': 'limit',
        'limit_price_offset_pct': 0.001, # 0.1%
        'zscore_period': 20,
        'zscore_lower': -2.0
    }

    # Act
    strat = cerebro_setup(MeanReversionZScoreStrategy, df, params)

    # Assert
    # The order will be created but might not fill if the price moves away.
    # The key is to check the *last order object* created by the strategy.
    assert strat.order is not None
    assert strat.order.isbuy()
    assert strat.order.exectype == bt.Order.Limit

    # The signal is on the bar with price 90. Expected limit price = 90 * (1 + 0.001) = 90.09
    expected_limit_price = 90 * (1 + 0.001)
    assert strat.order.created.price == pytest.approx(expected_limit_price)


# --- Tests for CustomRatioStrategy ---

def test_custom_ratio_executes_sell_on_high_ratio(cerebro_setup):
    """Verify a SELL order is placed when price/MA ratio exceeds the sell threshold."""
    # Arrange: Data that starts stable, then spikes up.
    prices = [100] * 50 + [103, 104] # 103/100 > 1.02, 104/100.x > 1.02
    data = {'close': prices, 'open': prices, 'high': prices, 'low': prices, 'volume': [1000]*52, 'openinterest': [0]*52}
    df = pd.DataFrame(data, index=pd.date_range(start='2023-01-01', periods=52))
    params = {'long_ma_period': 50, 'sell_threshold': 1.02}

    # Act
    strat = cerebro_setup(CustomRatioStrategy, df, params)
    analysis = strat.analyzers.trades.get_analysis()

    # Assert
    assert analysis.total.total > 0
    assert strat.position.size < 0 # Should have an open short position
