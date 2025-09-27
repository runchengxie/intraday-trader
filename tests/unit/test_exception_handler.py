import pytest
import time
import json
from unittest.mock import MagicMock, call

# Import the classes and decorators to be tested
from src.patf_trading_framework.exception_handler import (
    ExceptionHandler,
    ErrorCategory,
    ErrorSeverity,
    RetryConfig,
    CircuitBreaker,
    handle_exceptions,
)

# --- Pytest Fixtures ---

@pytest.fixture
def handler():
    """Returns a clean ExceptionHandler instance for each test."""
    return ExceptionHandler()

@pytest.fixture
def retry_config():
    """Returns a standard RetryConfig instance."""
    return RetryConfig(base_delay=0.01) # Use a very small delay for fast tests


# --- RetryConfig Tests ---

def test_retry_config_exponential_backoff(retry_config):
    """Verify that the delay increases exponentially with backoff enabled."""
    retry_config.exponential_backoff = True
    delay1 = retry_config.get_delay(0) # 2**0 * 0.01
    delay2 = retry_config.get_delay(1) # 2**1 * 0.01
    delay3 = retry_config.get_delay(2) # 2**2 * 0.01
    
    # We use pytest.approx because of jitter
    assert delay2 > delay1
    assert delay3 > delay2
    assert delay2 == pytest.approx(delay1 * 2, rel=0.5) # Jitter can be up to 50%
    assert delay3 == pytest.approx(delay2 * 2, rel=0.5)


def test_retry_config_no_backoff(retry_config):
    """Verify that the delay remains constant with backoff disabled."""
    retry_config.exponential_backoff = False
    delay1 = retry_config.get_delay(0)
    delay2 = retry_config.get_delay(1)
    
    assert delay1 == pytest.approx(delay2, rel=0.5)


# --- CircuitBreaker Tests ---

def test_circuit_breaker_trips_and_opens():
    """Verify the breaker opens after reaching the failure threshold."""
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=10)
    failing_func = MagicMock(side_effect=ValueError("Failed"))
    
    # First failure
    with pytest.raises(ValueError):
        breaker.call(failing_func)
    assert breaker.state == "CLOSED"
    assert breaker.failure_count == 1
    
    # Second failure - should trip the breaker
    with pytest.raises(ValueError):
        breaker.call(failing_func)
    assert breaker.state == "OPEN"
    assert breaker.failure_count == 2
    
    # Third call should be blocked immediately
    with pytest.raises(Exception, match="Circuit breaker is open"):
        breaker.call(failing_func)
    
    # The original function should only have been called twice
    assert failing_func.call_count == 2


def test_circuit_breaker_resets_after_recovery():
    """Verify the breaker moves to HALF_OPEN and then CLOSED after recovery."""
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
    failing_func = MagicMock(side_effect=ValueError("Failed"))
    succeeding_func = MagicMock(return_value="Success")
    
    # Trip the breaker
    with pytest.raises(ValueError):
        breaker.call(failing_func)
    assert breaker.state == "OPEN"
    
    # Wait for recovery timeout
    time.sleep(0.02)
    
    # Call with a succeeding function. It should now be HALF_OPEN, then move to CLOSED
    result = breaker.call(succeeding_func)
    
    assert result == "Success"
    assert breaker.state == "CLOSED"
    assert breaker.failure_count == 0


# --- ExceptionHandler Core Logic Tests ---

def test_handle_exception_creates_record(handler):
    """Verify that handling an exception logs it correctly."""
    try:
        _ = 1 / 0
    except ZeroDivisionError as e:
        handler.handle_exception(e, ErrorCategory.SYSTEM, ErrorSeverity.CRITICAL)
        
    assert len(handler.error_records) == 1
    record = handler.error_records[0]
    
    assert record.error_type == "ZeroDivisionError"
    assert record.category == ErrorCategory.SYSTEM
    assert record.severity == ErrorSeverity.CRITICAL
    assert "division by zero" in record.message


def test_emergency_stop_triggered_on_critical(handler):
    """Verify the emergency stop flag is set only for CRITICAL errors."""
    handler.handle_exception(ValueError("High error"), ErrorCategory.API, ErrorSeverity.HIGH)
    assert handler.emergency_stop_triggered is False
    
    handler.handle_exception(ValueError("Critical error"), ErrorCategory.SYSTEM, ErrorSeverity.CRITICAL)
    assert handler.emergency_stop_triggered is True


def test_error_callback_is_executed(handler):
    """Verify that a registered callback function is called on the correct error category."""
    callback_mock = MagicMock()
    handler.register_error_callback(ErrorCategory.NETWORK, callback_mock)
    
    # Handle a network error
    handler.handle_exception(ConnectionError("Timeout"), ErrorCategory.NETWORK, ErrorSeverity.MEDIUM)
    
    # Handle a different category of error
    handler.handle_exception(ValueError("Bad param"), ErrorCategory.API, ErrorSeverity.LOW)
    
    # The callback should have been called exactly once with the network error record
    callback_mock.assert_called_once()
    assert callback_mock.call_args[0][0].category == ErrorCategory.NETWORK


# --- Decorator and Retry Logic Tests ---

class MockTrader:
    """A mock class to test the decorator's ability to access the handler."""
    def __init__(self, handler):
        self.exception_handler = handler
        self.call_count = 0

    @handle_exceptions(category=ErrorCategory.API, retry=True)
    def fetch_data_with_retry(self):
        self.call_count += 1
        if self.call_count < 3:
            raise ValueError("API is down")
        return "Success"

    @handle_exceptions(category=ErrorCategory.SYSTEM, retry=False, default_return="Default")
    def fail_once_no_retry(self):
        raise SystemError("System failed")


def test_handle_exceptions_decorator_with_retry(handler):
    """Verify the retry decorator re-executes the function until it succeeds."""
    # Configure a fast retry for the test
    handler.retry_configs[ErrorCategory.API] = RetryConfig(max_retries=3, base_delay=0.01)
    
    trader = MockTrader(handler)
    result = trader.fetch_data_with_retry()
    
    assert result == "Success"
    assert trader.call_count == 3
    # Two errors should have been logged for the failed attempts
    assert len(handler.error_records) == 2
    assert handler.error_records[0].error_type == 'ValueError'


def test_handle_exceptions_decorator_no_retry(handler):
    """Verify the decorator with retry=False returns a default value on failure."""
    trader = MockTrader(handler)
    result = trader.fail_once_no_retry()
    
    assert result == "Default"
    # One error should be logged
    assert len(handler.error_records) == 1
    assert handler.error_records[0].error_type == 'SystemError'


# --- Reporting and State Management Tests ---

def test_get_error_statistics(handler):
    """Verify the statistics report aggregates errors correctly."""
    handler.handle_exception(ConnectionError(), ErrorCategory.NETWORK, ErrorSeverity.MEDIUM)
    handler.handle_exception(ValueError(), ErrorCategory.API, ErrorSeverity.LOW)
    handler.handle_exception(ValueError(), ErrorCategory.API, ErrorSeverity.LOW)
    
    stats = handler.get_error_statistics()
    
    assert stats['total_errors'] == 3
    assert stats['category_breakdown']['network']['count'] == 1
    assert stats['category_breakdown']['api']['count'] == 2
    assert stats['severity_breakdown']['low'] == 2
    assert stats['severity_breakdown']['medium'] == 1


def test_export_error_log(handler, tmp_path):
    """Verify that an error log can be exported to a JSON file."""
    handler.handle_exception(TypeError("Bad type"), ErrorCategory.STRATEGY, ErrorSeverity.HIGH)
    
    file_path = tmp_path / "error_log.json"
    handler.export_error_log(str(file_path))
    
    assert file_path.exists()
    with open(file_path) as f:
        data = json.load(f)
    
    assert len(data) == 1
    assert data[0]['error_type'] == 'TypeError'