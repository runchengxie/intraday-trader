1|import pytest
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|
3|np = pytest.importorskip("numpy")
4|
5|from intraday_trader_air.risk_manager import RiskManager
6|
7|# --- Pytest Fixtures ---
8|
9|
10|@pytest.fixture
11|def risk_config():
12|    """Provides a standard, reusable risk configuration dictionary for tests."""
13|    return {
14|        "var_window": 252,
15|        "var_confidence_level": 0.05,  # Corresponds to a 95% confidence level
16|        "price_jump_threshold": 0.10,  # 10% jump
17|        "volume_spike_threshold": 5.0,  # 5x average volume
18|        "max_order_participation_ratio": 0.02,  # 2% of recent volume
19|        "max_bid_ask_spread_pct": 0.005,  # 0.5% spread
20|        "market_impact_coefficient": 0.5,
21|        "max_gross_exposure": 1.5,  # 150%
22|        "max_leverage": 2.0,
23|    }
24|
25|
26|@pytest.fixture
27|def risk_manager(risk_config):
28|    """Returns a clean RiskManager instance using the standard config."""
29|    return RiskManager(risk_config)
30|
31|
32|@pytest.fixture
33|def populated_risk_manager(risk_manager):
34|    """Returns a RiskManager instance with a pre-filled history of returns."""
35|    # Create a predictable series of 50 returns for testing calculations
36|    np.random.seed(42)  # for reproducibility
37|    returns = np.random.normal(loc=0.0005, scale=0.01, size=50).tolist()
38|    # Add a few outliers to make VaR more meaningful
39|    returns[5] = -0.04  # 4% drop
40|    returns[15] = 0.035  # 3.5% gain
41|
42|    for r in returns:
43|        risk_manager.returns_history.append(r)
44|
45|    # Also populate price and volume history for other checks
46|    prices = 100 * np.exp(np.cumsum(returns))
47|    for p in prices:
48|        risk_manager.price_history.append(p)
49|    for _ in range(50):
50|        risk_manager.volume_history.append(10000)
51|
52|    return risk_manager
53|
54|
55|# --- Initialization and State Tests ---
56|
57|
58|def test_initialization_with_config(risk_manager, risk_config):
59|    """Verify that the risk manager initializes correctly with a given config."""
60|    assert risk_manager.var_window == risk_config["var_window"]
61|    assert risk_manager.config["max_gross_exposure"] == 1.5
62|
63|
64|def test_update_market_data_populates_history(risk_manager):
65|    """Verify that calling update_market_data correctly updates internal deques."""
66|    risk_manager.update_market_data(price=100, volume=1000)
67|    risk_manager.update_market_data(price=101, volume=1100)
68|
69|    assert len(risk_manager.price_history) == 2
70|    assert len(risk_manager.volume_history) == 2
71|    # Return history only has 1 entry since it needs two prices
72|    assert len(risk_manager.returns_history) == 1
73|    # Expected return = (101 - 100) / 100 = 0.01
74|    assert risk_manager.returns_history[0] == pytest.approx(0.01)
75|
76|
77|# --- Value at Risk (VaR) Calculation Tests ---
78|
79|
80|def test_calculate_var_historical(populated_risk_manager):
81|    """Verify historical VaR calculation against a known dataset."""
82|    portfolio_value = 100000.0
83|    result = populated_risk_manager.calculate_var(portfolio_value, method="historical")
84|
85|    # Manually calculate expected VaR for our known returns data
86|    returns_array = np.array(list(populated_risk_manager.returns_history))
87|    expected_var_return = np.percentile(returns_array, 5)  # 5th percentile for 95% VaR
88|    expected_var_amount = abs(expected_var_return * portfolio_value)
89|
90|    assert result["method"] == "historical"
91|    assert result["var"] == pytest.approx(expected_var_amount)
92|    assert result["var_percentage"] == pytest.approx(abs(expected_var_return))
93|
94|
95|def test_calculate_var_parametric(populated_risk_manager):
96|    """Verify parametric VaR calculation against a known dataset."""
97|    from scipy.stats import norm
98|
99|    portfolio_value = 100000.0
100|    result = populated_risk_manager.calculate_var(portfolio_value, method="parametric")
101|
102|    # Manually calculate expected VaR for our known returns data
103|    returns_array = np.array(list(populated_risk_manager.returns_history))
104|    mean = np.mean(returns_array)
105|    std = np.std(returns_array)
106|    expected_var_return = norm.ppf(0.05, mean, std)
107|    expected_var_amount = abs(expected_var_return * portfolio_value)
108|
109|    assert result["method"] == "parametric"
110|    assert result["var"] == pytest.approx(expected_var_amount)
111|
112|
113|def test_calculate_var_insufficient_data(risk_manager):
114|    """Ensure VaR calculation returns None when there is not enough historical data."""
115|    result = risk_manager.calculate_var(100000.0)
116|    assert result["var"] is None
117|
118|
119|# --- Pre-Trade Check Tests ---
120|
121|
122|def test_leverage_check_fails_on_exposure(risk_manager):
123|    """Ensures check fails if a trade exceeds the max gross exposure limit."""
124|    # Scenario: 1.5 (150%) limit. Portfolio is $100k, gross positions are already $140k.
125|    # A new trade worth $20k would push exposure to ($140k + $20k) / $100k = 160%.
126|    passed, warnings = risk_manager.check_leverage_and_exposure(
127|        proposed_trade_value=20000,
128|        portfolio_value=100000,
129|        gross_position_value=140000,
130|        cash=10000,  # Cash doesn't affect gross exposure calculation
131|    )
132|    assert passed is False
133|    assert "New gross exposure" in warnings[0]
134|
135|
136|def test_liquidity_check_fails_on_participation(risk_manager):
137|    """Ensures check fails if order size is too large relative to market volume."""
138|    # Scenario: 2% participation limit. Order size is 500, but recent average volume is 10,000.
139|    # Participation ratio would be 500 / 10000 = 5%, which exceeds the limit.
140|    passed, details = risk_manager.check_liquidity_and_impact(
141|        order_size=500,
142|        recent_avg_volume=10000,
143|        current_volatility=0.015,  # Volatility is needed for impact cost
144|        bid_ask_spread_pct=0.001,  # Well within limits
145|    )
146|    assert passed is False
147|    assert "Participation ratio" in details["warnings"][0]
148|
149|
150|def test_liquidity_check_fails_on_spread(risk_manager):
151|    """Ensures check fails if the bid-ask spread is too wide."""
152|    # Scenario: 0.5% spread limit. Current spread is 0.7%.
153|    passed, details = risk_manager.check_liquidity_and_impact(
154|        order_size=100,
155|        recent_avg_volume=50000,
156|        current_volatility=0.01,
157|        bid_ask_spread_pct=0.007,  # Exceeds the 0.005 limit
158|    )
159|    assert passed is False
160|    assert "Bid-ask spread" in details["warnings"][0]
161|
162|
163|def test_pre_trade_checks_pass(risk_manager):
164|    """Verify that checks pass when all parameters are within acceptable limits."""
165|    # Leverage check
166|    leverage_passed, leverage_warnings = risk_manager.check_leverage_and_exposure(
167|        proposed_trade_value=10000,
168|        portfolio_value=100000,
169|        gross_position_value=50000,
170|        cash=50000,
171|    )
172|    assert leverage_passed is True
173|    assert not leverage_warnings
174|
175|    # Liquidity check
176|    liquidity_passed, liquidity_details = risk_manager.check_liquidity_and_impact(
177|        order_size=100,
178|        recent_avg_volume=50000,
179|        current_volatility=0.01,
180|        bid_ask_spread_pct=0.001,
181|    )
182|    assert liquidity_passed is True
183|    assert not liquidity_details["warnings"]
184|
185|
186|# --- Data Validation and Alert Tests ---
187|
188|
189|def test_validate_market_data_invalid_price(risk_manager):
190|    """Verify data validation catches a non-positive price."""
191|    validation = risk_manager.validate_market_data(price=-5.0, volume=1000)
192|    assert validation["is_valid"] is False
193|    assert "Invalid price" in validation["errors"][0]
194|
195|
196|def test_perform_risk_checks_price_jump(risk_manager):
197|    """Verify that _perform_risk_checks detects a significant price jump."""
198|    # Arrange: Add a base price
199|    risk_manager.price_history.append(100.0)
200|    risk_manager.returns_history.append(0.0)  # Dummy previous return
201|
202|    # Act: Trigger a price jump greater than the 10% threshold
203|    # The return from 100 to 111 is +11%
204|    alerts = risk_manager.update_market_data(price=111.0, volume=1000)
205|
206|    # Assert
207|    assert alerts["price_jump_alert"] is True
208|    assert "Significant price jump" in alerts["messages"][0]
209|
