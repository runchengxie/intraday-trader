import pytest

# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false

pd = pytest.importorskip("pandas")
bt = pytest.importorskip("backtrader")

from intraday_trader_air.backtest.engine import BacktestEngine
from intraday_trader_air.scripts.run_backtests import extend_pandas_data
from intraday_trader_air.strategies import (
    BaseStrategy,
    BuyAndHold,
    EMACrossover,
    MeanReversion,
    RatioStrategy,
)
from intraday_trader_air.strategies.utils import (
    compute_ratio,
    compute_zscore,
    validate_series,
)


@pytest.fixture
def sample_ohlcv_data():
    """Generate a small OHLCV DataFrame for strategy tests."""
    import numpy as np

    dates = pd.date_range("2023-01-03", periods=100, freq="B", tz="America/New_York")
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(100))

    df = pd.DataFrame(
        {
            "open": close + np.random.randn(100) * 0.5,
            "high": close + np.abs(np.random.randn(100)) * 2,
            "low": close - np.abs(np.random.randn(100)) * 2,
            "close": close,
            "volume": np.random.randint(1000, 10000, 100),
        },
        index=dates,
    )
    # Add fake VWAP and trade_count for filtered-close compatibility
    df["vwap"] = (df["high"] + df["low"] + df["close"]) / 3
    df["trade_count"] = np.random.randint(50, 200, 100)
    return df


@pytest.fixture
def bt_datafeed(sample_ohlcv_data):
    """Convert the sample DataFrame to a Backtrader PandasData feed."""
    return extend_pandas_data(sample_ohlcv_data)


@pytest.fixture
def backtest_engine():
    """Return a BacktestEngine with default settings."""
    engine = BacktestEngine(initial_cash=100_000, commission=0.001, slippage=0.001)
    return engine


@pytest.fixture
def run_strategy(backtest_engine, bt_datafeed, request):
    """Run a strategy through the backtest engine and return results + cerebro."""

    def _run(strategy_cls, **params):
        strategy_params = {}
        for key in dir(strategy_cls.params):
            strategy_params[key] = getattr(strategy_cls.params, key)
        strategy_params.update(params)

        backtest_engine.setup(
            data=bt_datafeed,
            strategy=strategy_cls,
            strategy_params=strategy_params,
        )
        results = backtest_engine.run()
        return {
            "results": results,
            "cerebro": backtest_engine.cerebro,
        }

    return _run


# ---------------------------------------------------------------------------
# BaseStrategy tests
# ---------------------------------------------------------------------------


class TestBaseStrategy:
    def test_base_strategy_initializes(self, run_strategy):
        outcome = run_strategy(BaseStrategy)
        assert outcome is not None
        results = outcome["results"]
        assert results["sharpe_ratio"] is not None

    def test_base_strategy_params_override(self, run_strategy):
        outcome = run_strategy(BaseStrategy, printlog=False)
        cerebro = outcome["cerebro"]
        # The strategy instance should have the overridden param
        strategy = cerebro.runningstrats[0]
        assert strategy.p.printlog is False


# ---------------------------------------------------------------------------
# BuyAndHold tests
# ---------------------------------------------------------------------------


class TestBuyAndHold:
    def test_buy_and_hold_initializes(self, run_strategy):
        outcome = run_strategy(BuyAndHold)
        assert outcome is not None
        results = outcome["results"]
        assert results["total_value"] > 0

    def test_buy_and_hold_trades(self, run_strategy):
        outcome = run_strategy(BuyAndHold)
        results = outcome["results"]
        # Buy and hold should have exactly 1 trade (buy once, never sell)
        assert results["total_trades"] == 1

    def test_buy_and_hold_uses_full_capital(self, run_strategy):
        outcome = run_strategy(BuyAndHold, size_pct=0.95)
        results = outcome["results"]
        # Should use ~95% of capital
        cerebro = outcome["cerebro"]
        end_value = cerebro.broker.getvalue()
        assert end_value > 0
        # With 100k capital and 95% allocation, initial position should be large
        assert results["initial_value"] == pytest.approx(100000, rel=0.01)


# ---------------------------------------------------------------------------
# EMACrossover tests
# ---------------------------------------------------------------------------


class TestEMACrossover:
    def test_ema_crossover_initializes(self, run_strategy):
        outcome = run_strategy(EMACrossover)
        assert outcome is not None
        results = outcome["results"]
        assert results["total_trades"] >= 0

    def test_ema_crossover_with_adx_filter(self, run_strategy):
        outcome = run_strategy(
            EMACrossover,
            ema_short=5,
            ema_long=20,
            adx_period=14,
            adx_threshold=20,
        )
        results = outcome["results"]
        assert results["total_trades"] >= 0

    def test_ema_crossover_configurable_periods(self, run_strategy):
        for short, long in [(3, 10), (10, 30), (20, 50)]:
            outcome = run_strategy(
                EMACrossover,
                ema_short=short,
                ema_long=long,
            )
            assert outcome is not None

    def test_ema_crossover_without_adx(self, run_strategy):
        # ADX threshold of 0 disables the filter
        outcome = run_strategy(EMACrossover, adx_threshold=0)
        assert outcome is not None

    def test_ema_crossover_trailing_stop(self, run_strategy):
        outcome = run_strategy(EMACrossover, trailing_stop_pct=0.02)
        assert outcome is not None


# ---------------------------------------------------------------------------
# MeanReversion tests
# ---------------------------------------------------------------------------


class TestMeanReversion:
    def test_mean_reversion_initializes(self, run_strategy):
        outcome = run_strategy(MeanReversion)
        assert outcome is not None

    def test_mean_reversion_zscore_bounds(self, run_strategy):
        outcome = run_strategy(
            MeanReversion,
            zscore_lower=-2.0,
            zscore_upper=2.0,
            exit_threshold=0.5,
        )
        assert outcome is not None

    def test_mean_reversion_order_type(self, run_strategy):
        for order_type in ["market", "limit", "stop"]:
            outcome = run_strategy(MeanReversion, order_type=order_type)
            assert outcome is not None

    def test_mean_reversion_limit_offset(self, run_strategy):
        outcome = run_strategy(
            MeanReversion,
            order_type="limit",
            limit_price_offset_pct=0.01,
        )
        assert outcome is not None

    def test_mean_reversion_filtered_close(self, run_strategy):
        outcome = run_strategy(MeanReversion, use_filtered_price=True)
        assert outcome is not None


# ---------------------------------------------------------------------------
# RatioStrategy tests
# ---------------------------------------------------------------------------


class TestRatioStrategy:
    def test_ratio_strategy_initializes(self, run_strategy):
        outcome = run_strategy(RatioStrategy)
        assert outcome is not None

    def test_ratio_strategy_thresholds(self, run_strategy):
        outcome = run_strategy(
            RatioStrategy,
            buy_threshold=1.02,
            sell_threshold=0.98,
        )
        assert outcome is not None

    def test_ratio_strategy_exit(self, run_strategy):
        outcome = run_strategy(RatioStrategy, exit_threshold=1.0)
        assert outcome is not None


# ---------------------------------------------------------------------------
# Utils tests
# ---------------------------------------------------------------------------


class TestComputeZScore:
    def test_zscore_returns_tuple(self, sample_ohlcv_data):
        prices = sample_ohlcv_data["close"]
        z, mean, std = compute_zscore(prices, period=20)
        assert isinstance(z, pd.Series)
        assert isinstance(mean, float)
        assert isinstance(std, float)

    def test_zscore_near_zero_for_flat_series(self):
        flat = pd.Series([10.0] * 100)
        z, _mean, _std = compute_zscore(flat, period=20)
        # The last value should be near 0 since all values are equal
        assert abs(z.iloc[-1]) < 0.01

    def test_zscore_handles_short_series(self):
        short = pd.Series([1.0, 2.0, 3.0])
        z, mean, std = compute_zscore(short, period=5)
        assert z.empty
        assert mean == 0.0
        assert std == 0.0


class TestComputeRatio:
    def test_compute_ratio(self):
        close = pd.Series([10, 12, 15, 14, 16])
        ma = pd.Series([11, 12, 13, 14, 15])
        result = compute_ratio(close, ma)
        assert isinstance(result, pd.Series)
        assert result.iloc[-1] == pytest.approx(16 / 15)

    def test_compute_ratio_handles_zero(self):
        close = pd.Series([10, 12, 15])
        ma = pd.Series([10, 0, 10])
        result = compute_ratio(close, ma)
        assert not result.isna().all()


class TestValidateSeries:
    def test_valid_series(self):
        s = pd.Series([1.0, 2.0, 3.0])
        assert validate_series(s) is True

    def test_empty_series(self):
        s = pd.Series([], dtype=float)
        assert validate_series(s) is False

    def test_invalid_input(self):
        assert validate_series([1, 2, 3]) is False  # list, not Series
        assert validate_series(None) is False
