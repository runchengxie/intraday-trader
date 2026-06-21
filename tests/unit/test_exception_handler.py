1|import json
# pyright: reportUnknownMemberType=false, reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportCallIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportGeneralTypeIssues=false
2|import time
3|from unittest.mock import MagicMock
4|
5|import pytest
6|
7|from intraday_trader_air.exception_handler import (
8|    CircuitBreaker,
9|    ErrorCategory,
10|    ErrorSeverity,
11|    ExceptionHandler,
12|    RetryConfig,
13|    handle_exceptions,
14|)
15|
16|# --- Pytest Fixtures ---
17|
18|
19|@pytest.fixture
20|def handler():
21|    """Returns a clean ExceptionHandler instance for each test."""
22|    return ExceptionHandler()
23|
24|
25|@pytest.fixture
26|def retry_config():
27|    """Returns a standard RetryConfig instance."""
28|    return RetryConfig(base_delay=0.01)  # Use a very small delay for fast tests
29|
30|
31|# --- RetryConfig Tests ---
32|
33|
34|def test_retry_config_exponential_backoff(retry_config):
35|    """Verify that the delay increases exponentially with backoff enabled."""
36|    retry_config.exponential_backoff = True
37|    retry_config.jitter = False
38|    delay1 = retry_config.get_delay(0)  # 2**0 * 0.01
39|    delay2 = retry_config.get_delay(1)  # 2**1 * 0.01
40|    delay3 = retry_config.get_delay(2)  # 2**2 * 0.01
41|
42|    # We use pytest.approx because of jitter
43|    assert delay2 > delay1
44|    assert delay3 > delay2
45|    assert delay2 == pytest.approx(delay1 * 2, rel=0.5)  # Jitter can be up to 50%
46|    assert delay3 == pytest.approx(delay2 * 2, rel=0.5)
47|
48|
49|def test_retry_config_no_backoff(retry_config):
50|    """Verify that the delay remains constant with backoff disabled."""
51|    retry_config.exponential_backoff = False
52|    retry_config.jitter = False
53|    delay1 = retry_config.get_delay(0)
54|    delay2 = retry_config.get_delay(1)
55|
56|    assert delay1 == pytest.approx(delay2, rel=0.5)
57|
58|
59|# --- CircuitBreaker Tests ---
60|
61|
62|def test_circuit_breaker_trips_and_opens():
63|    """Verify the breaker opens after reaching the failure threshold."""
64|    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=10)
65|    call_counter = {"value": 0}
66|
67|    def failing_func():
68|        call_counter["value"] += 1
69|        raise ValueError("Failed")
70|
71|    with pytest.raises(ValueError):
72|        breaker.call(failing_func)
73|    assert breaker.state == "CLOSED"
74|    assert breaker.failure_count == 1
75|
76|    with pytest.raises(ValueError):
77|        breaker.call(failing_func)
78|    assert breaker.state == "OPEN"
79|    assert breaker.failure_count == 2
80|
81|    with pytest.raises(Exception, match="Circuit breaker is open"):
82|        breaker.call(failing_func)
83|
84|    assert call_counter["value"] == 2
85|
86|
87|def test_circuit_breaker_resets_after_recovery():
88|    """Verify the breaker moves to HALF_OPEN and then CLOSED after recovery."""
89|    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
90|    failing_func = MagicMock(side_effect=ValueError("Failed"))
91|    succeeding_func = MagicMock(return_value="Success")
92|
93|    # Trip the breaker
94|    with pytest.raises(ValueError):
95|        breaker.call(failing_func)
96|    assert breaker.state == "OPEN"
97|
98|    # Wait for recovery timeout
99|    time.sleep(0.02)
100|
101|    # Call with a succeeding function. It should now be HALF_OPEN, then move to CLOSED
102|    result = breaker.call(succeeding_func)
103|
104|    assert result == "Success"
105|    assert breaker.state == "CLOSED"
106|    assert breaker.failure_count == 0
107|
108|
109|# --- ExceptionHandler Core Logic Tests ---
110|
111|
112|def test_handle_exception_creates_record(handler):
113|    """Verify that handling an exception logs it correctly."""
114|    try:
115|        _ = 1 / 0
116|    except ZeroDivisionError as e:
117|        handler.handle_exception(e, ErrorCategory.SYSTEM, ErrorSeverity.CRITICAL)
118|
119|    assert len(handler.error_records) == 1
120|    record = handler.error_records[0]
121|
122|    assert record.error_type == "ZeroDivisionError"
123|    assert record.category == ErrorCategory.SYSTEM
124|    assert record.severity == ErrorSeverity.CRITICAL
125|    assert "division by zero" in record.message
126|
127|
128|def test_emergency_stop_triggered_on_critical(handler):
129|    """Verify the emergency stop flag is set only for CRITICAL errors."""
130|    handler.handle_exception(
131|        ValueError("High error"), ErrorCategory.API, ErrorSeverity.HIGH
132|    )
133|    assert handler.emergency_stop_triggered is False
134|
135|    handler.handle_exception(
136|        ValueError("Critical error"), ErrorCategory.SYSTEM, ErrorSeverity.CRITICAL
137|    )
138|    assert handler.emergency_stop_triggered is True
139|
140|
141|def test_error_callback_is_executed(handler):
142|    """Verify that a registered callback function is called on the correct error category."""
143|    callback_mock = MagicMock()
144|    handler.register_error_callback(ErrorCategory.NETWORK, callback_mock)
145|
146|    # Handle a network error
147|    handler.handle_exception(
148|        ConnectionError("Timeout"), ErrorCategory.NETWORK, ErrorSeverity.MEDIUM
149|    )
150|
151|    # Handle a different category of error
152|    handler.handle_exception(
153|        ValueError("Bad param"), ErrorCategory.API, ErrorSeverity.LOW
154|    )
155|
156|    # The callback should have been called exactly once with the network error record
157|    callback_mock.assert_called_once()
158|    assert callback_mock.call_args[0][0].category == ErrorCategory.NETWORK
159|
160|
161|# --- Decorator and Retry Logic Tests ---
162|
163|
164|class MockTrader:
165|    """A mock class to test the decorator's ability to access the handler."""
166|
167|    def __init__(self, handler):
168|        self.exception_handler = handler
169|        self.call_count = 0
170|
171|    @handle_exceptions(category=ErrorCategory.API, retry=True)
172|    def fetch_data_with_retry(self):
173|        self.call_count += 1
174|        if self.call_count < 3:
175|            raise ValueError("API is down")
176|        return "Success"
177|
178|    @handle_exceptions(
179|        category=ErrorCategory.SYSTEM, retry=False, default_return="Default"
180|    )
181|    def fail_once_no_retry(self):
182|        raise SystemError("System failed")
183|
184|
185|def test_handle_exceptions_decorator_with_retry(handler, caplog):
186|    """Verify the retry decorator re-executes the function until it succeeds."""
187|    # Configure a fast retry for the test
188|    handler.retry_configs[ErrorCategory.API] = RetryConfig(
189|        max_retries=3, base_delay=0.01
190|    )
191|
192|    trader = MockTrader(handler)
193|    with caplog.at_level("WARNING"):
194|        result = trader.fetch_data_with_retry()
195|
196|    assert result == "Success"
197|    assert trader.call_count == 3
198|    assert handler.error_records == []
199|    assert handler.emergency_stop_triggered is False
200|    assert any("Retrying" in record.message for record in caplog.records)
201|
202|
203|def test_handle_exceptions_decorator_no_retry(handler):
204|    """Verify the decorator with retry=False returns a default value on failure."""
205|    trader = MockTrader(handler)
206|    result = trader.fail_once_no_retry()
207|
208|    assert result == "Default"
209|    # One error should be logged
210|    assert len(handler.error_records) == 1
211|    assert handler.error_records[0].error_type == "SystemError"
212|
213|
214|# --- Reporting and State Management Tests ---
215|
216|
217|def test_get_error_statistics(handler):
218|    """Verify the statistics report aggregates errors correctly."""
219|    handler.handle_exception(
220|        ConnectionError(), ErrorCategory.NETWORK, ErrorSeverity.MEDIUM
221|    )
222|    handler.handle_exception(ValueError(), ErrorCategory.API, ErrorSeverity.LOW)
223|    handler.handle_exception(ValueError(), ErrorCategory.API, ErrorSeverity.LOW)
224|
225|    stats = handler.get_error_statistics()
226|
227|    assert stats["total_errors"] == 3
228|    assert stats["category_breakdown"]["network"]["count"] == 1
229|    assert stats["category_breakdown"]["api"]["count"] == 2
230|    assert stats["severity_breakdown"]["low"] == 2
231|    assert stats["severity_breakdown"]["medium"] == 1
232|
233|
234|def test_export_error_log(handler, tmp_path):
235|    """Verify that an error log can be exported to a JSON file."""
236|    handler.handle_exception(
237|        TypeError("Bad type"), ErrorCategory.STRATEGY, ErrorSeverity.HIGH
238|    )
239|
240|    file_path = tmp_path / "error_log.json"
241|    handler.export_error_log(str(file_path))
242|
243|    assert file_path.exists()
244|    with open(file_path) as f:
245|        data = json.load(f)
246|
247|    assert len(data) == 1
248|    assert data[0]["error_type"] == "TypeError"
249|

