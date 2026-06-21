import json

# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
from datetime import datetime

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from intraday_trader_air.performance_analyzer import (
    PerformanceAnalyzer,
    TradeRecord,
)

# --- Pytest Fixtures ---


@pytest.fixture
def empty_analyzer():
    """Returns a PerformanceAnalyzer instance with no data."""
    return PerformanceAnalyzer(initial_capital=100000.0)


@pytest.fixture
def populated_analyzer():
    """
    Returns a PerformanceAnalyzer instance populated with a realistic
    set of mock trades and portfolio snapshots for thorough testing.
    """
    analyzer = PerformanceAnalyzer(initial_capital=100000.0)

    # Mock trades representing a few winning and losing rounds
    mock_trades = [
        TradeRecord(
            timestamp=datetime(2023, 1, 5, 10, 5),
            symbol="SPY",
            side="buy",
            quantity=50,
            price=380.00,
            commission=1.0,
            order_id="order1",
            slippage=0.02,
            market_impact=0.01,
        ),
        TradeRecord(
            timestamp=datetime(2023, 1, 6, 14, 30),
            symbol="SPY",
            side="sell",
            quantity=50,
            price=385.00,
            commission=1.0,
            order_id="order2",
            slippage=0.03,
            market_impact=0.015,
        ),  # Profit
        TradeRecord(
            timestamp=datetime(2023, 1, 10, 11, 0),
            symbol="AAPL",
            side="buy",
            quantity=25,
            price=130.00,
            commission=1.0,
            order_id="order3",
            slippage=0.01,
            market_impact=0.005,
        ),
        TradeRecord(
            timestamp=datetime(2023, 1, 11, 9, 45),
            symbol="AAPL",
            side="sell",
            quantity=25,
            price=128.00,
            commission=1.0,
            order_id="order4",
            slippage=0.01,
            market_impact=0.005,
        ),  # Loss
    ]
    for trade in mock_trades:
        analyzer.add_trade(trade)

    # Mock portfolio values showing growth and a drawdown
    # Daily snapshots for 5 trading days
    analyzer.portfolio_values = [
        (datetime(2023, 1, 4, 16, 0), 100000.0),
        (datetime(2023, 1, 5, 16, 0), 100150.0),
        (datetime(2023, 1, 6, 16, 0), 100247.0),  # Peak value
        (datetime(2023, 1, 9, 16, 0), 100200.0),
        (datetime(2023, 1, 10, 16, 0), 100100.0),  # Drawdown
        (datetime(2023, 1, 11, 16, 0), 100193.0),
    ]

    # Update market prices needed for concentration risk calculation
    analyzer.latest_market_prices = {"SPY": 390.0, "AAPL": 135.0}

    return analyzer


# --- Unit Tests ---


def test_initialization(empty_analyzer):
    """Verify the analyzer is initialized with the correct starting capital."""
    assert empty_analyzer.initial_capital == 100000.0
    assert empty_analyzer.cash == 100000.0
    assert len(empty_analyzer.trades) == 0
    assert len(empty_analyzer.portfolio_values) == 0


def test_add_trade(empty_analyzer):
    """Verify that adding a trade correctly updates internal state."""
    trade = TradeRecord(
        timestamp=datetime.now(),
        symbol="SPY",
        side="buy",
        quantity=10,
        price=400.0,
        commission=1.0,
        order_id="t1",
    )

    empty_analyzer.add_trade(trade)

    assert len(empty_analyzer.trades) == 1
    assert empty_analyzer.trades[0] == trade
    assert empty_analyzer.positions["SPY"] == 10
    # Expected cash = 100000 - (10 * 400) - 1.0 = 95999.0
    assert empty_analyzer.cash == pytest.approx(95999.0)


def test_calculate_returns(populated_analyzer):
    """Verify the calculation of portfolio percentage returns."""
    returns = populated_analyzer.calculate_returns()
    assert isinstance(returns, pd.Series)
    assert len(returns) == 5  # (6 snapshots - 1)

    # Manual calculation for the first return: (100150.0 / 100000.0) - 1
    expected_first_return = 0.0015
    assert returns.iloc[0] == pytest.approx(expected_first_return)


def test_calculate_risk_metrics_with_data(populated_analyzer):
    """Test the calculation of key risk metrics against known results."""
    metrics = populated_analyzer.calculate_risk_metrics()

    assert metrics is not None
    assert "total_return" in metrics
    assert "sharpe_ratio" in metrics
    assert "max_drawdown" in metrics

    # Final value is 100193.0, initial is 100000.0
    expected_total_return = (100193.0 / 100000.0) - 1
    assert metrics["total_return"] == pytest.approx(expected_total_return)

    # Max drawdown check: Peak was 100247, trough was 100100
    # Expected drawdown = (100100 - 100247) / 100247
    expected_max_drawdown = (100100 - 100247) / 100247
    assert metrics["max_drawdown"] == pytest.approx(expected_max_drawdown)

    # Sharpe ratio is complex to calculate manually here, but we can check if it's a float
    assert isinstance(metrics["sharpe_ratio"], float)


def test_calculate_trading_costs(populated_analyzer):
    """Verify the aggregation of trading costs."""
    costs = populated_analyzer.calculate_trading_costs()

    # Total commissions: 1.0 + 1.0 + 1.0 + 1.0 = 4.0
    assert costs["total_commission"] == pytest.approx(4.0)

    # Total slippage: (0.02*50) + (0.03*50) + (0.01*25) + (0.01*25) = 1.0 + 1.5 + 0.25 + 0.25 = 3.0
    assert costs["total_slippage"] == pytest.approx(3.0)

    # Total market impact: (0.01*50) + (0.015*50) + (0.005*25) + (0.005*25) = 0.5 + 0.75 + 0.125 + 0.125 = 1.5
    assert costs["total_market_impact"] == pytest.approx(1.5)

    # Total cost = 4.0 + 3.0 + 1.5 = 8.5
    assert costs["total_cost"] == pytest.approx(8.5)


def test_calculate_turnover_rate(populated_analyzer):
    """Verify the calculation of portfolio turnover."""
    turnover = populated_analyzer.calculate_turnover_rate(period_days=30)

    # Total traded value: (50*380)+(50*385)+(25*130)+(25*128) = 19000+19250+3250+3200 = 44700
    expected_traded_value = 44700.0
    assert turnover["total_traded_value"] == pytest.approx(expected_traded_value)

    # Avg portfolio value: mean of [100000.0, 100150.0, 100247.0, 100200.0, 100100.0, 100193.0]
    avg_portfolio_value = np.mean(
        [100000.0, 100150.0, 100247.0, 100200.0, 100100.0, 100193.0]
    )
    assert turnover["avg_portfolio_value"] == pytest.approx(avg_portfolio_value)

    # Turnover rate = 44700 / avg_portfolio_value
    expected_turnover = expected_traded_value / avg_portfolio_value
    assert turnover["turnover_rate"] == pytest.approx(expected_turnover)


# --- Edge Case and Empty State Tests ---


def test_risk_metrics_no_data(empty_analyzer):
    """Ensure risk metrics calculation handles no data gracefully."""
    metrics = empty_analyzer.calculate_risk_metrics()
    assert metrics == {}


def test_costs_no_trades(empty_analyzer):
    """Ensure cost calculation handles no trades gracefully."""
    costs = empty_analyzer.calculate_trading_costs()
    assert costs == {}


def test_turnover_no_trades(empty_analyzer):
    """Ensure turnover calculation handles no trades gracefully."""
    turnover = empty_analyzer.calculate_turnover_rate()
    assert turnover["turnover_rate"] == 0.0


def test_returns_insufficient_data(empty_analyzer):
    """Ensure returns calculation handles fewer than two snapshots."""
    empty_analyzer.add_snapshot(datetime.now(), 100000.0)
    returns = empty_analyzer.calculate_returns()
    assert returns.empty is True


# --- Reporting and Plotting Tests ---


def test_generate_performance_report(populated_analyzer):
    """Verify that a JSON report is generated and contains the expected keys."""
    report_str = populated_analyzer.generate_performance_report()
    assert isinstance(report_str, str)

    report_data = json.loads(report_str)
    assert "summary" in report_data
    assert "returns_analysis" in report_data
    assert "trading_costs" in report_data
    assert "turnover_analysis" in report_data
    assert "concentration_risk" in report_data
    assert report_data["summary"]["total_return"] == pytest.approx(0.00193)


def test_plot_performance_charts_runs_without_error(
    populated_analyzer, tmp_path, mocker
):
    """
    Verify that the plotting function executes without errors and creates a file.
    We mock `plt.show()` to prevent plots from displaying during tests.
    """
    # Arrange
    mocker.patch("matplotlib.pyplot.show")  # Prevent plot window from opening
    save_path = tmp_path / "test_performance_chart.png"

    # Act
    populated_analyzer.plot_performance_charts(save_path=str(save_path))

    # Assert
    assert save_path.exists()
    assert save_path.is_file()
