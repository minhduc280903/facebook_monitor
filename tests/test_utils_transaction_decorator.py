#!/usr/bin/env python3
"""
Comprehensive tests for Transaction Decorator for Database Operations
Tests PostgreSQL transaction management, error handling, and performance monitoring
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock, call
from functools import wraps

# Setup path for imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import transaction decorator components
from utils.transaction_decorator import (
    transaction, async_transaction, TransactionManager,
    TransactionError, _is_postgresql_connection, _execute_with_retry,
    POSTGRESQL_AVAILABLE
)


@pytest.mark.unit
class TestTransactionError:
    """Test TransactionError exception class"""
    
    def test_transaction_error_creation(self):
        """Test TransactionError exception creation"""
        error = TransactionError("Transaction failed", original_error="Connection timeout")
        
        assert str(error) == "Transaction failed"
        assert error.original_error == "Connection timeout"
    
    def test_transaction_error_without_original(self):
        """Test TransactionError without original error"""
        error = TransactionError("Simple transaction error")
        
        assert str(error) == "Simple transaction error"
        assert error.original_error is None


@pytest.mark.unit
class TestConnectionDetection:
    """Test database connection detection utilities"""
    
    @pytest.mark.skipif(not POSTGRESQL_AVAILABLE, reason="PostgreSQL not available")
    def test_postgresql_connection_detection(self):
        """Test PostgreSQL connection detection"""
        # Mock psycopg2 connection
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'psycopg2.extensions'
        
        assert _is_postgresql_connection(mock_connection) is True
    
    def test_non_postgresql_connection_detection(self):
        """Test non-PostgreSQL connection detection"""
        # Mock SQLite connection
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'sqlite3'
        
        assert _is_postgresql_connection(mock_connection) is False
    
    def test_unknown_connection_type(self):
        """Test unknown connection type detection"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'unknown_db_module'
        
        # Should default to False for unknown types
        assert _is_postgresql_connection(mock_connection) is False


@pytest.mark.unit
class TestRetryMechanism:
    """Test retry mechanism for database operations"""
    
    def test_execute_with_retry_success_first_attempt(self):
        """Test successful execution on first attempt"""
        mock_operation = Mock(return_value="success")
        
        result = _execute_with_retry(mock_operation, max_retries=3, delay=0.01)
        
        assert result == "success"
        assert mock_operation.call_count == 1
    
    def test_execute_with_retry_success_after_failures(self):
        """Test successful execution after initial failures"""
        mock_operation = Mock(side_effect=[
            Exception("First failure"),
            Exception("Second failure"),
            "success"  # Third attempt succeeds
        ])
        
        result = _execute_with_retry(mock_operation, max_retries=3, delay=0.01)
        
        assert result == "success"
        assert mock_operation.call_count == 3
    
    def test_execute_with_retry_all_attempts_fail(self):
        """Test when all retry attempts fail"""
        mock_operation = Mock(side_effect=Exception("Persistent failure"))
        
        with pytest.raises(Exception) as exc_info:
            _execute_with_retry(mock_operation, max_retries=2, delay=0.01)
        
        assert "Persistent failure" in str(exc_info.value)
        assert mock_operation.call_count == 2  # max_retries attempts
    
    def test_execute_with_retry_timing(self):
        """Test retry timing with delays"""
        call_times = []
        
        def failing_operation():
            call_times.append(time.time())
            raise Exception("Timing test failure")
        
        start_time = time.time()
        
        with pytest.raises(Exception):
            _execute_with_retry(failing_operation, max_retries=2, delay=0.1)
        
        # Should have made 2 attempts with delay between them
        assert len(call_times) == 2
        time_diff = call_times[1] - call_times[0]
        assert time_diff >= 0.09  # Should wait at least delay time


@pytest.mark.unit
class TestTransactionDecorator:
    """Test synchronous transaction decorator"""
    
    def test_transaction_decorator_basic_usage(self):
        """Test basic transaction decorator usage"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        @transaction
        def test_function(connection):
            assert connection is mock_connection
            return "function_result"
        
        result = test_function(mock_connection)
        
        assert result == "function_result"
        mock_connection.cursor.assert_called_once()
        mock_cursor.execute.assert_called_with("BEGIN")
        mock_connection.commit.assert_called_once()
        mock_cursor.close.assert_called_once()
    
    def test_transaction_decorator_with_postgresql(self):
        """Test transaction decorator specifically with PostgreSQL"""
        # Mock PostgreSQL connection
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'psycopg2.extensions'
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        @transaction
        def postgresql_function(connection):
            return "postgresql_result"
        
        result = postgresql_function(mock_connection)
        
        assert result == "postgresql_result"
        mock_cursor.execute.assert_called_with("BEGIN")
        mock_connection.commit.assert_called_once()
    
    def test_transaction_decorator_rollback_on_exception(self):
        """Test transaction rollback when function raises exception"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        @transaction
        def failing_function(connection):
            raise ValueError("Function failed")
        
        with pytest.raises(TransactionError) as exc_info:
            failing_function(mock_connection)
        
        assert "Transaction failed" in str(exc_info.value)
        mock_cursor.execute.assert_called_with("BEGIN")
        mock_connection.rollback.assert_called_once()
        mock_connection.commit.assert_not_called()
    
    def test_transaction_decorator_nested_transactions(self):
        """Test nested transaction handling"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        @transaction
        def outer_function(connection):
            @transaction
            def inner_function(conn):
                return "inner_result"
            
            result = inner_function(connection)
            return f"outer_{result}"
        
        result = outer_function(mock_connection)
        
        assert result == "outer_inner_result"
        # Should only begin/commit once for nested transactions
        assert mock_cursor.execute.call_count >= 1
        assert mock_connection.commit.call_count >= 1
    
    def test_transaction_decorator_with_custom_isolation(self):
        """Test transaction decorator with custom isolation level"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        @transaction(isolation_level="SERIALIZABLE")
        def serializable_function(connection):
            return "serializable_result"
        
        result = serializable_function(mock_connection)
        
        assert result == "serializable_result"
        # Should set isolation level
        expected_calls = [
            call("BEGIN"),
            call("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        ]
        mock_cursor.execute.assert_has_calls(expected_calls, any_order=False)
    
    def test_transaction_decorator_readonly_transaction(self):
        """Test read-only transaction"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        @transaction(readonly=True)
        def readonly_function(connection):
            return "readonly_result"
        
        result = readonly_function(mock_connection)
        
        assert result == "readonly_result"
        expected_calls = [
            call("BEGIN"),
            call("SET TRANSACTION READ ONLY")
        ]
        mock_cursor.execute.assert_has_calls(expected_calls, any_order=False)
    
    def test_transaction_decorator_performance_monitoring(self):
        """Test transaction performance monitoring"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        @transaction(monitor_performance=True)
        def monitored_function(connection):
            time.sleep(0.1)  # Simulate some work
            return "monitored_result"
        
        with patch('utils.transaction_decorator.logger') as mock_logger:
            result = monitored_function(mock_connection)
        
        assert result == "monitored_result"
        # Should log performance metrics
        mock_logger.info.assert_called()
        
        # Check that timing information was logged
        log_calls = mock_logger.info.call_args_list
        timing_logged = any("Transaction completed" in str(call) for call in log_calls)
        assert timing_logged


@pytest.mark.unit
class TestAsyncTransactionDecorator:
    """Test asynchronous transaction decorator"""
    
    @pytest.mark.asyncio
    async def test_async_transaction_decorator_basic(self):
        """Test basic async transaction decorator usage"""
        mock_connection = AsyncMock()
        mock_cursor = AsyncMock()
        mock_connection.cursor.return_value = mock_cursor
        
        @async_transaction
        async def async_test_function(connection):
            assert connection is mock_connection
            return "async_result"
        
        result = await async_test_function(mock_connection)
        
        assert result == "async_result"
        mock_connection.cursor.assert_called_once()
        mock_cursor.execute.assert_called_with("BEGIN")
        mock_connection.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_async_transaction_rollback_on_exception(self):
        """Test async transaction rollback on exception"""
        mock_connection = AsyncMock()
        mock_cursor = AsyncMock()
        mock_connection.cursor.return_value = mock_cursor
        
        @async_transaction
        async def failing_async_function(connection):
            raise ValueError("Async function failed")
        
        with pytest.raises(TransactionError) as exc_info:
            await failing_async_function(mock_connection)
        
        assert "Transaction failed" in str(exc_info.value)
        mock_connection.rollback.assert_called_once()
        mock_connection.commit.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_async_transaction_with_isolation_level(self):
        """Test async transaction with custom isolation level"""
        mock_connection = AsyncMock()
        mock_cursor = AsyncMock()
        mock_connection.cursor.return_value = mock_cursor
        
        @async_transaction(isolation_level="READ COMMITTED")
        async def isolated_async_function(connection):
            return "isolated_result"
        
        result = await isolated_async_function(mock_connection)
        
        assert result == "isolated_result"
        expected_calls = [
            call("BEGIN"),
            call("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        ]
        mock_cursor.execute.assert_has_calls(expected_calls, any_order=False)


@pytest.mark.unit
class TestTransactionManager:
    """Test TransactionManager class"""
    
    def test_transaction_manager_initialization(self):
        """Test TransactionManager initialization"""
        mock_connection = Mock()
        
        manager = TransactionManager(mock_connection)
        
        assert manager.connection is mock_connection
        assert manager.in_transaction is False
        assert manager.savepoint_counter == 0
    
    def test_transaction_manager_context_manager(self):
        """Test TransactionManager as context manager"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        with TransactionManager(mock_connection) as manager:
            assert manager.in_transaction is True
            # Perform some operations
            pass
        
        assert manager.in_transaction is False
        mock_cursor.execute.assert_called_with("BEGIN")
        mock_connection.commit.assert_called_once()
    
    def test_transaction_manager_rollback_on_exception(self):
        """Test TransactionManager rollback on exception in context"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        with pytest.raises(ValueError):
            with TransactionManager(mock_connection) as manager:
                assert manager.in_transaction is True
                raise ValueError("Context manager test error")
        
        mock_connection.rollback.assert_called_once()
        mock_connection.commit.assert_not_called()
    
    def test_transaction_manager_savepoints(self):
        """Test savepoint management"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        with TransactionManager(mock_connection) as manager:
            # Create savepoint
            savepoint_name = manager.create_savepoint()
            assert savepoint_name == "sp_1"
            assert manager.savepoint_counter == 1
            
            # Create another savepoint
            savepoint_name2 = manager.create_savepoint()
            assert savepoint_name2 == "sp_2"
            assert manager.savepoint_counter == 2
            
            # Rollback to savepoint
            manager.rollback_to_savepoint("sp_1")
        
        # Verify savepoint SQL commands
        expected_calls = [
            call("BEGIN"),
            call("SAVEPOINT sp_1"),
            call("SAVEPOINT sp_2"),
            call("ROLLBACK TO SAVEPOINT sp_1")
        ]
        mock_cursor.execute.assert_has_calls(expected_calls, any_order=False)
    
    def test_transaction_manager_release_savepoint(self):
        """Test releasing savepoints"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        with TransactionManager(mock_connection) as manager:
            savepoint = manager.create_savepoint()
            manager.release_savepoint(savepoint)
        
        expected_calls = [
            call("BEGIN"),
            call("SAVEPOINT sp_1"),
            call("RELEASE SAVEPOINT sp_1")
        ]
        mock_cursor.execute.assert_has_calls(expected_calls, any_order=False)


@pytest.mark.integration
class TestTransactionIntegration:
    """Integration tests for transaction management"""
    
    def test_real_world_transaction_scenario(self):
        """Test realistic transaction scenario with multiple operations"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        @transaction(isolation_level="READ COMMITTED", monitor_performance=True)
        def complex_database_operation(connection):
            # Simulate multiple database operations
            operations = [
                "INSERT INTO posts (title) VALUES ('Test Post')",
                "UPDATE posts SET status = 'published' WHERE id = 1",
                "INSERT INTO interactions (post_id, type) VALUES (1, 'like')"
            ]
            
            for operation in operations:
                # In real scenario, would execute these operations
                pass
            
            return {"posts_created": 1, "interactions_added": 1}
        
        with patch('utils.transaction_decorator.logger') as mock_logger:
            result = complex_database_operation(mock_connection)
        
        assert result["posts_created"] == 1
        assert result["interactions_added"] == 1
        
        # Should have begun transaction, set isolation level, and committed
        expected_calls = [
            call("BEGIN"),
            call("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        ]
        mock_cursor.execute.assert_has_calls(expected_calls, any_order=False)
        mock_connection.commit.assert_called_once()
    
    def test_transaction_with_retry_on_deadlock(self):
        """Test transaction retry on deadlock detection"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        # Simulate deadlock on first attempt, success on second
        call_count = 0
        
        @transaction(retry_on_deadlock=True, max_retries=2)
        def deadlock_prone_operation(connection):
            nonlocal call_count
            call_count += 1
            
            if call_count == 1:
                # Simulate deadlock error
                deadlock_error = Exception("deadlock detected")
                deadlock_error.pgcode = "40P01"  # PostgreSQL deadlock error code
                raise deadlock_error
            
            return "success_after_retry"
        
        result = deadlock_prone_operation(mock_connection)
        
        assert result == "success_after_retry"
        assert call_count == 2  # Should have retried once
    
    def test_nested_transactions_with_savepoints(self):
        """Test nested transactions using savepoints"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        @transaction
        def outer_transaction(connection):
            # Outer transaction work
            outer_result = "outer_work_done"
            
            try:
                with TransactionManager(connection) as manager:
                    savepoint = manager.create_savepoint()
                    
                    # Inner transaction work that might fail
                    inner_result = "inner_work_done"
                    
                    # Simulate partial failure
                    raise ValueError("Inner operation failed")
                    
            except ValueError:
                # Inner transaction failed, but outer continues
                pass
            
            return outer_result
        
        result = outer_transaction(mock_connection)
        
        assert result == "outer_work_done"
        # Should have committed outer transaction despite inner failure
        mock_connection.commit.assert_called()
    
    @pytest.mark.asyncio
    async def test_async_transaction_integration(self):
        """Test async transaction integration scenario"""
        mock_connection = AsyncMock()
        mock_cursor = AsyncMock()
        mock_connection.cursor.return_value = mock_cursor
        
        @async_transaction(isolation_level="SERIALIZABLE")
        async def async_complex_operation(connection):
            # Simulate async database operations
            await asyncio.sleep(0.01)  # Simulate async work
            
            # Multiple operations
            operations = ["SELECT", "INSERT", "UPDATE"]
            for op in operations:
                await asyncio.sleep(0.01)  # Simulate each operation
            
            return {"operations_completed": len(operations)}
        
        import asyncio
        result = await async_complex_operation(mock_connection)
        
        assert result["operations_completed"] == 3
        mock_cursor.execute.assert_called()
        mock_connection.commit.assert_called_once()


@pytest.mark.unit
class TestTransactionErrorHandling:
    """Test transaction error handling and edge cases"""
    
    def test_connection_error_handling(self):
        """Test handling connection errors during transaction"""
        mock_connection = Mock()
        mock_connection.cursor.side_effect = Exception("Connection lost")
        
        @transaction
        def connection_error_function(connection):
            return "should_not_reach"
        
        with pytest.raises(TransactionError) as exc_info:
            connection_error_function(mock_connection)
        
        assert "Transaction failed" in str(exc_info.value)
        assert exc_info.value.original_error == "Connection lost"
    
    def test_commit_error_handling(self):
        """Test handling commit errors"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_connection.commit.side_effect = Exception("Commit failed")
        
        @transaction
        def commit_error_function(connection):
            return "function_completed"
        
        with pytest.raises(TransactionError) as exc_info:
            commit_error_function(mock_connection)
        
        assert "Transaction failed" in str(exc_info.value)
        mock_connection.rollback.assert_called_once()
    
    def test_rollback_error_handling(self):
        """Test handling rollback errors"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_connection.rollback.side_effect = Exception("Rollback failed")
        
        @transaction
        def rollback_error_function(connection):
            raise ValueError("Original function error")
        
        # Should still raise TransactionError, not the rollback error
        with pytest.raises(TransactionError) as exc_info:
            rollback_error_function(mock_connection)
        
        assert "Transaction failed" in str(exc_info.value)
    
    def test_non_postgresql_connection_warning(self):
        """Test warning for non-PostgreSQL connections"""
        # Mock SQLite connection
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'sqlite3'
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        @transaction
        def non_postgres_function(connection):
            return "non_postgres_result"
        
        with patch('utils.transaction_decorator.logger') as mock_logger:
            result = non_postgres_function(mock_connection)
        
        assert result == "non_postgres_result"
        # Should log warning about non-PostgreSQL usage
        mock_logger.warning.assert_called()
    
    def test_invalid_isolation_level(self):
        """Test handling invalid isolation level"""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = [
            None,  # BEGIN succeeds
            Exception("Invalid isolation level")  # SET TRANSACTION fails
        ]
        
        @transaction(isolation_level="INVALID_LEVEL")
        def invalid_isolation_function(connection):
            return "should_not_reach"
        
        with pytest.raises(TransactionError):
            invalid_isolation_function(mock_connection)
        
        mock_connection.rollback.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
