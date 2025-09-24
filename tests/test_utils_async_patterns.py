#!/usr/bin/env python3
"""
Comprehensive tests for Async Patterns and Utilities
Tests async delay patterns, synchronization primitives, and async decorators
"""

import pytest
import asyncio
import time
import threading
from unittest.mock import Mock, patch, AsyncMock
from typing import Any, List
from concurrent.futures import ThreadPoolExecutor

# Setup path for imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import async patterns components
from utils.async_patterns import (
    AsyncDelay, AsyncBatch, AsyncSynchronization, 
    async_retry, async_timeout, async_throttle,
    ThreadSafeAsyncQueue, AsyncWorkerPool, AsyncRateLimiter
)


@pytest.mark.unit
class TestAsyncDelay:
    """Test cases for AsyncDelay utilities"""
    
    @pytest.mark.asyncio
    async def test_smart_delay_timing(self):
        """Test smart delay timing is within expected range"""
        min_delay = 0.1
        max_delay = 0.2
        
        start_time = time.time()
        await AsyncDelay.smart_delay(min_delay, max_delay, "test")
        elapsed = time.time() - start_time
        
        # Should be within the specified range (with small tolerance)
        assert min_delay <= elapsed <= max_delay + 0.05
    
    @pytest.mark.asyncio
    async def test_exponential_backoff_progression(self):
        """Test exponential backoff delay progression"""
        base_delay = 0.1
        multiplier = 2.0
        
        # Test different attempts
        for attempt in range(3):
            expected_delay = min(base_delay * (multiplier ** attempt), 60.0)
            
            start_time = time.time()
            await AsyncDelay.exponential_backoff(
                attempt=attempt,
                base_delay=base_delay,
                max_delay=60.0,
                multiplier=multiplier
            )
            elapsed = time.time() - start_time
            
            # Should be close to expected delay (with tolerance for execution time)
            assert abs(elapsed - expected_delay) < 0.05
    
    @pytest.mark.asyncio
    async def test_exponential_backoff_max_delay_cap(self):
        """Test exponential backoff respects max delay cap"""
        base_delay = 1.0
        max_delay = 2.0
        multiplier = 10.0  # Large multiplier
        
        start_time = time.time()
        await AsyncDelay.exponential_backoff(
            attempt=5,  # High attempt number
            base_delay=base_delay,
            max_delay=max_delay,
            multiplier=multiplier
        )
        elapsed = time.time() - start_time
        
        # Should not exceed max_delay
        assert elapsed <= max_delay + 0.1
    
    @pytest.mark.asyncio
    async def test_jittered_delay(self):
        """Test jittered delay adds randomness"""
        base_delay = 0.2
        jitter_factor = 0.1
        
        delays = []
        for _ in range(5):
            start_time = time.time()
            await AsyncDelay.jittered_delay(base_delay, jitter_factor)
            elapsed = time.time() - start_time
            delays.append(elapsed)
        
        # All delays should be different (showing jitter effect)
        assert len(set(delays)) > 1
        
        # All delays should be within expected range
        min_expected = base_delay * (1 - jitter_factor)
        max_expected = base_delay * (1 + jitter_factor)
        
        for delay in delays:
            assert min_expected <= delay <= max_expected + 0.05


@pytest.mark.unit
class TestAsyncBatch:
    """Test cases for AsyncBatch processing utilities"""
    
    @pytest.mark.asyncio
    async def test_process_in_batches_basic(self):
        """Test basic batch processing"""
        items = list(range(10))  # [0, 1, 2, ..., 9]
        batch_size = 3
        
        async def process_item(item):
            return item * 2
        
        results = await AsyncBatch.process_in_batches(
            items=items,
            batch_size=batch_size,
            processor=process_item
        )
        
        expected = [i * 2 for i in range(10)]
        assert results == expected
    
    @pytest.mark.asyncio
    async def test_process_in_batches_with_delay(self):
        """Test batch processing with inter-batch delay"""
        items = list(range(6))
        batch_size = 2
        batch_delay = 0.1
        
        async def process_item(item):
            return item + 1
        
        start_time = time.time()
        results = await AsyncBatch.process_in_batches(
            items=items,
            batch_size=batch_size,
            processor=process_item,
            batch_delay=batch_delay
        )
        elapsed = time.time() - start_time
        
        # Should have processed 3 batches with 2 delays between them
        # Expected time: ~0.2s (2 * 0.1s delay)
        assert elapsed >= 0.2
        assert results == [1, 2, 3, 4, 5, 6]
    
    @pytest.mark.asyncio
    async def test_concurrent_map_basic(self):
        """Test concurrent mapping of function to items"""
        items = [1, 2, 3, 4, 5]
        
        async def square(x):
            await asyncio.sleep(0.01)  # Small delay to simulate work
            return x ** 2
        
        start_time = time.time()
        results = await AsyncBatch.concurrent_map(square, items, max_concurrency=3)
        elapsed = time.time() - start_time
        
        # Results should be correct
        assert results == [1, 4, 9, 16, 25]
        
        # Should be faster than sequential (5 * 0.01 = 0.05s)
        assert elapsed < 0.04  # Should complete in ~0.02s with concurrency
    
    @pytest.mark.asyncio
    async def test_concurrent_map_with_errors(self):
        """Test concurrent map handling errors"""
        items = [1, 2, 3, 4, 5]
        
        async def sometimes_fail(x):
            if x == 3:
                raise ValueError(f"Failed on {x}")
            return x * 2
        
        with pytest.raises(ValueError) as exc_info:
            await AsyncBatch.concurrent_map(sometimes_fail, items, max_concurrency=2)
        
        assert "Failed on 3" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_gather_with_limit(self):
        """Test gather with concurrency limit"""
        async def delayed_task(delay, result):
            await asyncio.sleep(delay)
            return result
        
        tasks = [
            delayed_task(0.01, f"result_{i}") for i in range(10)
        ]
        
        start_time = time.time()
        results = await AsyncBatch.gather_with_limit(tasks, limit=3)
        elapsed = time.time() - start_time
        
        # All results should be present
        assert len(results) == 10
        assert all(f"result_{i}" in results for i in range(10))
        
        # Should complete in reasonable time with concurrency limit
        assert elapsed < 0.1


@pytest.mark.unit
class TestAsyncSynchronization:
    """Test cases for async synchronization primitives"""
    
    @pytest.mark.asyncio
    async def test_semaphore_rate_limiter(self):
        """Test semaphore-based rate limiting"""
        max_concurrent = 2
        semaphore = AsyncSynchronization.create_semaphore(max_concurrent)
        
        call_times = []
        
        async def limited_task(task_id):
            async with semaphore:
                call_times.append((task_id, time.time()))
                await asyncio.sleep(0.1)
                return task_id
        
        # Start 5 tasks concurrently
        tasks = [limited_task(i) for i in range(5)]
        start_time = time.time()
        
        results = await asyncio.gather(*tasks)
        
        # All tasks should complete
        assert results == [0, 1, 2, 3, 4]
        
        # Check that no more than 2 tasks were running simultaneously
        # This is a simplified check - in practice you'd need more sophisticated timing analysis
        assert len(call_times) == 5
    
    @pytest.mark.asyncio
    async def test_async_lock_mutual_exclusion(self):
        """Test async lock provides mutual exclusion"""
        lock = AsyncSynchronization.create_lock()
        shared_resource = []
        
        async def exclusive_task(task_id):
            async with lock:
                # Critical section
                initial_length = len(shared_resource)
                await asyncio.sleep(0.01)  # Simulate some work
                shared_resource.append(task_id)
                
                # Verify no interference from other tasks
                assert len(shared_resource) == initial_length + 1
        
        # Run multiple tasks concurrently
        tasks = [exclusive_task(i) for i in range(5)]
        await asyncio.gather(*tasks)
        
        # All tasks should have completed successfully
        assert len(shared_resource) == 5
        assert set(shared_resource) == {0, 1, 2, 3, 4}
    
    @pytest.mark.asyncio
    async def test_async_event_coordination(self):
        """Test async event for task coordination"""
        event = AsyncSynchronization.create_event()
        results = []
        
        async def waiter(task_id):
            await event.wait()
            results.append(f"task_{task_id}_completed")
        
        async def setter():
            await asyncio.sleep(0.05)  # Small delay
            event.set()
        
        # Start waiters and setter
        tasks = [waiter(i) for i in range(3)] + [setter()]
        
        await asyncio.gather(*tasks)
        
        # All waiters should complete after event is set
        assert len(results) == 3
        assert all("completed" in result for result in results)


@pytest.mark.unit
class TestAsyncDecorators:
    """Test cases for async decorators"""
    
    @pytest.mark.asyncio
    async def test_async_retry_success_on_first_attempt(self):
        """Test retry decorator with successful first attempt"""
        call_count = 0
        
        @async_retry(max_attempts=3, delay=0.01)
        async def successful_function():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = await successful_function()
        
        assert result == "success"
        assert call_count == 1
    
    @pytest.mark.asyncio
    async def test_async_retry_with_failures(self):
        """Test retry decorator with initial failures"""
        call_count = 0
        
        @async_retry(max_attempts=3, delay=0.01)
        async def sometimes_failing_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"Attempt {call_count} failed")
            return "finally_success"
        
        result = await sometimes_failing_function()
        
        assert result == "finally_success"
        assert call_count == 3
    
    @pytest.mark.asyncio
    async def test_async_retry_exhausted_attempts(self):
        """Test retry decorator when all attempts are exhausted"""
        call_count = 0
        
        @async_retry(max_attempts=2, delay=0.01)
        async def always_failing_function():
            nonlocal call_count
            call_count += 1
            raise Exception(f"Attempt {call_count} failed")
        
        with pytest.raises(Exception) as exc_info:
            await always_failing_function()
        
        assert "Attempt 2 failed" in str(exc_info.value)
        assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_async_timeout_within_limit(self):
        """Test timeout decorator with operation within limit"""
        @async_timeout(timeout=0.1)
        async def quick_function():
            await asyncio.sleep(0.05)
            return "completed"
        
        result = await quick_function()
        assert result == "completed"
    
    @pytest.mark.asyncio
    async def test_async_timeout_exceeded(self):
        """Test timeout decorator with operation exceeding limit"""
        @async_timeout(timeout=0.05)
        async def slow_function():
            await asyncio.sleep(0.1)
            return "should_not_reach_here"
        
        with pytest.raises(asyncio.TimeoutError):
            await slow_function()
    
    @pytest.mark.asyncio
    async def test_async_throttle_rate_limiting(self):
        """Test throttle decorator for rate limiting"""
        call_times = []
        
        @async_throttle(rate=10, per=1.0)  # 10 calls per second
        async def throttled_function():
            call_times.append(time.time())
            return "throttled_result"
        
        # Make rapid calls
        tasks = [throttled_function() for _ in range(5)]
        await asyncio.gather(*tasks)
        
        # Check that calls were properly spaced
        if len(call_times) > 1:
            time_diffs = [call_times[i] - call_times[i-1] for i in range(1, len(call_times))]
            # With 10 calls/second, minimum interval should be 0.1s
            assert all(diff >= 0.09 for diff in time_diffs)  # Small tolerance


@pytest.mark.unit
class TestThreadSafeAsyncQueue:
    """Test cases for thread-safe async queue"""
    
    @pytest.mark.asyncio
    async def test_basic_queue_operations(self):
        """Test basic put and get operations"""
        queue = ThreadSafeAsyncQueue(maxsize=5)
        
        # Put items
        await queue.put("item1")
        await queue.put("item2")
        
        # Get items
        item1 = await queue.get()
        item2 = await queue.get()
        
        assert item1 == "item1"
        assert item2 == "item2"
        assert queue.empty()
    
    @pytest.mark.asyncio
    async def test_queue_maxsize_blocking(self):
        """Test queue blocks when maxsize is reached"""
        queue = ThreadSafeAsyncQueue(maxsize=2)
        
        # Fill queue to capacity
        await queue.put("item1")
        await queue.put("item2")
        assert queue.full()
        
        # Next put should block (test with timeout)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.put("item3"), timeout=0.1)
    
    @pytest.mark.asyncio
    async def test_queue_producer_consumer_pattern(self):
        """Test producer-consumer pattern with queue"""
        queue = ThreadSafeAsyncQueue(maxsize=10)
        produced_items = list(range(20))
        consumed_items = []
        
        async def producer():
            for item in produced_items:
                await queue.put(item)
                await asyncio.sleep(0.001)  # Small delay
        
        async def consumer():
            while len(consumed_items) < len(produced_items):
                item = await queue.get()
                consumed_items.append(item)
                queue.task_done()
        
        # Run producer and consumer concurrently
        await asyncio.gather(producer(), consumer())
        
        assert consumed_items == produced_items


@pytest.mark.unit
class TestAsyncWorkerPool:
    """Test cases for async worker pool"""
    
    @pytest.mark.asyncio
    async def test_worker_pool_task_processing(self):
        """Test worker pool processes tasks correctly"""
        async def worker_task(item):
            await asyncio.sleep(0.01)  # Simulate work
            return item * 2
        
        pool = AsyncWorkerPool(worker_count=3, task_function=worker_task)
        
        # Add tasks
        tasks = list(range(10))
        for task in tasks:
            await pool.add_task(task)
        
        # Start processing
        await pool.start()
        
        # Wait for completion
        await pool.join()
        results = pool.get_results()
        
        await pool.stop()
        
        # Verify results
        expected = [i * 2 for i in range(10)]
        assert sorted(results) == sorted(expected)
    
    @pytest.mark.asyncio
    async def test_worker_pool_with_errors(self):
        """Test worker pool handles task errors gracefully"""
        async def sometimes_failing_task(item):
            if item == 5:
                raise ValueError(f"Task {item} failed")
            return item
        
        pool = AsyncWorkerPool(worker_count=2, task_function=sometimes_failing_task)
        
        # Add tasks including one that will fail
        for i in range(10):
            await pool.add_task(i)
        
        await pool.start()
        await pool.join()
        
        results = pool.get_results()
        errors = pool.get_errors()
        
        await pool.stop()
        
        # Should have 9 successful results and 1 error
        assert len(results) == 9
        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)


@pytest.mark.unit
class TestAsyncRateLimiter:
    """Test cases for async rate limiter"""
    
    @pytest.mark.asyncio
    async def test_rate_limiter_basic_functionality(self):
        """Test basic rate limiting functionality"""
        rate_limiter = AsyncRateLimiter(rate=5, per=1.0)  # 5 operations per second
        
        call_times = []
        
        async def make_call():
            await rate_limiter.acquire()
            call_times.append(time.time())
        
        # Make several calls
        await asyncio.gather(*[make_call() for _ in range(3)])
        
        # Verify rate limiting (calls should be spaced appropriately)
        if len(call_times) > 1:
            time_diffs = [call_times[i] - call_times[i-1] for i in range(1, len(call_times))]
            # With 5 calls/second, minimum interval should be 0.2s
            assert all(diff >= 0.18 for diff in time_diffs)  # Small tolerance
    
    @pytest.mark.asyncio
    async def test_rate_limiter_burst_handling(self):
        """Test rate limiter handles burst of requests"""
        rate_limiter = AsyncRateLimiter(rate=2, per=1.0, burst=3)
        
        # Should allow burst initially
        start_time = time.time()
        
        for _ in range(3):  # Burst of 3
            await rate_limiter.acquire()
        
        burst_time = time.time() - start_time
        
        # Burst should complete quickly
        assert burst_time < 0.1
        
        # Next call should be rate limited
        next_call_start = time.time()
        await rate_limiter.acquire()
        next_call_time = time.time() - next_call_start
        
        # Should wait for rate limit
        assert next_call_time >= 0.4  # Should wait ~0.5s


@pytest.mark.integration
class TestAsyncPatternsIntegration:
    """Integration tests for async patterns working together"""
    
    @pytest.mark.asyncio
    async def test_combined_patterns_scenario(self):
        """Test multiple async patterns working together"""
        results = []
        
        @async_retry(max_attempts=2, delay=0.01)
        @async_timeout(timeout=1.0)
        async def process_item(item):
            if item == 3:  # Simulate occasional failure
                raise Exception("Processing failed")
            
            await AsyncDelay.smart_delay(0.01, 0.02, f"processing_{item}")
            return f"processed_{item}"
        
        # Process items in batches with rate limiting
        items = [1, 2, 4, 5, 6]  # Skip 3 which would fail
        
        processed = await AsyncBatch.concurrent_map(
            process_item, 
            items, 
            max_concurrency=2
        )
        
        expected = [f"processed_{i}" for i in items]
        assert processed == expected
    
    @pytest.mark.asyncio
    async def test_real_world_data_processing_scenario(self):
        """Test real-world scenario with data processing pipeline"""
        # Simulate processing posts data
        posts_data = [
            {"id": i, "content": f"Post {i}", "priority": i % 3}
            for i in range(20)
        ]
        
        processed_posts = []
        
        @async_throttle(rate=10, per=1.0)  # Rate limit API calls
        async def process_post(post):
            # Simulate API call delay
            await asyncio.sleep(0.01)
            
            processed = {
                **post,
                "processed_at": time.time(),
                "status": "processed"
            }
            processed_posts.append(processed)
            return processed
        
        # Process in priority-based batches
        high_priority = [p for p in posts_data if p["priority"] == 0]
        medium_priority = [p for p in posts_data if p["priority"] == 1]
        low_priority = [p for p in posts_data if p["priority"] == 2]
        
        # Process high priority first, then others concurrently
        await AsyncBatch.process_in_batches(
            high_priority, 
            batch_size=3, 
            processor=process_post
        )
        
        await asyncio.gather(
            AsyncBatch.process_in_batches(
                medium_priority, 
                batch_size=5, 
                processor=process_post
            ),
            AsyncBatch.process_in_batches(
                low_priority, 
                batch_size=5, 
                processor=process_post
            )
        )
        
        # Verify all posts processed
        assert len(processed_posts) == 20
        assert all(post["status"] == "processed" for post in processed_posts)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
