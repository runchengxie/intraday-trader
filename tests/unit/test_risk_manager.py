1|1|import pytest
2|# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
3|2|
4|3|np = pytest.importorskip("numpy")
5|4|
6|5|from intraday_trader_air.risk_manager import RiskManager
7|6|
8|7|# --- Pytest Fixtures ---
9|8|
10|9|
11|10|@pytest.fixture
12|11|def risk_config():
13|12|    """Provides a standard, reusable risk configuration dictionary for tests."""
14|13|    return {
15|14|        "var_window": 252,
16|15|        "var_confidence_level": 0.05,  # Corresponds to a 95% confidence level
17|16|        "price_jump_threshold": 0.10,  # 10% jump
18|17|        "volume_spike_threshold": 5.0,  # 5x average volume
19|18|        "max_order_participation_ratio": 0.02,  # 2% of recent volume
20|19|        "max_bid_ask_spread_pct": 0.005,  # 0.5% spread
21|20|        "market_impact_coefficient": 0.5,
22|21|        "max_gross_exposure": 1.5,  # 150%
23|22|        "max_leverage": 2.0,
24|23|    }
25|24|
26|25|
27|26|@pytest.fixture
28|27|def risk_manager(risk_config):
29|28|    """Returns a clean RiskManager instance using the standard config."""
30|29|    return RiskManager(risk_config)
31|30|
32|31|
33|32|@pytest.fixture
34|33|def populated_risk_manager(risk_manager):
35|34|    """Returns a RiskManager instance with a pre-filled history of returns."""
36|35|    # Create a predictable series of 50 returns for testing calculations
37|36|    np.random.seed(42)  # for reproducibility
38|37|    returns = np.random.normal(loc=0.0005, scale=0.01, size=50).tolist()
39|38|    # Add a few outliers to make VaR more meaningful
40|39|    returns[5] = -0.04  # 4% drop
41|40|    returns[15] = 0.035  # 3.5% gain
42|41|
43|42|    for r in returns:
44|43|        risk_manager.returns_history.append(r)
45|44|
46|45|    # Also populate price and volume history for other checks
47|46|    prices = 100 * np.exp(np.cumsum(returns))
48|47|    for p in prices:
49|48|        risk_manager.price_history.append(p)
50|49|    for _ in range(50):
51|50|        risk_manager.volume_history.append(10000)
52|51|
53|52|    return risk_manager
54|53|
55|54|
56|55|# --- Initialization and State Tests ---
57|56|
58|57|
59|58|def test_initialization_with_config(risk_manager, risk_config):
60|59|    """Verify that the risk manager initializes correctly with a given config."""
61|60|    assert risk_manager.var_window == risk_config["var_window"]
62|61|    assert risk_manager.config["max_gross_exposure"] == 1.5
63|62|
64|63|
65|64|def test_update_market_data_populates_history(risk_manager):
66|65|    """Verify that calling update_market_data correctly updates internal deques."""
67|66|    risk_manager.update_market_data(price=100, volume=1000)
68|67|    risk_manager.update_market_data(price=101, volume=1100)
69|68|
70|69|    assert len(risk_manager.price_history) == 2
71|70|    assert len(risk_manager.volume_history) == 2
72|71|    # Return history only has 1 entry since it needs two prices
73|72|    assert len(risk_manager.returns_history) == 1
74|73|    # Expected return = (101 - 100) / 100 = 0.01
75|74|    assert risk_manager.returns_history[0] == pytest.approx(0.01)
76|75|
77|76|
78|77|# --- Value at Risk (VaR) Calculation Tests ---
79|78|
80|79|
81|80|def test_calculate_var_historical(populated_risk_manager):
82|81|    """Verify historical VaR calculation against a known dataset."""
83|82|    portfolio_value = 100000.0
84|83|    result = populated_risk_manager.calculate_var(portfolio_value, method="historical")
85|84|
86|85|    # Manually calculate expected VaR for our known returns data
87|86|    returns_array = np.array(list(populated_risk_manager.returns_history))
88|87|    expected_var_return = np.percentile(returns_array, 5)  # 5th percentile for 95% VaR
89|88|    expected_var_amount = abs(expected_var_return * portfolio_value)
90|89|
91|90|    assert result["method"] == "historical"
92|91|    assert result["var"] == pytest.approx(expected_var_amount)
93|92|    assert result["var_percentage"] == pytest.approx(abs(expected_var_return))
94|93|
95|94|
96|95|def test_calculate_var_parametric(populated_risk_manager):
97|96|    """Verify parametric VaR calculation against a known dataset."""
98|97|    from scipy.stats import norm
99|98|
100|99|    portfolio_value = 100000.0
101|100|    result = populated_risk_manager.calculate_var(portfolio_value, method="parametric")
102|101|
103|102|    # Manually calculate expected VaR for our known returns data
104|103|    returns_array = np.array(list(populated_risk_manager.returns_history))
105|104|    mean = np.mean(returns_array)
106|105|    std = np.std(returns_array)
107|106|    expected_var_return = norm.ppf(0.05, mean, std)
108|107|    expected_var_amount = abs(expected_var_return * portfolio_value)
109|108|
110|109|    assert result["method"] == "parametric"
111|110|    assert result["var"] == pytest.approx(expected_var_amount)
112|111|
113|112|
114|113|def test_calculate_var_insufficient_data(risk_manager):
115|114|    """Ensure VaR calculation returns None when there is not enough historical data."""
116|115|    result = risk_manager.calculate_var(100000.0)
117|116|    assert result["var"] is None
118|117|
119|118|
120|119|# --- Pre-Trade Check Tests ---
121|120|
122|121|
123|122|def test_leverage_check_fails_on_exposure(risk_manager):
124|123|    """Ensures check fails if a trade exceeds the max gross exposure limit."""
125|124|    # Scenario: 1.5 (150%) limit. Portfolio is $100k, gross positions are already $140k.
126|125|    # A new trade worth $20k would push exposure to ($140k + $20k) / $100k = 160%.
127|126|    passed, warnings = risk_manager.check_leverage_and_exposure(
128|127|        proposed_trade_value=20000,
129|128|        portfolio_value=100000,
130|129|        gross_position_value=140000,
131|130|        cash=10000,  # Cash doesn't affect gross exposure calculation
132|131|    )
133|132|    assert passed is False
134|133|    assert "New gross exposure" in warnings[0]
135|134|
136|135|
137|136|def test_liquidity_check_fails_on_participation(risk_manager):
138|137|    """Ensures check fails if order size is too large relative to market volume."""
139|138|    # Scenario: 2% participation limit. Order size is 500, but recent average volume is 10,000.
140|139|    # Participation ratio would be 500 / 10000 = 5%, which exceeds the limit.
141|140|    passed, details = risk_manager.check_liquidity_and_impact(
142|141|        order_size=500,
143|142|        recent_avg_volume=10000,
144|143|        current_volatility=0.015,  # Volatility is needed for impact cost
145|144|        bid_ask_spread_pct=0.001,  # Well within limits
146|145|    )
147|146|    assert passed is False
148|147|    assert "Participation ratio" in details["warnings"][0]
149|148|
150|149|
151|150|def test_liquidity_check_fails_on_spread(risk_manager):
152|151|    """Ensures check fails if the bid-ask spread is too wide."""
153|152|    # Scenario: 0.5% spread limit. Current spread is 0.7%.
154|153|    passed, details = risk_manager.check_liquidity_and_impact(
155|154|        order_size=100,
156|155|        recent_avg_volume=50000,
157|156|        current_volatility=0.01,
158|157|        bid_ask_spread_pct=0.007,  # Exceeds the 0.005 limit
159|158|    )
160|159|    assert passed is False
161|160|    assert "Bid-ask spread" in details["warnings"][0]
162|161|
163|162|
164|163|def test_pre_trade_checks_pass(risk_manager):
165|164|    """Verify that checks pass when all parameters are within acceptable limits."""
166|165|    # Leverage check
167|166|    leverage_passed, leverage_warnings = risk_manager.check_leverage_and_exposure(
168|167|        proposed_trade_value=10000,
169|168|        portfolio_value=100000,
170|169|        gross_position_value=50000,
171|170|        cash=50000,
172|171|    )
173|172|    assert leverage_passed is True
174|173|    assert not leverage_warnings
175|174|
176|175|    # Liquidity check
177|176|    liquidity_passed, liquidity_details = risk_manager.check_liquidity_and_impact(
178|177|        order_size=100,
179|178|        recent_avg_volume=50000,
180|179|        current_volatility=0.01,
181|180|        bid_ask_spread_pct=0.001,
182|181|    )
183|182|    assert liquidity_passed is True
184|183|    assert not liquidity_details["warnings"]
185|184|
186|185|
187|186|# --- Data Validation and Alert Tests ---
188|187|
189|188|
190|189|def test_validate_market_data_invalid_price(risk_manager):
191|190|    """Verify data validation catches a non-positive price."""
192|191|    validation = risk_manager.validate_market_data(price=-5.0, volume=1000)
193|192|    assert validation["is_valid"] is False
194|193|    assert "Invalid price" in validation["errors"][0]
195|194|
196|195|
197|196|def test_perform_risk_checks_price_jump(risk_manager):
198|197|    """Verify that _perform_risk_checks detects a significant price jump."""
199|198|    # Arrange: Add a base price
200|199|    risk_manager.price_history.append(100.0)
201|200|    risk_manager.returns_history.append(0.0)  # Dummy previous return
202|201|
203|202|    # Act: Trigger a price jump greater than the 10% threshold
204|203|    # The return from 100 to 111 is +11%
205|204|    alerts = risk_manager.update_market_data(price=111.0, volume=1000)
206|205|
207|206|    # Assert
208|207|    assert alerts["price_jump_alert"] is True
209|208|    assert "Significant price jump" in alerts["messages"][0]
210|209|

