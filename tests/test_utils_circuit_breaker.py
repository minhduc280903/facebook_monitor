#!/usr/bin/env python3
"""
Comprehensive tests for Circuit Breaker Pattern Implementation
Tests failure detection, state transitions, and recovery mechanisms
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock
from typing import Any, Callable

# Setup path for imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import circuit breaker components
from utils.circuit_breaker import (
    CircuitBreaker, CircuitState, CircuitBreakerConfig, CircuitBreakerError,
    AsyncCircuitBreaker, CircuitBreakerMetrics
)


@pytest.mark.unit
class TestCircuitBreakerConfig:
    """Test cases for CircuitBreakerConfig"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = CircuitBreakerConfig()
        
        assert config.failure_threshold == 5
        assert config.recovery_timeout == 60
        assert config.success_threshold == 3
        assert config.timeout == 30
    
    def test_custom_config(self):
        """Test custom configuration values"""
        config = CircuitBreakerConfig(
            failure_threshold=10,
            recovery_timeout=120,
            success_threshold=5,
            timeout=45
        )
        
        assert config.failure_threshold == 10
        assert config.recovery_timeout == 120
        assert config.success_threshold == 5
        assert config.timeout == 45


@pytest.mark.unit
class TestCircuitBreakerStates:
    """Test circuit breaker state transitions"""
    
    def test_circuit_state_enum(self):
        """Test CircuitState enum values"""
        assert CircuitState.CLOSED.value == "CLOSED"
        assert CircuitState.OPEN.value == "OPEN"
        assert CircuitState.HALF_OPEN.value == "HALF_OPEN"


@pytest.mark.unit
class TestCircuitBreaker:
    """Test cases for synchronous CircuitBreaker"""
    
    @pytest.fixture
    def circuit_breaker(self):
        """Create CircuitBreaker with fast recovery for testing"""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=1,  # 1 second for fast testing
            success_threshold=2,
            timeout=5
        )
        return CircuitBreaker("test_service", config)
    
    @pytest.fixture
    def mock_function(self):
        """Mock function for testing circuit breaker"""
        return Mock(return_value="success")
    
    def test_initialization(self, circuit_breaker):
        """Test circuit breaker initialization"""
        assert circuit_breaker.name == "test_service"
        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.failure_count == 0
        assert circuit_breaker.success_count == 0
        assert circuit_breaker.last_failure_time is None
    
    def test_successful_call_closed_state(self, circuit_breaker, mock_function):
        """Test successful function call in CLOSED state"""
        result = circuit_breaker.call(mock_function)
        
        assert result == "success"
        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.failure_count == 0
        mock_function.assert_called_once()
    
    def test_failed_call_closed_state(self, circuit_breaker):
        """Test failed function call in CLOSED state"""
        failing_function = Mock(side_effect=Exception("Service error"))
        
        with pytest.raises(Exception) as exc_info:
            circuit_breaker.call(failing_function)
        
        assert str(exc_info.value) == "Service error"
        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.failure_count == 1
        assert circuit_breaker.last_failure_time is not None
    
    def test_transition_to_open_state(self, circuit_breaker):
        """Test transition from CLOSED to OPEN state after failures"""
        failing_function = Mock(side_effect=Exception("Service error"))
        
        # Generate failures to reach threshold
        for i in range(3):  # failure_threshold = 3
            with pytest.raises(Exception):
                circuit_breaker.call(failing_function)
            
            if i < 2:  # Before threshold
                assert circuit_breaker.state == CircuitState.CLOSED
            else:  # At threshold
                assert circuit_breaker.state == CircuitState.OPEN
        
        assert circuit_breaker.failure_count == 3
    
    def test_fast_fail_in_open_state(self, circuit_breaker):
        """Test fast failure when circuit is OPEN"""
        # Force circuit to OPEN state
        circuit_breaker._state = CircuitState.OPEN
        circuit_breaker._failure_count = 5
        circuit_breaker._last_failure_time = time.time()
        
        mock_function = Mock()
        
        with pytest.raises(CircuitBreakerError) as exc_info:
            circuit_breaker.call(mock_function)
        
        assert "Circuit breaker is OPEN" in str(exc_info.value)
        # Function should not be called when circuit is open
        mock_function.assert_not_called()
    
    def test_transition_to_half_open(self, circuit_breaker):
        """Test transition from OPEN to HALF_OPEN after recovery timeout"""
        # Force circuit to OPEN state
        circuit_breaker._state = CircuitState.OPEN
        circuit_breaker._failure_count = 5
        circuit_breaker._last_failure_time = time.time() - 2  # 2 seconds ago (> recovery_timeout)
        
        successful_function = Mock(return_value="recovered")
        
        result = circuit_breaker.call(successful_function)
        
        assert result == "recovered"
        assert circuit_breaker.state == CircuitState.HALF_OPEN
        assert circuit_breaker.success_count == 1
        successful_function.assert_called_once()
    
    def test_recovery_from_half_open_to_closed(self, circuit_breaker):
        """Test recovery from HALF_OPEN to CLOSED after successful calls"""
        # Set to HALF_OPEN state
        circuit_breaker._state = CircuitState.HALF_OPEN
        circuit_breaker._success_count = 1
        
        successful_function = Mock(return_value="success")
        
        # One more success should close the circuit (success_threshold = 2)
        result = circuit_breaker.call(successful_function)
        
        assert result == "success"
        assert circuit_breaker.state == CircuitState.CLOSED
        assert circuit_breaker.failure_count == 0
        assert circuit_breaker.success_count == 0
    
    def test_half_open_failure_back_to_open(self, circuit_breaker):
        """Test transition from HALF_OPEN back to OPEN on failure"""
        # Set to HALF_OPEN state
        circuit_breaker._state = CircuitState.HALF_OPEN
        circuit_breaker._success_count = 1
        
        failing_function = Mock(side_effect=Exception("Still failing"))
        
        with pytest.raises(Exception):
            circuit_breaker.call(failing_function)
        
        assert circuit_breaker.state == CircuitState.OPEN
        assert circuit_breaker.failure_count == 1
        assert circuit_breaker.success_count == 0
    
    def test_timeout_handling(self):
        """Test function timeout handling"""
        config = CircuitBreakerConfig(timeout=1)  # 1 second timeout
        cb = CircuitBreaker("timeout_test", config)
        
        def slow_function():
            time.sleep(2)  # Longer than timeout
            return "slow_result"
        
        with pytest.raises(Exception):  # Should timeout
            cb.call(slow_function)
        
        assert cb.failure_count == 1
    
    def test_metrics_collection(self, circuit_breaker):
        """Test that metrics are collected properly"""
        successful_function = Mock(return_value="success")
        failing_function = Mock(side_effect=Exception("error"))
        
        # Some successful calls
        for _ in range(3):
            circuit_breaker.call(successful_function)
        
        # Some failed calls
        for _ in range(2):
            with pytest.raises(Exception):
                circuit_breaker.call(failing_function)
        
        metrics = circuit_breaker.get_metrics()
        
        assert metrics.name == "test_service"
        assert metrics.state == circuit_breaker.state
        assert metrics.failure_count == 2
        assert metrics.total_calls >= 5
        assert metrics.success_rate < 1.0


@pytest.mark.unit  
class TestAsyncCircuitBreaker:
    """Test cases for asynchronous CircuitBreaker"""
    
    @pytest.fixture
    def async_circuit_breaker(self):
        """Create AsyncCircuitBreaker with fast recovery for testing"""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            recovery_timeout=1,
            success_threshold=2,
            timeout=5
        )
        return AsyncCircuitBreaker("async_test_service", config)
    
    @pytest.mark.asyncio
    async def test_async_successful_call(self, async_circuit_breaker):
        """Test successful async function call"""
        async def async_success():
            return "async_success"
        
        result = await async_circuit_breaker.call(async_success())
        
        assert result == "async_success"
        assert async_circuit_breaker.state == CircuitState.CLOSED
        assert async_circuit_breaker.failure_count == 0
    
    @pytest.mark.asyncio
    async def test_async_failed_call(self, async_circuit_breaker):
        """Test failed async function call"""
        async def async_failure():
            raise Exception("Async service error")
        
        with pytest.raises(Exception) as exc_info:
            await async_circuit_breaker.call(async_failure())
        
        assert str(exc_info.value) == "Async service error"
        assert async_circuit_breaker.failure_count == 1
    
    @pytest.mark.asyncio
    async def test_async_circuit_opens(self, async_circuit_breaker):
        """Test async circuit opens after failures"""
        async def async_failure():
            raise Exception("Persistent failure")
        
        # Generate failures to reach threshold
        for i in range(3):
            with pytest.raises(Exception):
                await async_circuit_breaker.call(async_failure())
        
        assert async_circuit_breaker.state == CircuitState.OPEN
    
    @pytest.mark.asyncio
    async def test_async_timeout_handling(self):
        """Test async timeout handling"""
        config = CircuitBreakerConfig(timeout=1)
        cb = AsyncCircuitBreaker("async_timeout_test", config)
        
        async def slow_async_function():
            await asyncio.sleep(2)  # Longer than timeout
            return "slow_result"
        
        with pytest.raises(asyncio.TimeoutError):
            await cb.call(slow_async_function())
        
        assert cb.failure_count == 1
    
    @pytest.mark.asyncio
    async def test_async_recovery_flow(self, async_circuit_breaker):
        """Test complete async recovery flow"""
        async def failing_function():
            raise Exception("Service down")
        
        async def recovery_function():
            return "service_recovered"
        
        # Break the circuit
        for _ in range(3):
            with pytest.raises(Exception):
                await async_circuit_breaker.call(failing_function())
        
        assert async_circuit_breaker.state == CircuitState.OPEN
        
        # Wait for recovery timeout
        await asyncio.sleep(1.1)
        
        # Should transition to HALF_OPEN and then CLOSED
        result1 = await async_circuit_breaker.call(recovery_function())
        assert result1 == "service_recovered"
        assert async_circuit_breaker.state == CircuitState.HALF_OPEN
        
        result2 = await async_circuit_breaker.call(recovery_function())
        assert result2 == "service_recovered"
        assert async_circuit_breaker.state == CircuitState.CLOSED


@pytest.mark.integration
class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker with real scenarios"""
    
    def test_database_connection_simulation(self):
        """Test circuit breaker with simulated database connection failures"""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=1,
            success_threshold=1
        )
        db_circuit = CircuitBreaker("database", config)
        
        # Simulate database connection function
        db_calls = 0
        def connect_to_db():
            nonlocal db_calls
            db_calls += 1
            if db_calls <= 3:  # First 3 calls fail
                raise Exception("Database connection failed")
            return "Connected"
        
        # First failure
        with pytest.raises(Exception):
            db_circuit.call(connect_to_db)
        assert db_circuit.state == CircuitState.CLOSED
        
        # Second failure - should open circuit
        with pytest.raises(Exception):
            db_circuit.call(connect_to_db)
        assert db_circuit.state == CircuitState.OPEN
        
        # Fast fail while open
        with pytest.raises(CircuitBreakerError):
            db_circuit.call(connect_to_db)
        
        # Wait for recovery
        time.sleep(1.1)
        
        # Should recover
        result = db_circuit.call(connect_to_db)
        assert result == "Connected"
        assert db_circuit.state == CircuitState.CLOSED
    
    def test_api_service_simulation(self):
        """Test circuit breaker with simulated API service calls"""
        api_circuit = CircuitBreaker("external_api", CircuitBreakerConfig())
        
        api_responses = ["error", "error", "error", "error", "error", "success"]
        call_count = 0
        
        def call_external_api():
            nonlocal call_count
            response = api_responses[min(call_count, len(api_responses) - 1)]
            call_count += 1
            
            if response == "error":
                raise Exception("API unavailable")
            return {"status": "success", "data": "api_data"}
        
        # Generate failures to open circuit
        for _ in range(5):
            with pytest.raises(Exception):
                api_circuit.call(call_external_api)
        
        assert api_circuit.state == CircuitState.OPEN
        
        # Fast fails while open
        with pytest.raises(CircuitBreakerError):
            api_circuit.call(call_external_api)
    
    @pytest.mark.asyncio
    async def test_microservice_communication(self):
        """Test circuit breaker for microservice communication"""
        service_circuit = AsyncCircuitBreaker("user_service", CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=1
        ))
        
        service_healthy = False
        
        async def call_user_service():
            if not service_healthy:
                raise Exception("User service unavailable")
            return {"user_id": 123, "username": "testuser"}
        
        # Service is down
        with pytest.raises(Exception):
            await service_circuit.call(call_user_service())
        
        with pytest.raises(Exception):
            await service_circuit.call(call_user_service())
        
        assert service_circuit.state == CircuitState.OPEN
        
        # Service recovers
        service_healthy = True
        await asyncio.sleep(1.1)
        
        result = await service_circuit.call(call_user_service())
        assert result["username"] == "testuser"


@pytest.mark.unit
class TestCircuitBreakerMetrics:
    """Test circuit breaker metrics collection"""
    
    def test_metrics_initialization(self):
        """Test metrics object initialization"""
        metrics = CircuitBreakerMetrics(
            name="test_service",
            state=CircuitState.CLOSED,
            failure_count=0,
            total_calls=0,
            success_rate=1.0,
            last_failure_time=None
        )
        
        assert metrics.name == "test_service"
        assert metrics.state == CircuitState.CLOSED
        assert metrics.failure_count == 0
        assert metrics.total_calls == 0
        assert metrics.success_rate == 1.0
        assert metrics.last_failure_time is None
    
    def test_metrics_calculation(self):
        """Test metrics calculation with various scenarios"""
        circuit_breaker = CircuitBreaker("metrics_test", CircuitBreakerConfig())
        
        # Simulate calls
        successful_calls = 7
        failed_calls = 3
        
        # Mock the internal counters
        circuit_breaker._total_calls = successful_calls + failed_calls
        circuit_breaker._successful_calls = successful_calls
        circuit_breaker._failure_count = failed_calls
        
        metrics = circuit_breaker.get_metrics()
        
        assert metrics.total_calls == 10
        assert metrics.failure_count == 3
        assert abs(metrics.success_rate - 0.7) < 0.01  # 7/10 = 0.7


@pytest.mark.unit
class TestCircuitBreakerEdgeCases:
    """Test edge cases and error scenarios"""
    
    def test_zero_thresholds(self):
        """Test circuit breaker with zero thresholds"""
        config = CircuitBreakerConfig(
            failure_threshold=1,  # Minimum 1
            success_threshold=1   # Minimum 1
        )
        cb = CircuitBreaker("edge_case", config)
        
        # Should work normally
        assert cb.config.failure_threshold == 1
        assert cb.config.success_threshold == 1
    
    def test_very_short_timeout(self):
        """Test with very short timeout"""
        config = CircuitBreakerConfig(timeout=0.1)  # 100ms
        cb = CircuitBreaker("short_timeout", config)
        
        def quick_function():
            return "quick"
        
        # Should succeed with quick function
        result = cb.call(quick_function)
        assert result == "quick"
    
    def test_thread_safety(self):
        """Test thread safety of circuit breaker"""
        import threading
        
        circuit_breaker = CircuitBreaker("thread_test", CircuitBreakerConfig())
        results = []
        errors = []
        
        def worker():
            try:
                result = circuit_breaker.call(lambda: "thread_result")
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = [threading.Thread(target=worker) for _ in range(10)]
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # All should succeed
        assert len(results) == 10
        assert len(errors) == 0
        assert all(r == "thread_result" for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
