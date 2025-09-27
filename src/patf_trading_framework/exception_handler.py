import json
import logging
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels."""

    LOW = "low"  # Minor error; operation can continue
    MEDIUM = "medium"  # Moderate error; may require a retry or adjustment
    HIGH = "high"  # Severe error; requires immediate attention
    CRITICAL = "critical"  # Critical error; must be resolved immediately


class ErrorCategory(Enum):
    """Error categories"""

    NETWORK = "network"  # Network connection errors
    API = "api"  # API call errors
    ORDER_EXECUTION = "order_execution"  # Order execution errors
    DATA_QUALITY = "data_quality"  # Data quality issues
    RISK_MANAGEMENT = "risk_management"  # Risk management errors
    SYSTEM = "system"  # System errors
    STRATEGY = "strategy"  # Strategy logic errors


@dataclass
class ErrorRecord:
    """Represents a single error record."""

    timestamp: datetime
    error_type: str
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    traceback_info: str
    context: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    resolved: bool = False
    resolution_action: str | None = None
    resolution_timestamp: datetime | None = None


class RetryConfig:
    """Configuration for retry logic."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_backoff: bool = True,
        jitter: bool = True,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_backoff = exponential_backoff
        self.jitter = jitter

    def get_delay(self, attempt: int) -> float:
        """Calculates the delay for a retry attempt.

        Args:
            attempt (int): The current retry attempt number.

        Returns:
            float: The delay in seconds.
        """
        if self.exponential_backoff:
            delay = self.base_delay * (2**attempt)
        else:
            delay = self.base_delay

        delay = min(delay, self.max_delay)

        if self.jitter:
            import random

            # Apply random jitter, scaling the delay to 50-100% of its value.
            delay *= 0.5 + random.random() * 0.5

        return delay


class CircuitBreaker:
    """Implements the Circuit Breaker pattern."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception

        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self._lock = threading.Lock()

    def call(self, func: Callable, *args, **kwargs):
        """Calls a function through the circuit breaker."""
        with self._lock:
            if self.state == "OPEN":
                if self._should_attempt_reset():
                    self.state = "HALF_OPEN"
                else:
                    raise Exception(
                        f"Circuit breaker is open; refusing to call {func.__name__}"
                    )

            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
            except self.expected_exception as e:
                self._on_failure()
                raise e

    def _should_attempt_reset(self) -> bool:
        """Checks if it's time to attempt resetting the circuit breaker."""
        return (
            self.last_failure_time
            and time.time() - self.last_failure_time >= self.recovery_timeout
        )

    def _on_success(self):
        """Handles a successful call."""
        self.failure_count = 0
        self.state = "CLOSED"

    def _on_failure(self):
        """Handles a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(
                f"Circuit breaker tripped to OPEN state. Failure count: {self.failure_count}"
            )


class ExceptionHandler:
    """A comprehensive exception handler."""

    def __init__(self):
        self.error_records: list[ErrorRecord] = []
        self.retry_configs: dict[ErrorCategory, RetryConfig] = (
            self._init_retry_configs()
        )
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.error_callbacks: dict[ErrorCategory, list[Callable]] = {}
        self.emergency_stop_triggered = False
        self._lock = threading.Lock()

        logger.info("Exception handler initialized.")

    def _init_retry_configs(self) -> dict[ErrorCategory, RetryConfig]:
        """Initializes the default retry configurations for each error category."""
        return {
            ErrorCategory.NETWORK: RetryConfig(
                max_retries=5, base_delay=2.0, max_delay=30.0
            ),
            ErrorCategory.API: RetryConfig(
                max_retries=3, base_delay=1.0, max_delay=10.0
            ),
            ErrorCategory.ORDER_EXECUTION: RetryConfig(
                max_retries=2, base_delay=0.5, max_delay=5.0
            ),
            ErrorCategory.DATA_QUALITY: RetryConfig(
                max_retries=3, base_delay=1.0, max_delay=15.0
            ),
            ErrorCategory.RISK_MANAGEMENT: RetryConfig(
                max_retries=1, base_delay=0.1, max_delay=1.0
            ),
            ErrorCategory.SYSTEM: RetryConfig(
                max_retries=2, base_delay=5.0, max_delay=60.0
            ),
            ErrorCategory.STRATEGY: RetryConfig(
                max_retries=1, base_delay=1.0, max_delay=5.0
            ),
        }

    def register_circuit_breaker(self, name: str, circuit_breaker: CircuitBreaker):
        """Registers a circuit breaker."""
        self.circuit_breakers[name] = circuit_breaker
        logger.info(f"Circuit breaker registered: {name}")

    def register_error_callback(self, category: ErrorCategory, callback: Callable):
        """Registers an error callback function."""
        if category not in self.error_callbacks:
            self.error_callbacks[category] = []
        self.error_callbacks[category].append(callback)
        logger.info(f"Error callback registered for category: {category.value}")

    def handle_exception(
        self,
        exception: Exception,
        category: ErrorCategory,
        severity: ErrorSeverity,
        context: dict[str, Any] = None,
    ) -> ErrorRecord:
        """Handles a given exception."""
        error_record = ErrorRecord(
            timestamp=datetime.now(),
            error_type=type(exception).__name__,
            category=category,
            severity=severity,
            message=str(exception),
            traceback_info=traceback.format_exc(),
            context=context or {},
        )

        with self._lock:
            self.error_records.append(error_record)

        logger.error(
            f"Handling exception: {category.value} - {severity.value} - {error_record.message}"
        )

        # Execute error callbacks
        self._execute_error_callbacks(category, error_record)

        # Check if an emergency stop is required
        if severity == ErrorSeverity.CRITICAL:
            self._trigger_emergency_stop(error_record)

        return error_record

    def _execute_error_callbacks(
        self, category: ErrorCategory, error_record: ErrorRecord
    ):
        """Executes the registered callbacks for a given error category."""
        if category in self.error_callbacks:
            for callback in self.error_callbacks[category]:
                try:
                    callback(error_record)
                except Exception as e:
                    logger.error(f"Error callback execution failed: {e}")

    def _trigger_emergency_stop(self, error_record: ErrorRecord):
        """Triggers an emergency stop."""
        self.emergency_stop_triggered = True
        logger.critical(f"Emergency stop triggered: {error_record.message}")

    def retry_with_backoff(
        self, func: Callable, category: ErrorCategory, *args, **kwargs
    ) -> Any:
        """A retry mechanism with an exponential backoff strategy."""
        retry_config = self.retry_configs.get(category, RetryConfig())
        last_exception = None

        for attempt in range(retry_config.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e

                if attempt < retry_config.max_retries:
                    delay = retry_config.get_delay(attempt)
                    logger.warning(
                        f"Retrying {attempt + 1}/{retry_config.max_retries}, delaying for {delay:.2f}seconds: {e}"
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"Retry failed after maximum attempts: {e}")

        # Log the final failure
        severity = (
            ErrorSeverity.HIGH
            if category
            in [ErrorCategory.ORDER_EXECUTION, ErrorCategory.RISK_MANAGEMENT]
            else ErrorSeverity.MEDIUM
        )
        self.handle_exception(
            last_exception,
            category,
            severity,
            {"retry_attempts": retry_config.max_retries},
        )
        raise last_exception

    def with_circuit_breaker(self, circuit_breaker_name: str):
        """Decorator to wrap a function with a circuit breaker."""

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                if circuit_breaker_name in self.circuit_breakers:
                    circuit_breaker = self.circuit_breakers[circuit_breaker_name]
                    return circuit_breaker.call(func, *args, **kwargs)
                else:
                    return func(*args, **kwargs)

            return wrapper

        return decorator

    def safe_execute(
        self,
        func: Callable,
        category: ErrorCategory,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        context: dict[str, Any] = None,
        default_return: Any = None,
    ) -> Any:
        """Safely executes a function, capturing and handling any exceptions."""
        try:
            return func()
        except Exception as e:
            self.handle_exception(e, category, severity, context)
            return default_return

    def get_error_statistics(self, hours: int = 24) -> dict:
        """Retrieves error statistics."""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_errors = [
            err for err in self.error_records if err.timestamp >= cutoff_time
        ]

        # Statistics by category
        category_stats = {}
        for category in ErrorCategory:
            category_errors = [err for err in recent_errors if err.category == category]
            category_stats[category.value] = {
                "count": len(category_errors),
                "severity_breakdown": {
                    severity.value: len(
                        [err for err in category_errors if err.severity == severity]
                    )
                    for severity in ErrorSeverity
                },
            }

        # Statistics by severity
        severity_stats = {}
        for severity in ErrorSeverity:
            severity_errors = [err for err in recent_errors if err.severity == severity]
            severity_stats[severity.value] = len(severity_errors)

        # Most common errors
        error_types = {}
        for error in recent_errors:
            error_type = error.error_type
            if error_type not in error_types:
                error_types[error_type] = 0
            error_types[error_type] += 1

        most_common_errors = sorted(
            error_types.items(), key=lambda x: x[1], reverse=True
        )[:5]

        return {
            "analysis_period_hours": hours,
            "total_errors": len(recent_errors),
            "category_breakdown": category_stats,
            "severity_breakdown": severity_stats,
            "most_common_errors": most_common_errors,
            "emergency_stop_status": self.emergency_stop_triggered,
            "circuit_breaker_status": {
                name: cb.state for name, cb in self.circuit_breakers.items()
            },
        }

    def resolve_error(self, error_index: int, resolution_action: str):
        """Marks an error as resolved."""
        if 0 <= error_index < len(self.error_records):
            error_record = self.error_records[error_index]
            error_record.resolved = True
            error_record.resolution_action = resolution_action
            error_record.resolution_timestamp = datetime.now()

            logger.info(
                f"Error resolved: {error_record.error_type} - {resolution_action}"
            )
        else:
            logger.warning(f"Invalid error index: {error_index}")

    def reset_emergency_stop(self):
        """Resets the emergency stop status."""
        self.emergency_stop_triggered = False
        logger.info("Emergency stop status has been reset.")

    def export_error_log(self, file_path: str):
        """Exports the error log to a file."""
        error_data = []
        for error in self.error_records:
            error_data.append(
                {
                    "timestamp": error.timestamp.isoformat(),
                    "error_type": error.error_type,
                    "category": error.category.value,
                    "severity": error.severity.value,
                    "message": error.message,
                    "context": error.context,
                    "retry_count": error.retry_count,
                    "resolved": error.resolved,
                    "resolution_action": error.resolution_action,
                    "resolution_timestamp": (
                        error.resolution_timestamp.isoformat()
                        if error.resolution_timestamp
                        else None
                    ),
                }
            )

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(error_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Error log exported to:  {file_path}")


# Decorator function
def handle_exceptions(
    category: ErrorCategory,
    severity: ErrorSeverity = ErrorSeverity.MEDIUM,
    retry: bool = False,
    default_return: Any = None,
):
    """Decorator for handling exceptions."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if args and hasattr(args[0], "exception_handler"):
                handler = args[0].exception_handler

                if retry:
                    return handler.retry_with_backoff(func, category, *args, **kwargs)
                else:
                    return handler.safe_execute(
                        lambda: func(*args, **kwargs),
                        category,
                        severity,
                        {"function": func.__name__},
                        default_return,
                    )
            else:
                # If no exception_handler is found, execute the function directly
                return func(*args, **kwargs)

        return wrapper

    return decorator
