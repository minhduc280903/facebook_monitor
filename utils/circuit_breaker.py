#!/usr/bin/env python3
"""
Circuit Breaker Pattern Implementation for Facebook Post Monitor
🔧 PRODUCTION FIX: Prevents cascade failures and implements graceful degradation

Purpose:
- Protect system from cascade failures
- Implement exponential backoff
- Provide graceful degradation
- Monitor service health
- Automatic recovery mechanisms
"""

import time
import logging
from logging_config import get_logger, setup_application_logging
import asyncio
from typing import Optional, Callable, Any, Dict
from enum import Enum
from dataclasses import dataclass
from threading import Lock

logger = get_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "CLOSED"      # Normal operation
    OPEN = "OPEN"          # Circuit is open, failing fast
    HALF_OPEN = "HALF_OPEN"  # Testing if service is back


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5
    recovery_timeout: int = 60
    success_threshold: int = 3  # For half-open state
    timeout: int = 30


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open"""
    pass


class CircuitBreaker:
    """
    🔧 PRODUCTION-GRADE Circuit Breaker Implementation

    Features:
    - Automatic failure detection
    - Exponential backoff
    - Graceful degradation
    - Health monitoring
    - Thread-safe operations
    """

    def __init__(self, name: str, config: Optional[CircuitBreakerConfig] = None):
        """
        Initialize circuit breaker

        Args:
            name: Unique name for this circuit breaker
            config: Configuration parameters
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()

        # State management
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.next_attempt_time: Optional[float] = None

        # Thread safety
        self.lock = Lock()

        # Metrics
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0

        logger.info(f"🛡️ Circuit Breaker '{name}' initialized with threshold: {self.config.failure_threshold}")

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerError: When circuit is open
        """
        with self.lock:
            self.total_calls += 1

            # Check if circuit should be open
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                    logger.info(f"🔄 Circuit '{self.name}' moved to HALF_OPEN state")
                else:
                    logger.debug(f"🚫 Circuit '{self.name}' is OPEN, failing fast")
                    raise CircuitBreakerError(f"Circuit breaker '{self.name}' is OPEN")

        # Execute function
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result

        except Exception:
            self._on_failure()
            raise

    async def call_async(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute async function with circuit breaker protection

        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerError: When circuit is open
        """
        with self.lock:
            self.total_calls += 1

            # Check if circuit should be open
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                    logger.info(f"🔄 Circuit '{self.name}' moved to HALF_OPEN state")
                else:
                    logger.debug(f"🚫 Circuit '{self.name}' is OPEN, failing fast")
                    raise CircuitBreakerError(f"Circuit breaker '{self.name}' is OPEN")

        # Execute async function
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result

        except Exception:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if circuit should attempt to reset"""
        if self.last_failure_time is None:
            return True

        return time.time() - self.last_failure_time >= self.config.recovery_timeout

    def _on_success(self):
        """Handle successful function execution"""
        with self.lock:
            self.successful_calls += 1

            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    logger.info(f"✅ Circuit '{self.name}' CLOSED after {self.success_count} successes")

            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0  # Reset failure count on success

    def _on_failure(self):
        """Handle failed function execution"""
        with self.lock:
            self.failed_calls += 1
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.CLOSED or self.state == CircuitState.HALF_OPEN:
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.error(f"🔴 Circuit '{self.name}' OPENED after {self.failure_count} failures")

    def get_state(self) -> CircuitState:
        """Get current circuit state"""
        return self.state

    def get_metrics(self) -> Dict[str, Any]:
        """Get circuit breaker metrics"""
        with self.lock:
            success_rate = (self.successful_calls / self.total_calls * 100) if self.total_calls > 0 else 0

            return {
                "name": self.name,
                "state": self.state.value,
                "total_calls": self.total_calls,
                "successful_calls": self.successful_calls,
                "failed_calls": self.failed_calls,
                "success_rate": round(success_rate, 2),
                "failure_count": self.failure_count,
                "last_failure_time": self.last_failure_time
            }

    def reset(self):
        """Manually reset circuit breaker to CLOSED state"""
        with self.lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
            logger.info(f"🔄 Circuit '{self.name}' manually reset to CLOSED")


class ExponentialBackoff:
    """
    🔧 PRODUCTION FIX: Exponential backoff implementation
    Prevents thundering herd problems
    """

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0, multiplier: float = 2.0):
        """
        Initialize exponential backoff

        Args:
            base_delay: Base delay in seconds
            max_delay: Maximum delay in seconds
            multiplier: Backoff multiplier
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.attempt = 0

    def get_delay(self) -> float:
        """Get delay for current attempt"""
        delay = min(self.base_delay * (self.multiplier ** self.attempt), self.max_delay)
        self.attempt += 1
        return delay

    def reset(self):
        """Reset backoff to initial state"""
        self.attempt = 0

    async def wait(self):
        """Async wait with current delay"""
        delay = self.get_delay()
        logger.debug(f"⏳ Exponential backoff: waiting {delay:.2f}s (attempt {self.attempt})")
        await asyncio.sleep(delay)


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers
    """

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = Lock()

    def get_breaker(self, name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
        """Get or create circuit breaker"""
        with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, config)
            return self._breakers[name]

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics for all circuit breakers"""
        with self._lock:
            return {name: breaker.get_metrics() for name, breaker in self._breakers.items()}

    def reset_all(self):
        """Reset all circuit breakers"""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()


# Global registry instance
circuit_breaker_registry = CircuitBreakerRegistry()


def circuit_breaker(name: str, config: Optional[CircuitBreakerConfig] = None):
    """
    Decorator for circuit breaker protection

    Args:
        name: Circuit breaker name
        config: Configuration
    """
    def decorator(func: Callable):
        breaker = circuit_breaker_registry.get_breaker(name, config)

        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                return await breaker.call_async(func, *args, **kwargs)
            return async_wrapper
        else:
            def sync_wrapper(*args, **kwargs):
                return breaker.call(func, *args, **kwargs)
            return sync_wrapper

    return decorator


# Test function
async def test_circuit_breaker():
    """Test circuit breaker functionality"""
    logger.info("🧪 Testing Circuit Breaker...")

    # Create test circuit breaker
    config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=5)
    breaker = CircuitBreaker("test_service", config)

    # Test function that fails
    def failing_function():
        raise Exception("Simulated failure")

    # Test function that succeeds
    def succeeding_function():
        return "Success!"

    try:
        # Test failures
        for i in range(5):
            try:
                breaker.call(failing_function)
            except Exception as e:
                logger.info(f"Attempt {i+1}: {e}")

        # Should be open now
        logger.info(f"Circuit state: {breaker.get_state()}")
        logger.info(f"Metrics: {breaker.get_metrics()}")

        # Wait for recovery
        await asyncio.sleep(6)

        # Test recovery
        result = breaker.call(succeeding_function)
        logger.info(f"Recovery success: {result}")
        logger.info(f"Final metrics: {breaker.get_metrics()}")

    except CircuitBreakerError as e:
        logger.info(f"Circuit breaker blocked call: {e}")


if __name__ == "__main__":
    setup_application_logging()
    test_logger = get_logger(__name__, level="DEBUG")
    asyncio.run(test_circuit_breaker())
