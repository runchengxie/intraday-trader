import pytest

np = pytest.importorskip("numpy")

from intraday_trader_air.risk_manager import RiskManager

# --- Pytest Fixtures ---


@pytest.fixture
def risk_config():
    """Provides a standard, reusable risk configuration dictionary for tests."""
    return {
        "var_window": 252,
        "var_confidence_level": 0.05,  # Corresponds to a 95% confidence level
        "price_jump_threshold": 0.10,  # 10% jump
        "volume_spike_threshold": 5.0,  # 5x average volume
        "max_order_participation_ratio": 0.02,  # 2% of recent volume
        "max_bid_ask_spread_pct": 0.005,  # 0.5% spread
        "market_impact_coefficient": 0.5,
        "max_gross_exposure": 1.5,  # 150%
        "max_leverage": 2.0,
    }


@pytest.fixture
def risk_manager(risk_config):
    """Returns a clean RiskManager instance using the standard config."""
    return RiskManager(risk_config)


@pytest.fixture
def populated_risk_manager(risk_manager):
    """Returns a RiskManager instance with a pre-filled history of returns."""
    # Create a predictable series of 50 returns for testing calculations
    np.random.seed(42)  # for reproducibility
    returns = np.random.normal(loc=0.0005, scale=0.01, size=50).tolist()
    # Add a few outliers to make VaR more meaningful
    returns[5] = -0.04  # 4% drop
    returns[15] = 0.035  # 3.5% gain

    for r in returns:
        risk_manager.returns_history.append(r)

    # Also populate price and volume history for other checks
    prices = 100 * np.exp(np.cumsum(returns))
    for p in prices:
        risk_manager.price_history.append(p)
    for _ in range(50):
        risk_manager.volume_history.append(10000)

    return risk_manager


# --- Initialization and State Tests ---


def test_initialization_with_config(risk_manager, risk_config):
    """Verify that the risk manager initializes correctly with a given config."""
    assert risk_manager.var_window == risk_config["var_window"]
    assert risk_manager.config["max_gross_exposure"] == 1.5


def test_update_market_data_populates_history(risk_manager):
    """Verify that calling update_market_data correctly updates internal deques."""
    risk_manager.update_market_data(price=100, volume=1000)
    risk_manager.update_market_data(price=101, volume=1100)

    assert len(risk_manager.price_history) == 2
    assert len(risk_manager.volume_history) == 2
    # Return history only has 1 entry since it needs two prices
    assert len(risk_manager.returns_history) == 1
    # Expected return = (101 - 100) / 100 = 0.01
    assert risk_manager.returns_history[0] == pytest.approx(0.01)


# --- Value at Risk (VaR) Calculation Tests ---


def test_calculate_var_historical(populated_risk_manager):
    """Verify historical VaR calculation against a known dataset."""
    portfolio_value = 100000.0
    result = populated_risk_manager.calculate_var(portfolio_value, method="historical")

    # Manually calculate expected VaR for our known returns data
    returns_array = np.array(list(populated_risk_manager.returns_history))
    expected_var_return = np.percentile(returns_array, 5)  # 5th percentile for 95% VaR
    expected_var_amount = abs(expected_var_return * portfolio_value)

    assert result["method"] == "historical"
    assert result["var"] == pytest.approx(expected_var_amount)
    assert result["var_percentage"] == pytest.approx(abs(expected_var_return))


def test_calculate_var_parametric(populated_risk_manager):
    """Verify parametric VaR calculation against a known dataset."""
    from scipy.stats import norm

    portfolio_value = 100000.0
    result = populated_risk_manager.calculate_var(portfolio_value, method="parametric")

    # Manually calculate expected VaR for our known returns data
    returns_array = np.array(list(populated_risk_manager.returns_history))
    mean = np.mean(returns_array)
    std = np.std(returns_array)
    expected_var_return = norm.ppf(0.05, mean, std)
    expected_var_amount = abs(expected_var_return * portfolio_value)

    assert result["method"] == "parametric"
    assert result["var"] == pytest.approx(expected_var_amount)


def test_calculate_var_insufficient_data(risk_manager):
    """Ensure VaR calculation returns None when there is not enough historical data."""
    result = risk_manager.calculate_var(100000.0)
    assert result["var"] is None


# --- Pre-Trade Check Tests ---


def test_leverage_check_fails_on_exposure(risk_manager):
    """Ensures check fails if a trade exceeds the max gross exposure limit."""
    # Scenario: 1.5 (150%) limit. Portfolio is $100k, gross positions are already $140k.
    # A new trade worth $20k would push exposure to ($140k + $20k) / $100k = 160%.
    passed, warnings = risk_manager.check_leverage_and_exposure(
        proposed_trade_value=20000,
        portfolio_value=100000,
        gross_position_value=140000,
        cash=10000,  # Cash doesn't affect gross exposure calculation
    )
    assert passed is False
    assert "New gross exposure" in warnings[0]


def test_liquidity_check_fails_on_participation(risk_manager):
    """Ensures check fails if order size is too large relative to market volume."""
    # Scenario: 2% participation limit. Order size is 500, but recent average volume is 10,000.
    # Participation ratio would be 500 / 10000 = 5%, which exceeds the limit.
    passed, details = risk_manager.check_liquidity_and_impact(
        order_size=500,
        recent_avg_volume=10000,
        current_volatility=0.015,  # Volatility is needed for impact cost
        bid_ask_spread_pct=0.001,  # Well within limits
    )
    assert passed is False
    assert "Participation ratio" in details["warnings"][0]


def test_liquidity_check_fails_on_spread(risk_manager):
    """Ensures check fails if the bid-ask spread is too wide."""
    # Scenario: 0.5% spread limit. Current spread is 0.7%.
    passed, details = risk_manager.check_liquidity_and_impact(
        order_size=100,
        recent_avg_volume=50000,
        current_volatility=0.01,
        bid_ask_spread_pct=0.007,  # Exceeds the 0.005 limit
    )
    assert passed is False
    assert "Bid-ask spread" in details["warnings"][0]


def test_pre_trade_checks_pass(risk_manager):
    """Verify that checks pass when all parameters are within acceptable limits."""
    # Leverage check
    leverage_passed, leverage_warnings = risk_manager.check_leverage_and_exposure(
        proposed_trade_value=10000,
        portfolio_value=100000,
        gross_position_value=50000,
        cash=50000,
    )
    assert leverage_passed is True
    assert not leverage_warnings

    # Liquidity check
    liquidity_passed, liquidity_details = risk_manager.check_liquidity_and_impact(
        order_size=100,
        recent_avg_volume=50000,
        current_volatility=0.01,
        bid_ask_spread_pct=0.001,
    )
    assert liquidity_passed is True
    assert not liquidity_details["warnings"]


# --- Data Validation and Alert Tests ---


def test_validate_market_data_invalid_price(risk_manager):
    """Verify data validation catches a non-positive price."""
    validation = risk_manager.validate_market_data(price=-5.0, volume=1000)
    assert validation["is_valid"] is False
    assert "Invalid price" in validation["errors"][0]


def test_perform_risk_checks_price_jump(risk_manager):
    """Verify that _perform_risk_checks detects a significant price jump."""
    # Arrange: Add a base price
    risk_manager.price_history.append(100.0)
    risk_manager.returns_history.append(0.0)  # Dummy previous return

    # Act: Trigger a price jump greater than the 10% threshold
    # The return from 100 to 111 is +11%
    alerts = risk_manager.update_market_data(price=111.0, volume=1000)

    # Assert
    assert alerts["price_jump_alert"] is True
    assert "Significant price jump" in alerts["messages"][0]
