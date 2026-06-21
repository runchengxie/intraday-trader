1|import json
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|from datetime import datetime
3|
4|import pytest
5|
6|pd = pytest.importorskip("pandas")
7|np = pytest.importorskip("numpy")
8|
9|from intraday_trader_air.performance_analyzer import (
10|    PerformanceAnalyzer,
11|    TradeRecord,
12|)
13|
14|# --- Pytest Fixtures ---
15|
16|
17|@pytest.fixture
18|def empty_analyzer():
19|    """Returns a PerformanceAnalyzer instance with no data."""
20|    return PerformanceAnalyzer(initial_capital=100000.0)
21|
22|
23|@pytest.fixture
24|def populated_analyzer():
25|    """
26|    Returns a PerformanceAnalyzer instance populated with a realistic
27|    set of mock trades and portfolio snapshots for thorough testing.
28|    """
29|    analyzer = PerformanceAnalyzer(initial_capital=100000.0)
30|
31|    # Mock trades representing a few winning and losing rounds
32|    mock_trades = [
33|        TradeRecord(
34|            timestamp=datetime(2023, 1, 5, 10, 5),
35|            symbol="SPY",
36|            side="buy",
37|            quantity=50,
38|            price=380.00,
39|            commission=1.0,
40|            order_id="order1",
41|            slippage=0.02,
42|            market_impact=0.01,
43|        ),
44|        TradeRecord(
45|            timestamp=datetime(2023, 1, 6, 14, 30),
46|            symbol="SPY",
47|            side="sell",
48|            quantity=50,
49|            price=385.00,
50|            commission=1.0,
51|            order_id="order2",
52|            slippage=0.03,
53|            market_impact=0.015,
54|        ),  # Profit
55|        TradeRecord(
56|            timestamp=datetime(2023, 1, 10, 11, 0),
57|            symbol="AAPL",
58|            side="buy",
59|            quantity=25,
60|            price=130.00,
61|            commission=1.0,
62|            order_id="order3",
63|            slippage=0.01,
64|            market_impact=0.005,
65|        ),
66|        TradeRecord(
67|            timestamp=datetime(2023, 1, 11, 9, 45),
68|            symbol="AAPL",
69|            side="sell",
70|            quantity=25,
71|            price=128.00,
72|            commission=1.0,
73|            order_id="order4",
74|            slippage=0.01,
75|            market_impact=0.005,
76|        ),  # Loss
77|    ]
78|    for trade in mock_trades:
79|        analyzer.add_trade(trade)
80|
81|    # Mock portfolio values showing growth and a drawdown
82|    # Daily snapshots for 5 trading days
83|    analyzer.portfolio_values = [
84|        (datetime(2023, 1, 4, 16, 0), 100000.0),
85|        (datetime(2023, 1, 5, 16, 0), 100150.0),
86|        (datetime(2023, 1, 6, 16, 0), 100247.0),  # Peak value
87|        (datetime(2023, 1, 9, 16, 0), 100200.0),
88|        (datetime(2023, 1, 10, 16, 0), 100100.0),  # Drawdown
89|        (datetime(2023, 1, 11, 16, 0), 100193.0),
90|    ]
91|
92|    # Update market prices needed for concentration risk calculation
93|    analyzer.latest_market_prices = {"SPY": 390.0, "AAPL": 135.0}
94|
95|    return analyzer
96|
97|
98|# --- Unit Tests ---
99|
100|
101|def test_initialization(empty_analyzer):
102|    """Verify the analyzer is initialized with the correct starting capital."""
103|    assert empty_analyzer.initial_capital == 100000.0
104|    assert empty_analyzer.cash == 100000.0
105|    assert len(empty_analyzer.trades) == 0
106|    assert len(empty_analyzer.portfolio_values) == 0
107|
108|
109|def test_add_trade(empty_analyzer):
110|    """Verify that adding a trade correctly updates internal state."""
111|    trade = TradeRecord(
112|        timestamp=datetime.now(),
113|        symbol="SPY",
114|        side="buy",
115|        quantity=10,
116|        price=400.0,
117|        commission=1.0,
118|        order_id="t1",
119|    )
120|
121|    empty_analyzer.add_trade(trade)
122|
123|    assert len(empty_analyzer.trades) == 1
124|    assert empty_analyzer.trades[0] == trade
125|    assert empty_analyzer.positions["SPY"] == 10
126|    # Expected cash = 100000 - (10 * 400) - 1.0 = 95999.0
127|    assert empty_analyzer.cash == pytest.approx(95999.0)
128|
129|
130|def test_calculate_returns(populated_analyzer):
131|    """Verify the calculation of portfolio percentage returns."""
132|    returns = populated_analyzer.calculate_returns()
133|    assert isinstance(returns, pd.Series)
134|    assert len(returns) == 5  # (6 snapshots - 1)
135|
136|    # Manual calculation for the first return: (100150.0 / 100000.0) - 1
137|    expected_first_return = 0.0015
138|    assert returns.iloc[0] == pytest.approx(expected_first_return)
139|
140|
141|def test_calculate_risk_metrics_with_data(populated_analyzer):
142|    """Test the calculation of key risk metrics against known results."""
143|    metrics = populated_analyzer.calculate_risk_metrics()
144|
145|    assert metrics is not None
146|    assert "total_return" in metrics
147|    assert "sharpe_ratio" in metrics
148|    assert "max_drawdown" in metrics
149|
150|    # Final value is 100193.0, initial is 100000.0
151|    expected_total_return = (100193.0 / 100000.0) - 1
152|    assert metrics["total_return"] == pytest.approx(expected_total_return)
153|
154|    # Max drawdown check: Peak was 100247, trough was 100100
155|    # Expected drawdown = (100100 - 100247) / 100247
156|    expected_max_drawdown = (100100 - 100247) / 100247
157|    assert metrics["max_drawdown"] == pytest.approx(expected_max_drawdown)
158|
159|    # Sharpe ratio is complex to calculate manually here, but we can check if it's a float
160|    assert isinstance(metrics["sharpe_ratio"], float)
161|
162|
163|def test_calculate_trading_costs(populated_analyzer):
164|    """Verify the aggregation of trading costs."""
165|    costs = populated_analyzer.calculate_trading_costs()
166|
167|    # Total commissions: 1.0 + 1.0 + 1.0 + 1.0 = 4.0
168|    assert costs["total_commission"] == pytest.approx(4.0)
169|
170|    # Total slippage: (0.02*50) + (0.03*50) + (0.01*25) + (0.01*25) = 1.0 + 1.5 + 0.25 + 0.25 = 3.0
171|    assert costs["total_slippage"] == pytest.approx(3.0)
172|
173|    # Total market impact: (0.01*50) + (0.015*50) + (0.005*25) + (0.005*25) = 0.5 + 0.75 + 0.125 + 0.125 = 1.5
174|    assert costs["total_market_impact"] == pytest.approx(1.5)
175|
176|    # Total cost = 4.0 + 3.0 + 1.5 = 8.5
177|    assert costs["total_cost"] == pytest.approx(8.5)
178|
179|
180|def test_calculate_turnover_rate(populated_analyzer):
181|    """Verify the calculation of portfolio turnover."""
182|    turnover = populated_analyzer.calculate_turnover_rate(period_days=30)
183|
184|    # Total traded value: (50*380)+(50*385)+(25*130)+(25*128) = 19000+19250+3250+3200 = 44700
185|    expected_traded_value = 44700.0
186|    assert turnover["total_traded_value"] == pytest.approx(expected_traded_value)
187|
188|    # Avg portfolio value: mean of [100000.0, 100150.0, 100247.0, 100200.0, 100100.0, 100193.0]
189|    avg_portfolio_value = np.mean(
190|        [100000.0, 100150.0, 100247.0, 100200.0, 100100.0, 100193.0]
191|    )
192|    assert turnover["avg_portfolio_value"] == pytest.approx(avg_portfolio_value)
193|
194|    # Turnover rate = 44700 / avg_portfolio_value
195|    expected_turnover = expected_traded_value / avg_portfolio_value
196|    assert turnover["turnover_rate"] == pytest.approx(expected_turnover)
197|
198|
199|# --- Edge Case and Empty State Tests ---
200|
201|
202|def test_risk_metrics_no_data(empty_analyzer):
203|    """Ensure risk metrics calculation handles no data gracefully."""
204|    metrics = empty_analyzer.calculate_risk_metrics()
205|    assert metrics == {}
206|
207|
208|def test_costs_no_trades(empty_analyzer):
209|    """Ensure cost calculation handles no trades gracefully."""
210|    costs = empty_analyzer.calculate_trading_costs()
211|    assert costs == {}
212|
213|
214|def test_turnover_no_trades(empty_analyzer):
215|    """Ensure turnover calculation handles no trades gracefully."""
216|    turnover = empty_analyzer.calculate_turnover_rate()
217|    assert turnover["turnover_rate"] == 0.0
218|
219|
220|def test_returns_insufficient_data(empty_analyzer):
221|    """Ensure returns calculation handles fewer than two snapshots."""
222|    empty_analyzer.add_snapshot(datetime.now(), 100000.0)
223|    returns = empty_analyzer.calculate_returns()
224|    assert returns.empty is True
225|
226|
227|# --- Reporting and Plotting Tests ---
228|
229|
230|def test_generate_performance_report(populated_analyzer):
231|    """Verify that a JSON report is generated and contains the expected keys."""
232|    report_str = populated_analyzer.generate_performance_report()
233|    assert isinstance(report_str, str)
234|
235|    report_data = json.loads(report_str)
236|    assert "summary" in report_data
237|    assert "returns_analysis" in report_data
238|    assert "trading_costs" in report_data
239|    assert "turnover_analysis" in report_data
240|    assert "concentration_risk" in report_data
241|    assert report_data["summary"]["total_return"] == pytest.approx(0.00193)
242|
243|
244|def test_plot_performance_charts_runs_without_error(
245|    populated_analyzer, tmp_path, mocker
246|):
247|    """
248|    Verify that the plotting function executes without errors and creates a file.
249|    We mock `plt.show()` to prevent plots from displaying during tests.
250|    """
251|    # Arrange
252|    mocker.patch("matplotlib.pyplot.show")  # Prevent plot window from opening
253|    save_path = tmp_path / "test_performance_chart.png"
254|
255|    # Act
256|    populated_analyzer.plot_performance_charts(save_path=str(save_path))
257|
258|    # Assert
259|    assert save_path.exists()
260|    assert save_path.is_file()
261|

