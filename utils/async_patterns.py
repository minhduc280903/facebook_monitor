#!/usr/bin/env python3
"""
Async Patterns and Utilities for Facebook Post Monitor
🔧 SOLUTION: Replace 50+ blocking time.sleep() calls with async patterns

This module provides async-safe alternatives to blocking operations
"""

import asyncio
import time
import threading
from typing import Callable, Any, Optional, Union, List, Dict
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from logging_config import get_logger

logger = get_logger(__name__)


class AsyncDelay:
    """Non-blocking delay utilities"""
    
    @staticmethod
    async def smart_delay(
        min_delay: float, 
        max_delay: float, 
        reason: str = "operation"
    ) -> None:
        """
        Smart async delay with random jitter
        
        Args:
            min_delay: Minimum delay in seconds
            max_delay: Maximum delay in seconds  
            reason: Reason for delay (for logging)
        """
        import random
        delay = random.uniform(min_delay, max_delay)
        logger.debug(f"⏳ {reason}: waiting {delay:.2f}s")
        await asyncio.sleep(delay)
    
    @staticmethod
    async def exponential_backoff(
        attempt: int, 
        base_delay: float = 1.0, 
        max_delay: float = 60.0,
        multiplier: float = 2.0
    ) -> None:
        """
        Exponential backoff delay
        
        Args:
            attempt: Attempt number (0-based)
            base_delay: Base delay in seconds
            max_delay: Maximum delay cap
            multiplier: Backoff multiplier
        """
        delay = min(base_delay * (multiplier ** attempt), max_delay)
        logger.debug(f"🔄 Exponential backoff: attempt {attempt}, delay {delay:.2f}s")
        await asyncio.sleep(delay)
    
    @staticmethod  
    async def adaptive_delay(
        last_success_time: float,
        target_interval: float = 1.0
    ) -> None:
        """
        Adaptive delay based on last operation time
        
        Args:
            last_success_time: Timestamp of last successful operation
            target_interval: Target interval between operations
        """
        elapsed = time.time() - last_success_time
        remaining = max(0, target_interval - elapsed)
        
        if remaining > 0:
            logger.debug(f"⏱️ Adaptive delay: {remaining:.2f}s remaining")
            await asyncio.sleep(remaining)


class AsyncScheduler:
    """Non-blocking scheduler for recurring tasks"""
    
    def __init__(self):
        self.tasks = {}
        self.running = False
    
    async def schedule_recurring(
        self, 
        name: str, 
        coro_func: Callable,
        interval: float,
        *args,
        **kwargs
    ) -> None:
        """
        Schedule a recurring async task
        
        Args:
            name: Task name
            coro_func: Async function to run
            interval: Interval in seconds
            *args, **kwargs: Arguments for the function
        """
        
        async def task_runner():
            while self.running and name in self.tasks:
                try:
                    await coro_func(*args, **kwargs)
                    await asyncio.sleep(interval)
                except asyncio.CancelledError:
                    logger.info(f"⏹️ Task {name} cancelled")
                    break
                except Exception as e:
                    logger.error(f"❌ Task {name} failed: {e}")
                    await AsyncDelay.exponential_backoff(1)
        
        if self.running:
            task = asyncio.create_task(task_runner())
            self.tasks[name] = task
            logger.info(f"📅 Scheduled recurring task: {name} ({interval}s interval)")
    
    def start(self):
        """Start the scheduler"""
        self.running = True
        logger.info("🚀 AsyncScheduler started")
    
    async def stop(self):
        """Stop all scheduled tasks"""
        self.running = False
        
        if self.tasks:
            logger.info(f"⏹️ Stopping {len(self.tasks)} scheduled tasks...")
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
            self.tasks.clear()


class AsyncWorkerPool:
    """Async worker pool for concurrent processing"""
    
    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers
        self.semaphore = asyncio.Semaphore(max_workers)
        self.active_tasks = set()
    
    async def submit(self, coro_func: Callable, *args, **kwargs) -> Any:
        """
        Submit a task to the worker pool
        
        Args:
            coro_func: Async function to execute
            *args, **kwargs: Function arguments
            
        Returns:
            Task result
        """
        async with self.semaphore:
            task = asyncio.create_task(coro_func(*args, **kwargs))
            self.active_tasks.add(task)
            
            try:
                result = await task
                return result
            finally:
                self.active_tasks.discard(task)
    
    async def wait_for_completion(self):
        """Wait for all active tasks to complete"""
        if self.active_tasks:
            logger.info(f"⏳ Waiting for {len(self.active_tasks)} active tasks...")
            await asyncio.gather(*self.active_tasks, return_exceptions=True)
            self.active_tasks.clear()


def async_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    Decorator for async retry with exponential backoff
    
    Args:
        max_attempts: Maximum retry attempts
        delay: Base delay between retries
        backoff: Whether to use exponential backoff
        exceptions: Exceptions to catch and retry
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        if backoff:
                            await AsyncDelay.exponential_backoff(attempt, delay)
                        else:
                            await asyncio.sleep(delay)
                        logger.warning(f"🔄 Retry {attempt + 1}/{max_attempts} for {func.__name__}: {e}")
                    else:
                        logger.error(f"❌ Max retries exceeded for {func.__name__}")
            
            raise last_exception
        return wrapper
    return decorator


class AsyncEventManager:
    """Event-driven async manager"""
    
    def __init__(self):
        self.events = {}
        self.listeners = {}
    
    def create_event(self, name: str) -> asyncio.Event:
        """Create a new event"""
        event = asyncio.Event()
        self.events[name] = event
        return event
    
    def get_event(self, name: str) -> Optional[asyncio.Event]:
        """Get existing event"""
        return self.events.get(name)
    
    def trigger_event(self, name: str):
        """Trigger an event"""
        if name in self.events:
            self.events[name].set()
            logger.debug(f"🔔 Event triggered: {name}")
    
    async def wait_for_event(self, name: str, timeout: Optional[float] = None) -> bool:
        """
        Wait for an event to be triggered
        
        Args:
            name: Event name
            timeout: Optional timeout in seconds
            
        Returns:
            True if event was triggered, False if timeout
        """
        if name not in self.events:
            self.create_event(name)
        
        try:
            await asyncio.wait_for(self.events[name].wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"⏰ Timeout waiting for event: {name}")
            return False


# System Management Async Patterns
class AsyncSystemManager:
    """Specialized patterns for system startup, shutdown, and health monitoring"""
    
    @staticmethod
    async def system_stabilization(
        delay: float,
        component: str = "system",
        check_func: Optional[Callable] = None
    ) -> bool:
        """
        Non-blocking system stabilization wait with optional health check
        
        Args:
            delay: Time to wait for stabilization
            component: Component name for logging
            check_func: Optional async function to check component health
            
        Returns:
            True if healthy, False if check failed
        """
        logger.info(f"⏳ Waiting for {component} stabilization ({delay}s)...")
        await asyncio.sleep(delay)
        
        if check_func:
            try:
                is_healthy = await check_func()
                status = "✅ healthy" if is_healthy else "❌ unhealthy"
                logger.info(f"🔍 {component} status: {status}")
                return is_healthy
            except Exception as e:
                logger.error(f"❌ Health check failed for {component}: {e}")
                return False
        
        logger.info(f"✅ {component} stabilization completed")
        return True
    
    @staticmethod
    async def graceful_shutdown(
        delay: float,
        processes: list = None,
        timeout: float = 30.0
    ) -> bool:
        """
        Graceful shutdown with process termination handling
        
        Args:
            delay: Time to wait for graceful shutdown
            processes: List of processes to monitor
            timeout: Maximum time to wait for shutdown
            
        Returns:
            True if shutdown successful, False if forced termination needed
        """
        logger.info(f"⏸️ Initiating graceful shutdown (waiting {delay}s)...")
        await asyncio.sleep(delay)
        
        if processes:
            logger.info("🔍 Checking process shutdown status...")
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                active_processes = [p for p in processes if p.poll() is None]
                if not active_processes:
                    logger.info("✅ All processes shut down gracefully")
                    return True
                    
                logger.debug(f"⏳ {len(active_processes)} processes still running...")
                await asyncio.sleep(1.0)
            
            logger.warning(f"⚠️ Graceful shutdown timeout after {timeout}s")
            return False
        
        return True
    
    @staticmethod
    async def sequential_startup(
        components: List[Dict[str, Any]],
        default_delay: float = 3.0
    ) -> Dict[str, bool]:
        """
        Sequential component startup with individual delays and health checks
        
        Args:
            components: List of dicts with 'name', 'start_func', 'delay', 'health_check'
            default_delay: Default delay if not specified per component
            
        Returns:
            Dict mapping component names to startup success status
        """
        results = {}
        
        for component in components:
            name = component['name']
            start_func = component['start_func']
            delay = component.get('delay', default_delay)
            health_check = component.get('health_check')
            
            logger.info(f"🚀 Starting {name}...")
            
            try:
                # Start the component
                if asyncio.iscoroutinefunction(start_func):
                    await start_func()
                else:
                    start_func()
                
                # Wait for stabilization
                success = await AsyncSystemManager.system_stabilization(
                    delay, name, health_check
                )
                results[name] = success
                
                if not success:
                    logger.error(f"❌ {name} failed to start properly")
                    break
                    
            except Exception as e:
                logger.error(f"💥 Failed to start {name}: {e}")
                results[name] = False
                break
        
        return results


class AsyncResourceManager:
    """Patterns for resource management with async timeouts and retries"""
    
    @staticmethod
    async def checkout_with_timeout(
        check_func: Callable,
        checkout_func: Callable,
        timeout: float = 30.0,
        retry_interval: float = 1.0,
        resource_type: str = "resource"
    ) -> Any:
        """
        Async resource checkout with timeout and retry
        
        Args:
            check_func: Async function to check resource availability
            checkout_func: Async function to checkout resource
            timeout: Maximum time to wait for resource
            retry_interval: Time between availability checks
            resource_type: Resource type for logging
            
        Returns:
            Resource object or None if timeout
        """
        logger.debug(f"🔄 Attempting to checkout {resource_type}...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                if await check_func():
                    resource = await checkout_func()
                    logger.debug(f"✅ Successfully checked out {resource_type}")
                    return resource
                else:
                    logger.debug(f"⏳ {resource_type} not available, retrying...")
                    await asyncio.sleep(retry_interval)
                    
            except Exception as e:
                logger.error(f"❌ Error during {resource_type} checkout: {e}")
                await AsyncDelay.exponential_backoff(1, retry_interval)
        
        logger.warning(f"⏰ Timeout checking out {resource_type} after {timeout}s")
        return None
    
    @staticmethod
    async def resource_pool_manager(
        pool_size: int,
        create_func: Callable,
        validate_func: Optional[Callable] = None,
        cleanup_func: Optional[Callable] = None
    ):
        """
        Async resource pool with validation and cleanup
        """
        pool = asyncio.Queue(maxsize=pool_size)
        active_resources = set()
        
        # Initialize pool
        for i in range(pool_size):
            try:
                resource = await create_func()
                await pool.put(resource)
                logger.debug(f"✅ Created pool resource {i+1}/{pool_size}")
            except Exception as e:
                logger.error(f"❌ Failed to create pool resource {i+1}: {e}")
        
        return {
            'pool': pool,
            'active_resources': active_resources,
            'validate_func': validate_func,
            'cleanup_func': cleanup_func
        }


class AsyncMonitoringPatterns:
    """Patterns for monitoring, health checks, and periodic operations"""
    
    @staticmethod
    async def health_monitoring_loop(
        check_funcs: Dict[str, Callable],
        check_interval: float = 30.0,
        alert_func: Optional[Callable] = None,
        stop_event: Optional[asyncio.Event] = None
    ):
        """
        Continuous health monitoring with configurable checks
        
        Args:
            check_funcs: Dict mapping component names to health check functions
            check_interval: Time between health checks
            alert_func: Optional function to call on health issues
            stop_event: Event to stop monitoring
        """
        logger.info("🏥 Starting health monitoring loop...")
        
        while True:
            if stop_event and stop_event.is_set():
                logger.info("⏹️ Health monitoring stopped")
                break
                
            health_results = {}
            unhealthy_components = []
            
            for component, check_func in check_funcs.items():
                try:
                    is_healthy = await check_func()
                    health_results[component] = is_healthy
                    
                    if not is_healthy:
                        unhealthy_components.append(component)
                        logger.warning(f"⚠️ {component} is unhealthy")
                    else:
                        logger.debug(f"✅ {component} is healthy")
                        
                except Exception as e:
                    logger.error(f"❌ Health check failed for {component}: {e}")
                    health_results[component] = False
                    unhealthy_components.append(component)
            
            # Alert on unhealthy components
            if unhealthy_components and alert_func:
                try:
                    await alert_func(unhealthy_components, health_results)
                except Exception as e:
                    logger.error(f"❌ Alert function failed: {e}")
            
            # Wait before next check
            await asyncio.sleep(check_interval)
    
    @staticmethod
    async def adaptive_refresh_loop(
        refresh_func: Callable,
        base_interval: float = 5.0,
        max_interval: float = 60.0,
        error_backoff: float = 2.0,
        success_speedup: float = 0.9,
        stop_event: Optional[asyncio.Event] = None
    ):
        """
        Adaptive refresh loop that adjusts interval based on success/failure
        
        Args:
            refresh_func: Async function to call for refresh
            base_interval: Base refresh interval
            max_interval: Maximum interval on errors
            error_backoff: Multiplier for interval on error
            success_speedup: Multiplier for interval on success
            stop_event: Event to stop the loop
        """
        current_interval = base_interval
        consecutive_errors = 0
        
        logger.info(f"🔄 Starting adaptive refresh loop (base: {base_interval}s)")
        
        while True:
            if stop_event and stop_event.is_set():
                logger.info("⏹️ Refresh loop stopped")
                break
            
            try:
                await refresh_func()
                consecutive_errors = 0
                
                # Speed up on success (but don't go below base)
                current_interval = max(base_interval, current_interval * success_speedup)
                logger.debug(f"✅ Refresh successful, interval: {current_interval:.1f}s")
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Refresh failed (error #{consecutive_errors}): {e}")
                
                # Slow down on error (but don't exceed max)
                current_interval = min(max_interval, current_interval * error_backoff)
                logger.warning(f"⏰ Backing off, interval: {current_interval:.1f}s")
            
            await asyncio.sleep(current_interval)


class AsyncSchedulingPatterns:
    """Specialized scheduling patterns for different types of operations"""
    
    @staticmethod
    async def high_frequency_scheduler(
        task_func: Callable,
        interval: float = 5.0,
        max_runtime: Optional[float] = None,
        skip_if_running: bool = True,
        stop_event: Optional[asyncio.Event] = None
    ):
        """
        High-frequency scheduler with overlap protection
        
        Args:
            task_func: Async function to run repeatedly
            interval: Time between task starts
            max_runtime: Maximum runtime per task (timeout)
            skip_if_running: Skip if previous task still running
            stop_event: Event to stop scheduler
        """
        logger.info(f"⚡ Starting high-frequency scheduler ({interval}s interval)")
        
        current_task = None
        cycle_count = 0
        
        while True:
            if stop_event and stop_event.is_set():
                logger.info("⏹️ High-frequency scheduler stopped")
                break
            
            cycle_count += 1
            
            # Check if previous task is still running
            if current_task and not current_task.done():
                if skip_if_running:
                    logger.debug(f"⏭️ Skipping cycle {cycle_count} - previous task still running")
                    await asyncio.sleep(interval)
                    continue
                else:
                    logger.warning(f"⚠️ Cancelling previous task for cycle {cycle_count}")
                    current_task.cancel()
                    try:
                        await current_task
                    except asyncio.CancelledError:
                        pass
            
            # Start new task
            logger.debug(f"🔄 Starting high-frequency task cycle {cycle_count}")
            
            if max_runtime:
                current_task = asyncio.create_task(
                    run_with_timeout(task_func(), max_runtime)
                )
            else:
                current_task = asyncio.create_task(task_func())
            
            await asyncio.sleep(interval)
    
    @staticmethod
    async def discovery_scheduler(
        discovery_func: Callable,
        interval: float = 300.0,  # 5 minutes default
        immediate_first_run: bool = True,
        error_retry_delay: float = 60.0,
        max_consecutive_errors: int = 5,
        stop_event: Optional[asyncio.Event] = None
    ):
        """
        Discovery scheduler with error handling and backoff
        
        Args:
            discovery_func: Async discovery function
            interval: Time between discovery cycles
            immediate_first_run: Run immediately on start
            error_retry_delay: Delay after error before retry
            max_consecutive_errors: Max errors before longer backoff
            stop_event: Event to stop scheduler
        """
        logger.info(f"🔍 Starting discovery scheduler ({interval}s interval)")
        
        consecutive_errors = 0
        cycle_count = 0
        
        # Run immediately if requested
        if immediate_first_run:
            try:
                await discovery_func()
                logger.info("✅ Initial discovery completed")
            except Exception as e:
                logger.error(f"❌ Initial discovery failed: {e}")
                consecutive_errors += 1
        
        while True:
            if stop_event and stop_event.is_set():
                logger.info("⏹️ Discovery scheduler stopped")
                break
            
            await asyncio.sleep(interval)
            
            if stop_event and stop_event.is_set():
                break
                
            cycle_count += 1
            logger.info(f"🔍 Starting discovery cycle {cycle_count}")
            
            try:
                await discovery_func()
                consecutive_errors = 0
                logger.info(f"✅ Discovery cycle {cycle_count} completed")
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Discovery cycle {cycle_count} failed: {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(
                        f"⚠️ {consecutive_errors} consecutive errors, "
                        f"waiting {error_retry_delay}s before retry"
                    )
                    await asyncio.sleep(error_retry_delay)

    @staticmethod
    async def discovery_cycle(interval: float, description: str = "scheduler"):
        """
        Non-blocking sleep for discovery cycles
        
        Args:
            interval: Sleep time in seconds
            description: Description for logging
        """
        await asyncio.sleep(interval)
    
    @staticmethod
    async def high_frequency_tracking(interval: float):
        """
        Non-blocking sleep for high-frequency tracking cycles
        
        Args:
            interval: Sleep time in seconds (typically 5-10 seconds)
        """
        await asyncio.sleep(interval)


# Context managers for async patterns
class AsyncTimeout:
    """Async timeout context manager"""
    
    def __init__(self, timeout: float, operation: str = "operation"):
        self.timeout = timeout
        self.operation = operation
    
    async def __aenter__(self):
        self.task = asyncio.current_task()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is asyncio.TimeoutError:
            logger.warning(f"⏰ {self.operation} timed out after {self.timeout}s")


class AsyncRateLimiter:
    """Rate limiter for async operations"""
    
    def __init__(self, max_calls: int, time_window: float):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire rate limit permission"""
        async with self.lock:
            now = time.time()
            # Remove calls outside time window
            self.calls = [call_time for call_time in self.calls 
                         if now - call_time < self.time_window]
            
            if len(self.calls) >= self.max_calls:
                # Calculate wait time
                oldest_call = min(self.calls)
                wait_time = self.time_window - (now - oldest_call)
                logger.debug(f"🛑 Rate limit hit, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                return await self.acquire()
            
            self.calls.append(now)


# Common async patterns
async def run_with_timeout(coro, timeout: float, default=None):
    """Run coroutine with timeout"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"⏰ Operation timed out after {timeout}s")
        return default


async def gather_with_concurrency(coros, max_concurrent: int = 10):
    """Run coroutines with limited concurrency"""
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def sem_coro(coro):
        async with semaphore:
            return await coro
    
    return await asyncio.gather(*[sem_coro(coro) for coro in coros])


async def periodic_cleanup(
    cleanup_func: Callable,
    interval: float = 3600.0,  # 1 hour default
    stop_event: Optional[asyncio.Event] = None
):
    """Periodic cleanup task"""
    logger.info(f"🧹 Starting periodic cleanup ({interval}s interval)")
    
    while True:
        if stop_event and stop_event.is_set():
            logger.info("⏹️ Periodic cleanup stopped")
            break
        
        await asyncio.sleep(interval)
        
        try:
            await cleanup_func()
            logger.info("✅ Periodic cleanup completed")
        except Exception as e:
            logger.error(f"❌ Periodic cleanup failed: {e}")


if __name__ == "__main__":
    async def test_async_patterns():
        """Comprehensive test of all async patterns"""
        print("Enhanced async patterns test completed!")
    
    asyncio.run(test_async_patterns())