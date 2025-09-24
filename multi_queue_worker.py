#!/usr/bin/env python3
"""
Multi-Queue Worker for Facebook Post Monitor - Enterprise Edition Phase 3.1
Worker có thể lắng nghe multiple queues với priority khác nhau

Vai trò:
- Consumer thông minh cho multiple Redis queues  
- Simplified task processing (TRACKING = DISCOVERY unified)
- Tái sử dụng tất cả logic từ worker.py (SessionManager, ProxyManager, ScraperWorker)
- Support specialized worker types hoặc generalist workers
"""

import redis
import sys
import io

# Fix encoding cho Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


import json
import asyncio
import os
import time
import uuid
from datetime import datetime
from typing import Optional, Any, Dict, List, Tuple
from playwright.async_api import (
    async_playwright, Page, BrowserContext, Playwright
)

from core.database_manager import DatabaseManager
# SỬA LỖI: Import ScraperCoordinator thay vì ScraperWorker cũ
from scrapers.scraper_coordinator import ScraperCoordinator, CaptchaException
from core.session_manager import SessionManager, AccountRole
from core.proxy_manager import ProxyManager
from utils.browser_config import get_browser_launch_options, get_init_script, get_browser_args
from utils.circuit_breaker import (
    CircuitBreakerConfig, CircuitBreakerError,
    ExponentialBackoff, circuit_breaker_registry
)
from multi_queue_config import (
    MultiQueueConfig, QueueType
)
from logging_config import get_logger

# Configuration management with fallback (tái sử dụng từ worker.py)
class FallbackConfig:
    failure_threshold = 3
    checkout_timeout = 30
    headless = True
    max_tasks_per_cleanup = 1000
    stats_log_interval = 5
    backoff_base_delay = 1.0
    backoff_max_delay = 30.0
    database_failure_threshold = 3
    database_recovery_timeout = 30
    session_failure_threshold = 5
    session_recovery_timeout = 60
    browser_failure_threshold = 3
    browser_recovery_timeout = 45
    scraper_failure_threshold = 4
    scraper_recovery_timeout = 120


class FallbackSettings:
    def __init__(self):
        self.session = FallbackConfig()
        self.worker = FallbackConfig()
        self.circuit_breaker = FallbackConfig()
        self.redis = FallbackConfig()


# Import settings with fallback
try:
    from config import settings
except ImportError:
    settings = FallbackSettings()

# Get module logger
logger = get_logger(__name__)


class MultiQueueWorker:
    """
    Advanced consumer có thể xử lý multiple queues với priority
    
    Tái sử dụng 100% logic từ TaskWorker nhưng với khả năng:
    - Lắng nghe multiple queues theo priority order
    - Smart queue selection based on task availability
    - Dynamic worker allocation theo load
    """
    
    def __init__(
        self, 
        worker_id: str, 
        queue_types: List[QueueType], 
        config: MultiQueueConfig,
        redis_client: Optional[redis.Redis] = None,
        db_manager: Optional[DatabaseManager] = None,
        session_manager: Optional[SessionManager] = None,
        proxy_manager: Optional[ProxyManager] = None,
        settings: Optional[Any] = None
    ):
        """
        Initialize multi-queue worker với dependency injection và REAL SCRAPING
        
        Args:
            worker_id: Unique identifier cho worker
            queue_types: List of QueueType enums to process
            config: Multi-queue configuration
            redis_client: Redis client instance (injectable)
            db_manager: Database manager instance (injectable)
            session_manager: Session manager instance (injectable)
            proxy_manager: Proxy manager instance (injectable)
            settings: Configuration settings (injectable)
        """
        self.worker_id = worker_id
        self.queue_types = queue_types
        self.config = config
        
        # Get logger from centralized logging
        from logging_config import get_logger
        self.logger = get_logger(f"{__name__}.{worker_id}")
        
        # Use injected dependencies or create defaults
        if settings is None:
            # Fallback to import if not injected
            try:
                from config import settings
            except ImportError:
                settings = FallbackSettings()
        self.settings = settings
        
        # Redis connection - use injected or create new
        if redis_client:
            self.redis_client = redis_client
        else:
            self.redis_client = redis.Redis(
                host=getattr(settings.redis, 'host', 'redis'),
                port=getattr(settings.redis, 'port', 6379),
                decode_responses=True
            )
        
        # Database manager - use injected or create new
        if db_manager:
            self.db_manager = db_manager
        else:
            self.db_manager = DatabaseManager()
        
        # Session manager - use injected or create new
        if session_manager:
            self.session_manager = session_manager
        else:
            self.session_manager = SessionManager()
        
        # Proxy manager - use injected or create new
        if proxy_manager:
            self.proxy_manager = proxy_manager
        else:
            self.proxy_manager = ProxyManager()
        
        # Performance metrics
        self.stats = {
            'tasks_processed': 0,
            'tasks_failed': 0,
            'tasks_by_queue': {qt.value: 0 for qt in queue_types},
            'avg_processing_time': 0,
            'start_time': datetime.now(),
            'last_log_time': time.time()
        }
        
        # Task cleanup counter
        self.task_counter = 0
        self.max_tasks_per_cleanup = getattr(settings.worker, 'max_tasks_per_cleanup', 1000)
        
        # Browser and scraper setup for REAL scraping
        self.playwright = None
        self.browser = None
        self.context = None  # Added missing context attribute
        self.page = None
        self.browser_available = True  # Track browser availability
        # SỬA LỖI: Sử dụng ScraperCoordinator
        self.scraper_coordinator = None
        
        # Tái sử dụng circuit breakers từ worker.py
        self._setup_circuit_breakers()
        
        self.logger.info(
            f"Worker {worker_id} initialized for queues: {[qt.value for qt in queue_types]}",
            extra={'worker_id': worker_id}
        )
    
    def _setup_circuit_breakers(self):
        """Setup circuit breakers for different components"""
        from utils.circuit_breaker import CircuitBreakerConfig, circuit_breaker_registry
        
        # Database circuit breaker
        db_config = CircuitBreakerConfig(
            failure_threshold=getattr(self.settings.circuit_breaker, 'database_failure_threshold', 3),
            recovery_timeout=getattr(self.settings.circuit_breaker, 'database_recovery_timeout', 30)
        )
        self.db_breaker = circuit_breaker_registry.get_breaker('database', db_config)
        
        # Session circuit breaker
        session_config = CircuitBreakerConfig(
            failure_threshold=getattr(self.settings.circuit_breaker, 'session_failure_threshold', 5),
            recovery_timeout=getattr(self.settings.circuit_breaker, 'session_recovery_timeout', 60)
        )
        self.session_breaker = circuit_breaker_registry.get_breaker('session', session_config)
        
        # Browser circuit breaker
        browser_config = CircuitBreakerConfig(
            failure_threshold=getattr(self.settings.circuit_breaker, 'browser_failure_threshold', 3),
            recovery_timeout=getattr(self.settings.circuit_breaker, 'browser_recovery_timeout', 45)
        )
        self.browser_breaker = circuit_breaker_registry.get_breaker('browser', browser_config)
        
        # Scraper circuit breaker
        scraper_config = CircuitBreakerConfig(
            failure_threshold=getattr(self.settings.circuit_breaker, 'scraper_failure_threshold', 4),
            recovery_timeout=getattr(self.settings.circuit_breaker, 'scraper_recovery_timeout', 120)
        )
        self.scraper_breaker = circuit_breaker_registry.get_breaker('scraper', scraper_config)
        
        self.logger.info("🛡️ Circuit breakers initialized: database, session, browser, scraper")
    
    def _get_appropriate_role_for_queues(self) -> AccountRole:
        """Luôn trả về MIXED vì worker SCAN làm cả hai việc."""
        return AccountRole.MIXED
    
    def _try_role_based_session_assignment(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Try to assign a session based on worker's role requirements với proxy binding
        
        Returns:
            Tuple (session_name, proxy_config) if successful, None if no suitable session available
        """
        try:
            required_role = self._get_appropriate_role_for_queues()
            self.logger.info(f"🎯 Worker {self.worker_id} requesting {required_role.value} session with bound proxy")
            
            # Use new session-proxy checkout method with extended timeout and pre-check
            self.logger.info("🔍 Checking available sessions before checkout...")
            available_sessions = len([s for s in self.session_manager.resource_pool.values() if s.status == 'READY'])
            self.logger.info(f"📊 Available sessions: {available_sessions}")
            
            result = self.session_manager.checkout_session_with_proxy(self.proxy_manager, timeout=60)
            
            if result:
                session_name, proxy_config = result
                self.logger.info(f"✅ Assigned session-proxy pair: {session_name} -> {proxy_config.get('proxy_id')}")
                return result
            
            self.logger.warning("❌ No session-proxy pairs available for assignment")
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Error in role-based session-proxy assignment: {e}")
            return None

    async def _setup_browser(self) -> bool:
        """Setup browser với session-proxy binding cho REAL scraping"""
        try:
            self.logger.info("🌐 Setting up REAL browser for Facebook scraping with session-proxy binding...")
            
            # Timeout wrapper cho toàn bộ browser setup process
            try:
                result = await asyncio.wait_for(self._setup_browser_internal(), timeout=180)  # 3 minutes max
                if result:
                    self.browser_available = True
                    self.logger.info("✅ Browser setup completed successfully with session-proxy binding")
                return result
            except asyncio.TimeoutError:
                self.logger.error("❌ Browser setup timed out after 3 minutes - worker cannot function without proper setup")
                self.browser_available = False
                return False  # Failed setup means worker should not continue
        except Exception as e:
            self.logger.error(f"❌ Browser setup failed: {e}")
            self.browser_available = False
            return False
    
    async def _setup_simple_browser(self) -> bool:
        """Simple browser setup like manual_login - no session-proxy binding"""
        try:
            self.logger.info("Setting up SIMPLE browser (like manual_login)...")
            
            # Start Playwright
            self.logger.info("DEBUG: Importing os module...")
            import os
            self.logger.info("DEBUG: Importing playwright...")
            from playwright.async_api import async_playwright
            self.logger.info("DEBUG: Importing browser config...")
            from utils.browser_config import get_browser_launch_options
            
            self.logger.info("DEBUG: Starting playwright...")
            self.playwright = await async_playwright().start()
            self.logger.info("DEBUG: Playwright started successfully")
            
            # Use first available session directory (no complex binding)
            sessions_dir = "./sessions"
            if os.path.exists(sessions_dir):
                session_dirs = [d for d in os.listdir(sessions_dir) if os.path.isdir(os.path.join(sessions_dir, d))]
                if session_dirs:
                    session_dir = os.path.join(sessions_dir, session_dirs[0])
                    self.logger.info(f"Using simple session: {session_dirs[0]}")
                else:
                    self.logger.error("No session directories found")
                    return False
            else:
                self.logger.error("Sessions directory not found")
                return False
            
            # Simple browser launch (no proxy, like manual_login)
            launch_options = get_browser_launch_options(
                user_data_dir=session_dir,
                headless=True,  # Worker runs headless
                proxy_config=None  # No proxy complexity
            )
            
            self.logger.info("Launching simple browser context...")
            self.context = await self.playwright.chromium.launch_persistent_context(**launch_options)
            self.browser = None
            self.logger.info("Simple browser setup successful!")
            return True
            
        except Exception as e:
            self.logger.error(f"Simple browser setup failed: {e}")
            return False
    
    async def _setup_browser_internal(self) -> bool:
        """Internal browser setup logic"""
        try:
            
            # Start Playwright
            self.playwright = await async_playwright().start()
            
            # Get headless setting from worker config (not scraping config)
            headless = getattr(self.settings.worker, 'headless', True)
            
            # 🔗 SESSION-PROXY BINDING ASSIGNMENT with retry mechanism
            max_retries = 3
            for attempt in range(max_retries):
                self.logger.info(f"🔄 Attempt {attempt + 1}/{max_retries}: Requesting session-proxy pair...")
                
                session_proxy_pair = self._try_role_based_session_assignment()
                if not session_proxy_pair:
                    self.logger.error(f"❌ Cannot get session-proxy pair on attempt {attempt + 1}/{max_retries}")
                    if attempt == max_retries - 1:  # Last attempt
                        return False
                    continue

                session_name, proxy_config = session_proxy_pair
                session_dir = f"./sessions/{session_name}"
                self.assigned_session_name = session_name  # Track for cleanup
                self.assigned_proxy_config = proxy_config  # Track for cleanup

                self.logger.info(f"✅ Assigned session-proxy pair: {session_name} -> {proxy_config.get('proxy_id', 'unknown')}")
                self.logger.info(f"📁 Session directory: {session_dir}")
                self.logger.info(f"🔗 Proxy config: {proxy_config.get('type', 'unknown')}://{proxy_config.get('host', 'unknown')}:{proxy_config.get('port', 'unknown')}")

                # Get browser launch options with bound proxy
                launch_options = get_browser_launch_options(
                    user_data_dir=session_dir,
                    headless=headless,
                    proxy_config=proxy_config  # 🔗 Pass bound proxy config
                )

                # If proxy validation failed, launch_options won't contain proxy
                if proxy_config and 'proxy' not in launch_options:
                    self.logger.warning(f"⚠️ Proxy {proxy_config.get('proxy_id')} failed validation, releasing and retrying...")
                    # Release this session-proxy pair
                    self.session_manager.checkin_session_with_proxy(session_name, proxy_config, self.proxy_manager)
                    if attempt < max_retries - 1:
                        continue  # Try with different proxy
                    else:
                        self.logger.warning("⚠️ All proxy attempts failed, launching without proxy...")
                        launch_options = get_browser_launch_options(
                            user_data_dir=session_dir,
                            headless=headless,
                            proxy_config=None  # No proxy
                        )

                # Try to launch browser with current configuration
                try:
                    # Launch persistent context với extended timeout và logging
                    # asyncio already imported at top level
                    self.logger.info(f"🚀 Launching browser with options: headless={launch_options.get('headless')}, proxy={'enabled' if 'proxy' in launch_options else 'disabled'}")
                    self.context = await asyncio.wait_for(
                        self.playwright.chromium.launch_persistent_context(**launch_options),
                        timeout=60  # Increased from 30 to 60 seconds
                    )
                    self.browser = None  # Không cần browser object riêng
                    self.logger.info(f"✅ Browser launched successfully with {'proxy' if 'proxy' in launch_options else 'no proxy'}")
                    break  # Success, exit retry loop

                except asyncio.TimeoutError:
                    self.logger.error(f"⏰ Browser launch timed out on attempt {attempt + 1}")
                    # Release this session-proxy pair
                    self.session_manager.checkin_session_with_proxy(session_name, proxy_config, self.proxy_manager)
                    if attempt < max_retries - 1:
                        continue  # Try again
                    else:
                        self.logger.error("❌ All browser launch attempts failed")
                        return False

                except Exception as e:
                    self.logger.error(f"❌ Browser launch failed on attempt {attempt + 1}: {e}")
                    # Release this session-proxy pair
                    self.session_manager.checkin_session_with_proxy(session_name, proxy_config, self.proxy_manager)
                    if attempt < max_retries - 1:
                        continue  # Try again
                    else:
                        self.logger.error("❌ All browser launch attempts failed")
                        return False

            if not self.context:
                self.logger.error("❌ Failed to launch browser after all attempts")
                return False
            
            # FIX: Sử dụng trang có sẵn trong context thay vì tạo mới
            # Trang có sẵn chứa session đã đăng nhập, cookies và trạng thái
            if self.context.pages:
                self.page = self.context.pages[0]
                self.logger.info("✅ Using existing page with session data")
            else:
                # Fallback: tạo trang mới nếu không có sẵn (hiếm khi xảy ra)
                self.page = await self.context.new_page()
                self.logger.info("⚠️ Created new page (no existing session found)")
            
            # Add stealth scripts
            init_script = get_init_script()
            await self.page.add_init_script(init_script)
            
            # SỬA LỖI: Khởi tạo ScraperCoordinator thay vì ScraperWorker
            self.scraper_coordinator = ScraperCoordinator(self.db_manager, self.page)
            
            # ENHANCED LOGGING: Ghi lại chi tiết session và proxy assignment
            session_info = f"Session: {self.assigned_session_name}"
            proxy_info = "No Proxy"
            if self.assigned_proxy_config:
                proxy_id = self.assigned_proxy_config.get('proxy_id', 'unknown')
                proxy_host = self.assigned_proxy_config.get('host', 'unknown')  
                proxy_port = self.assigned_proxy_config.get('port', 'unknown')
                proxy_info = f"Proxy: {proxy_id} ({proxy_host}:{proxy_port})"
            
            self.logger.info(f"✅ PRODUCTION BROWSER SETUP COMPLETED!")
            self.logger.info(f"📋 {session_info}")
            self.logger.info(f"🌐 {proxy_info}")
            self.logger.info(f"🔧 Worker {self.worker_id} ready for production scraping")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Browser setup failed: {e}")
            await self._cleanup_browser()
            return False
    
    async def _cleanup_browser(self):
        """Cleanup browser resources"""
        try:
            if self.context:
                await self.context.close()
            # Note: persistent context tự động đóng browser
            if self.playwright:
                await self.playwright.stop()
                
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None
            # SỬA LỖI: Dọn dẹp ScraperCoordinator
            self.scraper_coordinator = None
            
            self.logger.info("🧹 Browser resources cleaned up")
            
        except Exception as e:
            self.logger.error(f"❌ Browser cleanup error: {e}")

    async def process_queues(self):
        """
        Main processing loop for multi-queue worker với REAL browser scraping
        """
        # Import modules at top level to avoid subprocess import hang
        self.logger.info("DEBUG: Entering process_queues method")
        
        try:
            import time
            self.logger.info("DEBUG: time module imported successfully")
        except Exception as e:
            self.logger.error(f"ERROR importing time: {e}")
            return
        
        try:
            start_time = time.time()
            self.logger.info(f"DEBUG: time.time() called: {start_time}")
        except Exception as e:
            self.logger.error(f"ERROR calling time.time(): {e}")
            return
            
        self.logger.info("Starting multi-queue processing loop with REAL SCRAPING...")
        self.logger.info(f"Step 1: Start time recorded: {start_time}")
        
        try:
            self.logger.info("Step 2: Formatting queue types...")
            queue_names = str([qt.value for qt in self.queue_types])
            self.logger.info(f"Queue priority order: {queue_names}")
        except Exception as e:
            self.logger.error(f"Error formatting queue types: {e}")
            self.logger.info("Queue priority order: [unable to format]")
        
        self.logger.info("Step 3: Time calculation...")
        current_time = time.time()
        elapsed = current_time - start_time
        self.logger.info(f"Step 4: About to start browser setup... (after {elapsed:.1f}s)")
        # FIXED: Use proper browser setup with session-proxy binding 
        try:
            browser_setup = await asyncio.wait_for(self._setup_browser(), timeout=180)  # 3 minutes for proper setup
        except asyncio.TimeoutError:
            self.logger.error("❌ Browser setup timeout after 3 minutes - worker will exit")
            return  # Exit worker completely on setup failure
        except Exception as e:
            self.logger.error(f"❌ Browser setup failed with error: {e}")
            return  # Exit worker completely on setup failure
        
        if not browser_setup:
            self.logger.error("❌ Cannot start worker without proper browser setup! Exiting.")
            return
        self.logger.info("Browser setup completed, starting task processing...")
        
        try:
            while True:
                task_found = False
                
                # Process queues in priority order
                for queue_type in self.queue_types:
                    queue_name = queue_type.value
                    
                    try:
                        # Try to get a task from this queue
                        task = self.redis_client.blpop([queue_name], timeout=1)
                        
                        if task:
                            _, task_data = task
                            task_found = True
                            
                            # Parse task data with improved error handling
                            message = json.loads(task_data)
                            task_info = message.get('payload') # <-- FIX: Mở "phong bì" payload

                            # FIXED: Comprehensive task_info validation
                            if not task_info:
                                self.logger.error(f"❌ Invalid message format in {queue_name}: missing payload. Skipping task.")
                                continue
                            
                            if not isinstance(task_info, dict):
                                self.logger.error(f"❌ Invalid task_info type in {queue_name}: expected dict, got {type(task_info)}. Skipping task.")
                                continue
                            
                            if not task_info.get('url'):
                                self.logger.error(f"❌ Invalid task in {queue_name}: missing URL. Skipping task.")
                                continue
                            
                            self.logger.info(f"🔄 REAL SCRAPING task from {queue_name}: {task_info.get('url', 'unknown')[:50]}")
                            
                            # Process the task with REAL SCRAPING
                            await self._process_task(task_info) # Xử lý task SCAN duy nhất
                            
                            # Update statistics
                            self.stats['tasks_processed'] += 1
                            self.stats['tasks_by_queue'][queue_name] += 1
                            
                            # 🎯 REPORT SUCCESS TO SESSION MANAGER
                            if hasattr(self, 'assigned_session_name') and self.assigned_session_name:
                                self.session_manager.report_outcome(self.assigned_session_name, 'success')
                            
                            # Log progress periodically
                            if time.time() - self.stats['last_log_time'] > 30:  # Every 30 seconds
                                self._log_stats()
                            
                            break  # Process one task at a time, restart priority loop
                            
                    except redis.RedisError as e:
                        self.logger.error(f"❌ Redis error for queue {queue_name}: {e}")
                        continue
                    except json.JSONDecodeError as e:
                        self.logger.error(f"❌ Invalid task data in {queue_name}: {e}")
                        continue
                    except CaptchaException as e:
                        self.logger.critical(f"🚨 CAPTCHA detected: {e}")
                        # Pause briefly and continue
                        await asyncio.sleep(60)
                        continue
                    except Exception as e:
                        self.logger.error(f"❌ Unexpected error processing {queue_name}: {e}")
                        self.stats['tasks_failed'] += 1
                        
                        # 🎯 REPORT FAILURE TO SESSION MANAGER  
                        if hasattr(self, 'assigned_session_name') and self.assigned_session_name:
                            self.session_manager.report_outcome(self.assigned_session_name, 'failure', {'error': str(e)})
                        continue
                
                # If no tasks found in any queue, wait briefly before retrying
                if not task_found:
                    await asyncio.sleep(1)
                    
        except KeyboardInterrupt:
            self.logger.info("⏹️ Received shutdown signal, stopping worker...")
        except Exception as e:
            self.logger.error(f"💥 Fatal error in processing loop: {e}")
            raise
        finally:
            await self._cleanup()
    
    async def _process_task(self, task_info: dict):
        """Xử lý một task SCAN duy nhất."""
        self.logger.debug(f"Processing SCAN task: {task_info}")
        
        if not self.scraper_coordinator:
            self.logger.error("❌ ScraperCoordinator not initialized!")
            raise Exception("ScraperCoordinator not available")
        
        try:
            await self._process_scan_real(task_info)
        except CaptchaException:
            raise # Đẩy lỗi CAPTCHA lên để xử lý đặc biệt
        except Exception as e:
            self.logger.error(f"Lỗi xử lý scan task: {e}")
            raise
    
    async def _process_scan_real(self, task_info: dict):
        """
        Process scan task với KIẾN TRÚC MỚI - unified scanning với time-based filtering
        
        Logic đơn giản: Chỉ cần gọi scraper_coordinator.process_url() 
        vì tất cả logic phức tạp đã được tích hợp sẵn trong ScraperCoordinator
        """
        target_url = task_info.get('url', '')
        self.logger.info(f"🔍 REAL SCANNING (NEW ARCHITECTURE): {target_url}")
        
        if not target_url:
            self.logger.error("❌ Scan task has no URL. Skipping.")
            return

        try:
            # KIẾN TRÚC MỚI: Chỉ cần một lệnh gọi duy nhất
            # ScraperCoordinator đã tích hợp:
            # - Start date checking
            # - Time-based filtering  
            # - Discovery + tracking logic
            # - Atomic dual-stream processing
            scraping_result = await self.scraper_coordinator.process_url(target_url)
            
            self.logger.info(f"✅ SCAN (NEW ARCHITECTURE) results:")
            self.logger.info(f"   📊 New posts discovered: {scraping_result.get('new_posts', 0)}")
            self.logger.info(f"   📈 Interactions logged: {scraping_result.get('interactions_logged', 0)}")
            self.logger.info(f"   ❌ Errors: {scraping_result.get('errors', 0)}")
            
            if scraping_result.get('errors', 0) > 0:
                self.logger.warning(f"⚠️ Scan had {scraping_result['errors']} errors")
                
        except CaptchaException:
            # Re-raise for special handling
            raise
        except Exception as e:
            self.logger.error(f"❌ Scan scraping failed: {e}")
            raise
    
    def _log_stats(self):
        """Log worker statistics"""
        uptime = datetime.now() - self.stats['start_time']
        
        self.logger.info(
            f"📊 Worker Stats - "
            f"Processed: {self.stats['tasks_processed']}, "
            f"Failed: {self.stats['tasks_failed']}, "
            f"Uptime: {uptime}"
        )
        
        for queue_name, count in self.stats['tasks_by_queue'].items():
            if count > 0:
                self.logger.info(f"   {queue_name}: {count} tasks")
        
        self.stats['last_log_time'] = time.time()
    
    async def _cleanup(self):
        """Cleanup ALL resources including browser, session-proxy pair"""
        self.logger.info("🧹 Cleaning up ALL worker resources...")
        
        await self._cleanup_browser()
        
        # 🔗 PRODUCTION: Consistent session-proxy pair checkin
        if (hasattr(self, 'assigned_session_name') and self.assigned_session_name and 
            hasattr(self, 'assigned_proxy_config') and self.assigned_proxy_config):
            try:
                self.session_manager.checkin_session_with_proxy(
                    self.assigned_session_name,
                    self.assigned_proxy_config,
                    self.proxy_manager,
                    session_status="READY",
                    proxy_status="READY"
                )
                self.logger.info(f"✅ Checked in session-proxy pair: {self.assigned_session_name} -> {self.assigned_proxy_config.get('proxy_id')}")
            except Exception as e:
                self.logger.error(f"❌ Error checking in session-proxy pair: {e}")
                
                # 🔧 EMERGENCY FALLBACK: Separate checkin only when unified method fails
                # This preserves resources in case of binding system issues
                try:
                    if self.assigned_session_name:
                        self.session_manager.checkin_session(self.assigned_session_name)
                        self.logger.info(f"🚨 Emergency session checkin: {self.assigned_session_name}")
                    if self.assigned_proxy_config:
                        self.proxy_manager.checkin_proxy(self.assigned_proxy_config)
                        self.logger.info(f"🚨 Emergency proxy checkin: {self.assigned_proxy_config.get('proxy_id')}")
                except Exception as fallback_error:
                    self.logger.error(f"❌ Emergency fallback also failed: {fallback_error}")
                    # Log for monitoring - this indicates serious system issues
                    self.logger.critical(f"🚨 CRITICAL: Both unified and emergency checkin failed for session {self.assigned_session_name}")
        
        # Reset assignments to prevent double-checkin
        self.assigned_session_name = None
        self.assigned_proxy_config = None
        
        try:
            if hasattr(self, 'db_manager') and self.db_manager:
                self.db_manager.close()
            if hasattr(self, 'redis_client') and self.redis_client:
                self.redis_client.close()
        except Exception as e:
            self.logger.error(f"❌ Error during cleanup: {e}")

async def run_worker_with_auto_restart(worker: MultiQueueWorker, max_restarts: int = 5, restart_delay: int = 30):
    """
    Wrapper function để chạy worker với auto-restart mechanism
    
    Args:
        worker: MultiQueueWorker instance
        max_restarts: Số lần restart tối đa
        restart_delay: Thời gian delay giữa các lần restart (seconds)
    """
    restart_count = 0
    
    while restart_count < max_restarts:
        try:
            logger.info(f"🚀 Starting worker {worker.worker_id} (attempt {restart_count + 1}/{max_restarts + 1})")
            await worker.process_queues()
            
            # Nếu worker exit gracefully (không có exception), break
            logger.info(f"✅ Worker {worker.worker_id} completed gracefully")
            break
            
        except KeyboardInterrupt:
            logger.info(f"⏹️ Worker {worker.worker_id} interrupted by user")
            break
            
        except Exception as e:
            restart_count += 1
            logger.error(f"💥 Worker {worker.worker_id} crashed: {e}")
            
            if restart_count < max_restarts:
                logger.info(f"🔄 Restarting worker in {restart_delay} seconds... (attempt {restart_count + 1}/{max_restarts})")
                await asyncio.sleep(restart_delay)
                
                # Reset worker state for restart
                try:
                    await worker._cleanup()
                    logger.info(f"🧹 Worker {worker.worker_id} cleaned up for restart")
                except Exception as cleanup_error:
                    logger.error(f"❌ Cleanup error: {cleanup_error}")
            else:
                logger.error(f"❌ Worker {worker.worker_id} exceeded max restarts ({max_restarts}), giving up")
                break
    
    logger.info(f"🏁 Worker {worker.worker_id} finished after {restart_count} restarts")


def main():
    """Hàm main để chạy multi-queue worker với dependency injection mặc định"""
    import argparse
    from logging_config import setup_application_logging, get_logger
    from dependency_injection import ServiceManager
    
    # Setup centralized logging
    setup_application_logging()
    
    parser = argparse.ArgumentParser(description="Multi-Queue Worker for Facebook Post Monitor")
    parser.add_argument("--worker-id", type=str, help="Worker ID (auto-generate if not provided)")
    parser.add_argument("--queues", type=str, nargs="+", 
                       choices=["scan", "all"],
                       default=["all"],
                       help="Queues to listen to")
    parser.add_argument("--headless", action="store_true", default=False, help="Run browser in headless mode")
    parser.add_argument("--no-headless", action="store_true", default=False, help="Run browser in visible mode (override headless)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--auto-restart", action="store_true", default=False, help="Enable auto-restart on worker crash")
    parser.add_argument("--max-restarts", type=int, default=5, help="Maximum number of restarts (default: 5)")
    parser.add_argument("--restart-delay", type=int, default=30, help="Delay between restarts in seconds (default: 30)")
    
    args = parser.parse_args()
    
    logger = get_logger(__name__)
    
    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("Debug mode enabled")
    
    # Generate worker ID if not provided
    worker_id = args.worker_id or f"worker_{uuid.uuid4().hex[:8]}"
    
    # Map queue arguments to QueueType
    if "all" in args.queues:
        queue_types = MultiQueueConfig.get_all_queues()
    else:
        queue_map = {
            "scan": QueueType.SCAN  # Only SCAN queue in unified architecture
        }
        queue_types = [queue_map[q] for q in args.queues if q in queue_map]
    
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        FACEBOOK POST MONITOR - ENTERPRISE EDITION           ║")
    print("║              MULTI-QUEUE WORKER PHASE 3.1                   ║")
    print("║                                                              ║")
    print("║  🔄 Priority-based multi-queue processing                   ║")
    print("║  ⚡ High-freq > Low-freq > Discovery                         ║")
    print("║  🎯 Intelligent task routing và proxy management            ║")
    print("║  🔧 Session pool + Proxy pool integration                   ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    
    print(f"🔄 Worker ID: {worker_id}")
    print(f"📋 Listening to queues: {[q.value for q in queue_types]}")
    print(f"🎯 Priority order: {[q.name for q in queue_types]}")
    
    # Override headless setting based on command line arguments
    override_settings = None
    if args.no_headless or not args.headless:
        # User wants visible browser mode
        print("👀 Running with VISIBLE browser (non-headless mode)")
        try:
            from config import settings as global_settings
            override_settings = global_settings
            override_settings.worker.headless = False
        except ImportError:
            # Fallback for systems without config
            class Override:
                class WorkerConfig:
                    headless = False
                worker = WorkerConfig()
            override_settings = Override()
    else:
        print("🕶️ Running in headless mode (browser hidden)")

    print("💉 Using dependency injection (default)")
    
    # Initialize ServiceManager
    service_manager = ServiceManager()
    container = service_manager.container
    
    # Get dependencies from container
    redis_client = container.get_optional('redis_client')
    db_manager = container.get_optional('database_manager')
    session_manager = container.get_optional('session_manager')
    proxy_manager = container.get_optional('proxy_manager')
    config = container.get_optional('config') or override_settings
    
    # Apply headless override to injected config
    if override_settings and config:
        config.worker.headless = override_settings.worker.headless
    
    # Create worker with injected dependencies
    worker = MultiQueueWorker(
        worker_id=worker_id,
        queue_types=queue_types,
        config=MultiQueueConfig(),
        redis_client=redis_client,
        db_manager=db_manager,
        session_manager=session_manager,
        proxy_manager=proxy_manager,
        settings=config or override_settings
    )
    
    print()
    
    # Run worker with optional auto-restart
    if args.auto_restart:
        print(f"🔄 Auto-restart enabled: max {args.max_restarts} restarts, {args.restart_delay}s delay")
        print("⚠️  Worker will automatically restart on crashes")
        print()
        asyncio.run(run_worker_with_auto_restart(worker, args.max_restarts, args.restart_delay))
    else:
        print("🚀 Running worker without auto-restart")
        print()
        asyncio.run(worker.process_queues())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Worker bị dừng")
    except Exception as e:
        print(f"\n💥 Lỗi: {e}")
        import traceback
        traceback.print_exc()


