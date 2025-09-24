#!/usr/bin/env python3
"""
Transaction Decorator for Database Operations - PostgreSQL Only
🔧 PRODUCTION ENHANCEMENT: Clean transaction management

Features:
- Automatic BEGIN/COMMIT/ROLLBACK handling for PostgreSQL
- Consistent error handling
- Logging integration
- Performance monitoring
"""

import time
import logging
from functools import wraps
from typing import Callable

# PostgreSQL support
try:
    import psycopg2
    POSTGRESQL_AVAILABLE = True
except ImportError:
    POSTGRESQL_AVAILABLE = False
    psycopg2 = None

logger = logging.getLogger(__name__)


def _is_postgresql_connection(connection):
    """Check if connection is PostgreSQL (psycopg2)"""
    if POSTGRESQL_AVAILABLE and psycopg2:
        return isinstance(connection, psycopg2.extensions.connection)
    return False


def _begin_transaction(cursor, connection):
    """Begin PostgreSQL transaction"""
    cursor.execute("BEGIN")


def _commit_transaction(cursor, connection):
    """Commit PostgreSQL transaction"""
    connection.commit()


def _rollback_transaction(cursor, connection):
    """Rollback PostgreSQL transaction"""
    try:
        connection.rollback()
    except Exception as e:
        if POSTGRESQL_AVAILABLE and psycopg2:
            if isinstance(e, (psycopg2.OperationalError, psycopg2.DatabaseError)):
                logger.error("❌ PostgreSQL rollback failed: %s", e)
                return
        logger.error("❌ Rollback failed: %s", e)


def transactional(func: Callable) -> Callable:
    """
    Decorator for automatic transaction management (PostgreSQL only)

    Features:
    - Automatic BEGIN transaction
    - Automatic COMMIT on success
    - Automatic ROLLBACK on failure
    - Performance timing
    - Comprehensive error logging

    Usage:
        @transactional
        def add_new_post(self, post_data, cursor=None):
            # cursor is provided by decorator
            cursor.execute(insert_sql, post_data)
            return True
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not hasattr(self, 'connection') or not self.connection:
            logger.error("Database connection not initialized for transactional operation")
            return False

        cursor = None
        start_time = time.time()
        operation_name = func.__name__
        is_postgresql = _is_postgresql_connection(self.connection)

        if not is_postgresql:
            logger.error("Only PostgreSQL connections are supported")
            return False

        try:
            cursor = self.connection.cursor()

            # Begin transaction
            _begin_transaction(cursor, self.connection)
            logger.debug("🔄 PostgreSQL transaction started for %s", operation_name)

            # Execute the wrapped function with cursor
            result = func(self, *args, cursor=cursor, **kwargs)

            # Commit on success
            _commit_transaction(cursor, self.connection)

            duration = time.time() - start_time
            logger.debug(
                "✅ PostgreSQL transaction committed for %s in %.3fs",
                operation_name, duration
            )

            return result

        except Exception as e:
            # Handle PostgreSQL-specific errors
            if POSTGRESQL_AVAILABLE and psycopg2:
                if isinstance(e, (psycopg2.IntegrityError, psycopg2.OperationalError)):
                    _rollback_transaction(cursor, self.connection)
                    duration = time.time() - start_time
                    error_type = "integrity constraint violation" if isinstance(e, psycopg2.IntegrityError) else "operational error"
                    logger.error(
                        "❌ PostgreSQL %s in %s after %.3fs: %s",
                        error_type, operation_name, duration, str(e)
                    )
                    return False
            
            # Generic error handling for unexpected errors
            _rollback_transaction(cursor, self.connection)
            duration = time.time() - start_time
            logger.error(
                "❌ Transaction failed for %s after %.3fs: %s",
                operation_name, duration, str(e)
            )
            return False

    return wrapper


def read_only_transaction(func: Callable) -> Callable:
    """
    Decorator for read-only operations with transaction isolation (PostgreSQL only)

    Features:
    - BEGIN transaction for read consistency  
    - Automatic ROLLBACK (no commits for read-only)
    - Performance monitoring
    - Error handling
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not hasattr(self, 'connection') or not self.connection:
            logger.error("Database connection not initialized for read operation")
            return None

        cursor = None
        start_time = time.time()
        operation_name = func.__name__
        is_postgresql = _is_postgresql_connection(self.connection)

        if not is_postgresql:
            logger.error("Only PostgreSQL connections are supported")
            return None

        try:
            cursor = self.connection.cursor()

            # Begin read-only transaction for consistency
            cursor.execute("BEGIN")
            logger.debug("📖 PostgreSQL read transaction started for %s", operation_name)

            # Execute the wrapped function
            result = func(self, *args, cursor=cursor, **kwargs)

            # Always rollback for read-only (no changes to commit)
            _rollback_transaction(cursor, self.connection)

            duration = time.time() - start_time
            logger.debug(
                "✅ Read operation %s completed in %.3fs",
                operation_name, duration
            )

            return result

        except Exception as e:
            # Handle PostgreSQL errors
            if POSTGRESQL_AVAILABLE and psycopg2:
                if isinstance(e, (psycopg2.DatabaseError, psycopg2.OperationalError)):
                    _rollback_transaction(cursor, self.connection)
                    duration = time.time() - start_time
                    logger.error(
                        "❌ PostgreSQL read operation %s failed after %.3fs: %s",
                        operation_name, duration, str(e)
                    )
                    return None
            
            _rollback_transaction(cursor, self.connection)
            duration = time.time() - start_time
            logger.error(
                "❌ Read operation %s failed after %.3fs: %s",
                operation_name, duration, str(e)
            )
            return None

    return wrapper


def bulk_transaction(batch_size: int = 1000):
    """
    Decorator for bulk operations with batching (PostgreSQL only)

    Args:
        batch_size: Number of operations per transaction batch

    Features:
    - Automatic batching of large operations
    - Transaction per batch for better performance
    - Progress logging
    - Rollback per batch on errors
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, items, *args, **kwargs):
            if not hasattr(self, 'connection') or not self.connection:
                logger.error("Database connection not initialized for bulk operation")
                return False

            operation_name = func.__name__
            total_items = len(items)
            processed = 0
            failed = 0

            logger.info(
                "🔄 Starting bulk %s for %d items (batch size: %d)",
                operation_name, total_items, batch_size
            )

            # Process in batches
            for i in range(0, total_items, batch_size):
                batch = items[i:i + batch_size]
                cursor = None
                batch_start = time.time()

                try:
                    cursor = self.connection.cursor()
                    cursor.execute("BEGIN")

                    # Process batch
                    batch_result = func(self, batch, cursor=cursor, *args, **kwargs)

                    if batch_result:
                        self.connection.commit()
                        processed += len(batch)

                        batch_duration = time.time() - batch_start
                        logger.debug(
                            "✅ Bulk batch %d committed: %d items in %.3fs",
                            i//batch_size + 1, len(batch), batch_duration
                        )
                    else:
                        self.connection.rollback()
                        failed += len(batch)
                        logger.warning(
                            "❌ Bulk batch %d failed: %d items",
                            i//batch_size + 1, len(batch)
                        )

                except Exception as e:
                    # Handle PostgreSQL errors
                    if POSTGRESQL_AVAILABLE and psycopg2 and isinstance(e, (psycopg2.DatabaseError, psycopg2.OperationalError)):
                        if cursor:
                            try:
                                self.connection.rollback()
                            except (psycopg2.DatabaseError, psycopg2.OperationalError):
                                pass
                        
                        failed += len(batch)
                        batch_duration = time.time() - batch_start
                        logger.error(
                            "❌ PostgreSQL bulk batch %d error after %.3fs: %s",
                            i//batch_size + 1, batch_duration, str(e)
                        )
                    else:
                        # Generic error handling
                        if cursor:
                            try:
                                self.connection.rollback()
                            except Exception:
                                pass

                        failed += len(batch)
                        batch_duration = time.time() - batch_start
                        logger.error(
                            "❌ Bulk batch %d error after %.3fs: %s",
                            i//batch_size + 1, batch_duration, str(e)
                        )

            success_rate = (processed / total_items * 100) if total_items > 0 else 0
            logger.info(
                "✅ Bulk %s completed: %d/%d (%.1f%%) processed, %d failed",
                operation_name, processed, total_items, success_rate, failed
            )

            return processed > 0

        return wrapper
    return decorator


if __name__ == "__main__":
    print("✅ Transaction decorator (PostgreSQL only) ready!")
    print("Note: This module requires PostgreSQL connection for testing.")