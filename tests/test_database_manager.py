#!/usr/bin/env python3
"""
Unit Tests for DatabaseManager - Refactored for Connection Pooling

Tests for the dual-stream architecture with a focus on verifying
the correct use of the psycopg2 connection pool.
"""

import pytest
from unittest.mock import Mock, patch, ANY
from datetime import datetime, timezone, timedelta
import psycopg2.pool

# Import the module under test
from core.database_manager import DatabaseManager


@pytest.fixture
def mock_settings():
    """Provides a mock of the global settings object."""
    settings = Mock()
    settings.database.host = "pool_host"
    settings.database.port = 5433
    settings.database.user = "pool_user"
    settings.database.password = "pool_pass"
    settings.database.name = "pool_db"
    settings.database.pool_size = 5
    settings.scraping.post_tracking_days = 7
    return settings

@pytest.fixture
def db_manager_with_mocks(mock_settings):
    """
    Initializes DatabaseManager with a mocked connection pool.
    This fixture provides access to the manager and its mocks for detailed assertions.
    """
    mock_pool = Mock(spec=psycopg2.pool.SimpleConnectionPool)
    mock_connection = Mock()
    mock_cursor = Mock()

    # Configure the mock hierarchy
    mock_pool.getconn.return_value = mock_connection
    mock_connection.cursor.return_value = mock_cursor

    # Patch the SimpleConnectionPool to return our mock pool
    with patch('core.database_manager.pool.SimpleConnectionPool', return_value=mock_pool) as mock_pool_constructor:
        with patch('core.database_manager.settings', mock_settings):
            db_manager = DatabaseManager()
            # Attach mocks for easy access in tests
            db_manager.mock_pool_constructor = mock_pool_constructor
            db_manager.mock_pool = mock_pool
            db_manager.mock_connection = mock_connection
            db_manager.mock_cursor = mock_cursor
            yield db_manager

class TestDatabaseManagerRefactored:
    """Test suite for the refactored, pool-based DatabaseManager."""

    def test_initialization_with_pool(self, db_manager_with_mocks):
        """Test that DatabaseManager initializes the connection pool correctly."""
        db = db_manager_with_mocks
        settings = db.db_config

        # Assert that the pool was created with the correct parameters from settings
        db.mock_pool_constructor.assert_called_once_with(
            minconn=1,
            maxconn=settings.pool_size,
            host=settings.host,
            port=settings.port,
            user=settings.user,
            password=settings.password,
            dbname=settings.name,
            cursor_factory=ANY
        )
        # Assert that the table creation method was called
        assert db.mock_cursor.execute.call_count > 0

    def test_get_connection_context_manager(self, db_manager_with_mocks):
        """Test the get_connection context manager for acquiring and releasing connections."""
        db = db_manager_with_mocks

        with db.get_connection() as conn:
            assert conn == db.mock_connection
            db.mock_pool.getconn.assert_called_once()
            # putconn should not be called yet
            db.mock_pool.putconn.assert_not_called()
        
        # After exiting the context, putconn should be called
        db.mock_pool.putconn.assert_called_once_with(db.mock_connection)

    def test_is_post_new_returns_true_for_new_post(self, db_manager_with_mocks):
        """Test is_post_new returns True when a post does not exist."""
        db = db_manager_with_mocks
        db.mock_cursor.fetchone.return_value = None  # Simulate post not found

        assert db.is_post_new("new_sig") is True
        db.mock_cursor.execute.assert_called_once_with(ANY, ("new_sig",))

    def test_is_post_new_returns_false_for_existing_post(self, db_manager_with_mocks):
        """Test is_post_new returns False when a post exists."""
        db = db_manager_with_mocks
        db.mock_cursor.fetchone.return_value = (1,)  # Simulate post found

        assert db.is_post_new("existing_sig") is False

    def test_add_new_post_with_interaction_atomic(self, db_manager_with_mocks):
        """Test the atomic add_new_post_with_interaction method."""
        db = db_manager_with_mocks
        post_sig = "atomic_post_123"

        result = db.add_new_post_with_interaction(
            post_signature=post_sig,
            post_url="http://atomic.com/post",
            source_url="http://atomic.com/group",
            like_count=100,
            comment_count=20
        )

        assert result is True
        # Verify it was a transaction: getconn and putconn were called once
        db.mock_pool.getconn.assert_called_once()
        db.mock_pool.putconn.assert_called_once()
        # Verify commit was called on the connection
        db.mock_connection.commit.assert_called_once()

        # Verify two execute calls were made (INSERT post, INSERT interaction)
        assert db.mock_cursor.execute.call_count == 2
        
        # More detailed check of the SQL
        first_call_args = db.mock_cursor.execute.call_args_list[0].args
        assert "INSERT INTO posts" in first_call_args[0]
        assert post_sig in first_call_args[1]

        second_call_args = db.mock_cursor.execute.call_args_list[1].args
        assert "INSERT INTO interactions" in second_call_args[0]
        assert post_sig in second_call_args[1]
        assert 100 in second_call_args[1]
        assert 20 in second_call_args[1]

    def test_cleanup_old_interactions_safe_and_pooled(self, db_manager_with_mocks):
        """Test cleanup_old_interactions uses the pool and parameterized queries."""
        db = db_manager_with_mocks
        db.mock_cursor.fetchone.return_value = {'count': 50} # Simulate 50 old interactions

        deleted_count = db.cleanup_old_interactions(days_to_keep=30)

        assert deleted_count == 50
        # Check that the interval was passed as a parameter, not an f-string
        select_sql, select_params = db.mock_cursor.execute.call_args_list[0].args
        assert "%s" in select_sql
        assert "30 days" in select_params[0]

        delete_sql, delete_params = db.mock_cursor.execute.call_args_list[1].args
        assert "%s" in delete_sql
        assert "30 days" in delete_params[0]

        # Verify transactionality
        db.mock_connection.commit.assert_called_once()

    def test_get_active_tracking_posts_uses_pool(self, db_manager_with_mocks):
        """Test get_active_tracking_posts uses the connection pool."""
        db = db_manager_with_mocks
        db.mock_cursor.fetchall.return_value = [{'post_signature': 'sig1'}]

        posts = db.get_active_tracking_posts()

        assert len(posts) == 1
        assert posts[0]['post_signature'] == 'sig1'
        db.mock_pool.getconn.assert_called_once()
        db.mock_pool.putconn.assert_called_once()

    def test_close_closes_pool(self, db_manager_with_mocks):
        """Test that the close method calls closeall on the pool."""
        db = db_manager_with_mocks
        db.close()
        db.mock_pool.closeall.assert_called_once()
    
    def test_get_existing_post_signatures_batch(self, db_manager_with_mocks):
        """Test batch check for existing posts - FIX for N+1 query problem."""
        db = db_manager_with_mocks
        
        # Mock fetchall to return some existing signatures
        db.mock_cursor.fetchall.return_value = [
            {'post_signature': 'sig1'},
            {'post_signature': 'sig3'}
        ]
        
        signatures = ['sig1', 'sig2', 'sig3', 'sig4']
        existing = db.get_existing_post_signatures_batch(signatures)
        
        # Should return set of existing signatures
        assert existing == {'sig1', 'sig3'}
        
        # Verify single query with all signatures
        db.mock_cursor.execute.assert_called_once()
        sql, params = db.mock_cursor.execute.call_args[0]
        assert "WHERE post_signature = ANY(%s)" in sql
        assert params[0] == signatures
        
        # Verify pool usage
        db.mock_pool.getconn.assert_called_once()
        db.mock_pool.putconn.assert_called_once()
    
    def test_log_interactions_batch(self, db_manager_with_mocks):
        """Test batch insert interactions - FIX for N+1 query problem."""
        db = db_manager_with_mocks
        db.mock_cursor.rowcount = 3  # Simulate 3 rows inserted
        
        interactions = [
            {
                'post_signature': 'sig1',
                'log_timestamp_utc': '2025-09-30T10:00:00+00:00',
                'like_count': 10,
                'comment_count': 5
            },
            {
                'post_signature': 'sig2',
                'log_timestamp_utc': '2025-09-30T10:00:00+00:00',
                'like_count': 20,
                'comment_count': 10
            },
            {
                'post_signature': 'sig3',
                'log_timestamp_utc': '2025-09-30T10:00:00+00:00',
                'like_count': 30,
                'comment_count': 15
            }
        ]
        
        inserted_count = db.log_interactions_batch(interactions)
        
        # Should return number of inserted interactions
        assert inserted_count == 3
        
        # Verify executemany was called with batch insert
        db.mock_cursor.executemany.assert_called_once()
        sql, params = db.mock_cursor.executemany.call_args[0]
        assert "INSERT INTO interactions" in sql
        assert len(params) == 3
        
        # Verify commit
        db.mock_connection.commit.assert_called_once()
        
        # Verify pool usage
        db.mock_pool.getconn.assert_called_once()
        db.mock_pool.putconn.assert_called_once()

