#!/usr/bin/env python3
"""
Celery-based Task Worker for Facebook Post Monitor - Enterprise Edition Phase 3.2
Chuyển đổi từ manual queue processing sang Celery distributed task system

MIGRATION: MultiQueueWorker -> Celery Tasks
- Giữ nguyên business logic scraping
- Thay manual Redis polling bằng Celery task system
- Automatic retries, priority queues, monitoring
"""

import sys
import io
import asyncio
import os
from typing import Dict, Any, Optional
from datetime import datetime
from celery import Celery, current_task
from celery.exceptions import Retry
from kombu import Queue

# Fix encoding cho Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Import core modules
from contextlib import asynccontextmanager
from core.database_manager import DatabaseManager
from scrapers.scraper_coordinator import ScraperCoordinator, CaptchaException
from core.session_manager import SessionManager, AccountRole
from core.proxy_manager import ProxyManager
from utils.browser_config import get_browser_launch_options
from logging_config import get_logger

# Configuration with fallback
class FallbackConfig:
    failure_threshold = 3
    checkout_timeout = 30
    headless = True

class FallbackSettings:
    def __init__(self):
        self.session = FallbackConfig()
        self.worker = FallbackConfig()

try:
    from config import settings
except ImportError:
    settings = FallbackSettings()

# CELERY APPLICATION SETUP
app = Celery('facebook_scraper')

# Celery configuration
app.conf.update(
    broker_url='redis://redis:6379/0',
    result_backend='redis://redis:6379/0',

    # Task routing với priority queues
    task_routes={
        'facebook_scraper.scan_facebook_url': {'queue': 'scan_high', 'priority': 9},
        'facebook_scraper.discovery_scan': {'queue': 'discovery', 'priority': 5},
        'facebook_scraper.cleanup_task': {'queue': 'maintenance', 'priority': 1},
        'facebook_scraper.dispatch_scan_tasks': {'queue': 'maintenance', 'priority': 8},
        'facebook_scraper.health_check': {'queue': 'maintenance', 'priority': 1},
        'facebook_scraper.browser_health_check': {'queue': 'maintenance', 'priority': 1},
        'facebook_scraper.refresh_login_sessions': {'queue': 'maintenance', 'priority': 7},
    },

    # Worker configuration
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    worker_concurrency=2,

    # Task configuration
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],

    # Retry defaults
    task_default_retry_delay=60,
    task_max_retries=3,

    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,

    # Beat schedule - THAY THẾ manual scheduling
    beat_schedule={
        'dispatch-scan-tasks': {
            'task': 'facebook_scraper.dispatch_scan_tasks',
            'schedule': 300.0,  # 5 minutes
        },
        'cleanup-old-data': {
            'task': 'facebook_scraper.cleanup_task',
            'schedule': 3600.0,  # 1 hour
        },
        'browser-health-check': {
            'task': 'facebook_scraper.browser_health_check',
            'schedule': 1800.0,  # 30 minutes - Monitor browser resources
        },
        'refresh-sessions': {
            'task': 'facebook_scraper.refresh_login_sessions',
            'schedule': 86400.0,  # 24 hours - Re-login daily to keep sessions fresh
        },
    },
    timezone='UTC',
)

logger = get_logger(__name__)

class SafeBrowserManager:
    """
    🔒 THREAD-SAFE & RESOURCE-SAFE Browser Manager with guaranteed cleanup
    
    FIXES:
    - Memory leaks từ unmanaged playwright instances
    - Zombie Chrome processes từ failed cleanup
    - Session-proxy resource leaks
    - Port exhaustion từ DevTools ports
    """

    def __init__(self):
        self.session_manager = SessionManager()
        self.proxy_manager = ProxyManager()
        # ENHANCEMENT: Track active browser PIDs to prevent zombies
        self.active_browser_pids = []
        self.pid_lock = threading.Lock()
        logger.info("🔒 SafeBrowserManager initialized with guaranteed cleanup and PID tracking")

    @asynccontextmanager
    async def browser_session(self):
        """
        🔒 GUARANTEED CLEANUP Context Manager
        
        Usage:
            async with browser_manager.browser_session() as (page, session_name):
                # Use page for scraping
                # Auto cleanup guaranteed even on exceptions
        """
        playwright = None
        context = None
        session_name = None
        proxy_config = None
        
        try:
            # Import here để tránh circular imports
            from playwright.async_api import async_playwright

            logger.info("🚀 Starting browser session with guaranteed cleanup...")
            playwright = await async_playwright().start()

            # Session-proxy binding với retry logic
            max_retries = 3
            for attempt in range(max_retries):
                logger.info(f"🔄 Browser setup attempt {attempt + 1}/{max_retries}")

                session_proxy_pair = self._get_session_proxy_pair()
                if not session_proxy_pair:
                    if attempt == max_retries - 1:
                        raise Exception("Cannot get session-proxy pair after all attempts")
                    continue

                session_name, proxy_config = session_proxy_pair
                session_dir = f"./sessions/{session_name}"

                logger.info(f"✅ Got session-proxy: {session_name} -> {proxy_config.get('proxy_id', 'unknown')}")

                # Browser launch options
                launch_options = get_browser_launch_options(
                    user_data_dir=session_dir,
                    headless=getattr(settings.worker, 'headless', True),
                    proxy_config=proxy_config
                )

                try:
                    context = await asyncio.wait_for(
                        playwright.chromium.launch_persistent_context(**launch_options),
                        timeout=60
                    )
                    break  # Success

                except Exception as e:
                    logger.error(f"❌ Browser launch failed on attempt {attempt + 1}: {e}")
                    # Cleanup session-proxy on failed attempt
                    if session_proxy_pair:
                        self.session_manager.checkin_session_with_proxy(
                            session_name, proxy_config, self.proxy_manager,
                            session_status="READY", proxy_status="READY"
                        )
                        session_name, proxy_config = None, None  # Reset for cleanup
                    if attempt == max_retries - 1:
                        raise

            if not context:
                raise Exception("Failed to launch browser context after all retries")

            # Get page
            page = context.pages[0] if context.pages else await context.new_page()

            # Add stealth scripts
            from utils.browser_config import get_init_script
            init_script = get_init_script()
            await page.add_init_script(init_script)
            
            # ENHANCEMENT: Track browser process PID for zombie prevention
            try:
                # Try to get browser process PID (Playwright internal)
                if hasattr(context, '_browser') and hasattr(context._browser, '_proc'):
                    browser_pid = context._browser._proc.pid
                    with self.pid_lock:
                        self.active_browser_pids.append(browser_pid)
                    logger.debug(f"📍 Tracking browser PID: {browser_pid}")
            except Exception as e:
                logger.debug(f"Could not track browser PID: {e}")

            logger.info(f"✅ Browser session ready: {session_name}")
            
            # Yield to caller - guaranteed cleanup in finally block
            yield page, session_name

        except Exception as e:
            logger.error(f"❌ Browser session setup failed: {e}")
            raise

        finally:
            # 🔒 GUARANTEED CLEANUP - Always executes even on exceptions
            logger.info("🧹 Starting guaranteed browser cleanup...")
            
            cleanup_errors = []
            
            # 1. Close browser context
            if context:
                try:
                    await context.close()
                    logger.info("✅ Browser context closed")
                except Exception as e:
                    cleanup_errors.append(f"Context close error: {e}")
            
            # 2. Stop playwright
            if playwright:
                try:
                    await playwright.stop()
                    logger.info("✅ Playwright stopped")
                except Exception as e:
                    cleanup_errors.append(f"Playwright stop error: {e}")
            
            # 3. Checkin session-proxy pair
            if session_name and proxy_config:
                try:
                    self.session_manager.checkin_session_with_proxy(
                        session_name, proxy_config, self.proxy_manager,
                        session_status="READY", proxy_status="READY"
                    )
                    logger.info(f"✅ Session-proxy checked in: {session_name}")
                except Exception as e:
                    cleanup_errors.append(f"Session checkin error: {e}")
            
            # 4. ENHANCEMENT: Cleanup tracked browser PIDs
            try:
                import psutil
                with self.pid_lock:
                    for pid in self.active_browser_pids[:]:  # Iterate over copy
                        try:
                            proc = psutil.Process(pid)
                            if proc.is_running():
                                proc.terminate()
                                logger.debug(f"🧹 Terminated tracked browser PID: {pid}")
                            self.active_browser_pids.remove(pid)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            # Process already gone
                            if pid in self.active_browser_pids:
                                self.active_browser_pids.remove(pid)
            except ImportError:
                pass  # psutil not available
            except Exception as e:
                cleanup_errors.append(f"PID cleanup error: {e}")
            
            # Log cleanup errors but don't raise to avoid masking original exceptions
            if cleanup_errors:
                logger.warning(f"⚠️ Cleanup completed with {len(cleanup_errors)} errors: {cleanup_errors}")
            else:
                logger.info("🎉 Browser cleanup completed successfully")

    def _get_session_proxy_pair(self):
        """Get session-proxy pair with error handling"""
        try:
            required_role = AccountRole.MIXED
            logger.info(f"🎯 Requesting {required_role.value} session with bound proxy")

            result = self.session_manager.checkout_session_with_proxy(self.proxy_manager, timeout=60)
            if result:
                session_name, proxy_config = result
                logger.info(f"✅ Session-proxy assigned: {session_name} -> {proxy_config.get('proxy_id')}")
                return result

            logger.warning("❌ No session-proxy pairs available")
            return None

        except Exception as e:
            logger.error(f"❌ Session-proxy assignment error: {e}")
            return None

    async def get_browser_health_metrics(self):
        """Get browser health metrics for monitoring"""
        try:
            import psutil
            chrome_processes = []
            total_memory = 0
            
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    if 'chrome' in proc.info['name'].lower() or 'chromium' in proc.info['name'].lower():
                        memory_mb = proc.info['memory_info'].rss / 1024 / 1024
                        chrome_processes.append({
                            'pid': proc.info['pid'],
                            'name': proc.info['name'],
                            'memory_mb': round(memory_mb, 2)
                        })
                        total_memory += memory_mb
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            return {
                'chrome_process_count': len(chrome_processes),
                'total_memory_mb': round(total_memory, 2),
                'processes': chrome_processes[:10]  # Limit to first 10 for logging
            }
        except ImportError:
            logger.warning("⚠️ psutil not available, cannot get browser health metrics")
            return {'chrome_process_count': 'unknown', 'total_memory_mb': 'unknown', 'processes': []}
        except Exception as e:
            logger.error(f"❌ Error getting browser health metrics: {e}")
            return {'chrome_process_count': 'error', 'total_memory_mb': 'error', 'processes': []}

    async def cleanup_zombie_browsers(self):
        """
        Clean up zombie Chrome/Chromium processes
        
        ENHANCED: Also cleans up orphaned processes that were supposed to be tracked
        """
        try:
            import psutil
            import signal
            
            killed_count = 0
            zombie_processes = []
            orphaned_processes = []
            
            # Get currently tracked PIDs
            with self.pid_lock:
                tracked_pids = set(self.active_browser_pids[:])
            
            for proc in psutil.process_iter(['pid', 'name', 'status', 'create_time']):
                try:
                    if ('chrome' in proc.info['name'].lower() or 'chromium' in proc.info['name'].lower()):
                        pid = proc.info['pid']
                        
                        # Kill zombie processes
                        if proc.info['status'] == psutil.STATUS_ZOMBIE:
                            zombie_processes.append(pid)
                            try:
                                proc.kill()
                                killed_count += 1
                                logger.info(f"🧹 Killed zombie Chrome process: {pid}")
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                        
                        # ENHANCEMENT: Kill orphaned Chrome processes (old, not tracked)
                        # If process is older than 1 hour and not in tracked PIDs
                        elif pid not in tracked_pids:
                            current_time = time.time()
                            process_age = current_time - proc.info['create_time']
                            
                            # Kill if older than 1 hour (likely orphaned)
                            if process_age > 3600:
                                orphaned_processes.append(pid)
                                try:
                                    proc.terminate()
                                    killed_count += 1
                                    logger.info(f"🧹 Terminated orphaned Chrome process: {pid} (age: {process_age/60:.1f}min)")
                                except (psutil.NoSuchProcess, psutil.AccessDenied):
                                    pass
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            if killed_count > 0:
                logger.info(f"🧹 Cleaned up {killed_count} Chrome processes ({len(zombie_processes)} zombies, {len(orphaned_processes)} orphaned)")
            
            return {
                'killed_zombies': len(zombie_processes), 
                'killed_orphaned': len(orphaned_processes),
                'zombie_pids': zombie_processes,
                'orphaned_pids': orphaned_processes,
                'total_killed': killed_count
            }
        except ImportError:
            logger.warning("⚠️ psutil not available, cannot cleanup zombie browsers")
            return {'killed_zombies': 0, 'killed_orphaned': 0, 'zombie_pids': [], 'orphaned_pids': [], 'total_killed': 0}
        except Exception as e:
            logger.error(f"❌ Error cleaning up zombie browsers: {e}")
            return {'killed_zombies': 0, 'killed_orphaned': 0, 'zombie_pids': [], 'orphaned_pids': [], 'total_killed': 0}

# Legacy BrowserManager for backward compatibility (DEPRECATED)
class BrowserManager:
    """⚠️ DEPRECATED: Use SafeBrowserManager instead. This class has resource leak issues."""
    
    def __init__(self):
        logger.warning("⚠️ DEPRECATED BrowserManager used. Migrate to SafeBrowserManager.browser_session()")
        self.safe_manager = SafeBrowserManager()
    
    async def get_browser_session(self):
        """⚠️ DEPRECATED: Resource leak prone method"""
        logger.error("❌ DEPRECATED get_browser_session() called. Use SafeBrowserManager.browser_session() context manager!")
        raise DeprecationWarning("Use SafeBrowserManager.browser_session() context manager for guaranteed cleanup")

# CELERY TASKS - THAY THẾ MultiQueueWorker.process_queues()

@app.task(bind=True, name='facebook_scraper.scan_facebook_url', max_retries=3)
def scan_facebook_url(self, task_info: dict):
    """
    MIGRATION: Thay thế MultiQueueWorker._process_scan_real()
    Celery task cho scanning Facebook URL
    """
    url = task_info.get('url', '')

    try:
        logger.info(f"🔍 CELERY SCAN: {url}")

        if not url:
            raise ValueError("No URL provided in task")

        # Run async scraping logic trong sync Celery task
        result = asyncio.run(_async_scan_task(task_info))

        logger.info(f"✅ Scan completed: {result}")
        return {
            'status': 'success',
            'url': url,
            'new_posts': result.get('new_posts', 0),
            'interactions_logged': result.get('interactions_logged', 0),
            'task_id': self.request.id
        }

    except CaptchaException as e:
        logger.critical(f"🚨 CAPTCHA detected: {e}")
        # CAPTCHA không retry, pause task
        raise Exception(f"CAPTCHA detected: {e}")

    except Exception as exc:
        logger.error(f"❌ Scan failed for {url}: {exc}")

        # Automatic retry với exponential backoff (thay thế manual retry logic)
        if self.request.retries < self.max_retries:
            retry_countdown = 60 * (2 ** self.request.retries)  # 60s, 120s, 240s
            logger.warning(f"🔄 Retrying in {retry_countdown}s (attempt {self.request.retries + 1})")
            raise self.retry(countdown=retry_countdown, exc=exc)

        logger.error(f"💥 Max retries exceeded for {url}")
        return {
            'status': 'failed',
            'url': url,
            'error': str(exc),
            'task_id': self.request.id
        }

async def _async_scan_task(task_info: dict):
    """
    🔒 SAFE ASYNC SCAN TASK with guaranteed resource cleanup
    
    FIXES:
    - Browser resource leaks
    - Database connection leaks  
    - Session-proxy resource leaks
    - Guaranteed cleanup even on exceptions
    """
    db_manager = None
    browser_manager = SafeBrowserManager()
    
    try:
        # Initialize database manager
        db_manager = DatabaseManager()
        
        # Use SafeBrowserManager with guaranteed cleanup
        async with browser_manager.browser_session() as (page, session_name):
            # Initialize scraper with managed resources
            scraper_coordinator = ScraperCoordinator(db_manager, page)

            # Process URL
            target_url = task_info.get('url', '')
            logger.info(f"🎯 Processing URL: {target_url}")
            scraping_result = await scraper_coordinator.process_url(target_url)

            # Report success
            if session_name:
                browser_manager.session_manager.report_outcome(session_name, 'success')
                logger.info(f"✅ Reported success for session: {session_name}")

            return scraping_result

    except Exception as e:
        logger.error(f"❌ Task failed: {e}")
        # Note: session reporting will be handled by browser context manager cleanup
        raise

    finally:
        # Cleanup database resources
        if db_manager:
            db_manager.close()
            logger.info("✅ Database manager cleaned up")
        # Browser cleanup is automatically handled by context manager

@app.task(name='facebook_scraper.dispatch_scan_tasks')
def dispatch_scan_tasks():
    """
    MIGRATION: Thay thế scan_scheduler.py logic
    Celery Beat task để dispatch scan tasks
    """
    try:
        import json
        from datetime import datetime, timedelta

        logger.info("📋 Dispatching scan tasks...")

        # Load targets (giữ nguyên logic từ schedulers)
        with open('targets.json', 'r') as f:
            targets_data = json.load(f)
            targets = targets_data.get('targets', [])

        dispatched_count = 0
        for target in targets:
            url = target.get('url')
            if url:
                # Dispatch task với priority (thay manual queue logic)
                priority = 9 if target.get('priority') == 'high' else 5
                scan_facebook_url.apply_async(
                    args=[{'url': url}],
                    queue='scan_high' if priority > 7 else 'scan_normal',
                    priority=priority
                )
                dispatched_count += 1

        logger.info(f"✅ Dispatched {dispatched_count} scan tasks")
        return {'dispatched': dispatched_count}

    except Exception as e:
        logger.error(f"❌ Task dispatch failed: {e}")
        raise

@app.task(name='facebook_scraper.cleanup_task')
def cleanup_task():
    """Periodic cleanup task"""
    db_manager = None
    try:
        logger.info("🧹 Running cleanup task...")

        # Database cleanup logic
        db_manager = DatabaseManager()
        # Add cleanup logic here

        logger.info("✅ Cleanup completed")
        return {'status': 'success'}

    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        raise
    finally:
        # Cleanup database resources to avoid connection leaks
        if db_manager:
            db_manager.close()

@app.task(name='facebook_scraper.debug_session_test')
def debug_session_test():
    """Debug task để test session availability và browser startup"""
    try:
        logger.info("🔍 DEBUG: Testing session availability and browser startup...")

        # Test session manager
        from core.session_manager import SessionManager
        from core.proxy_manager import ProxyManager

        session_manager = SessionManager()
        proxy_manager = ProxyManager()

        # Get session stats
        session_stats = session_manager.get_stats()
        logger.info(f"📊 Session stats: {session_stats}")

        # Test session checkout
        session_proxy_pair = session_manager.checkout_session_with_proxy(proxy_manager, timeout=30)
        if session_proxy_pair:
            session_name, proxy_config = session_proxy_pair
            logger.info(f"✅ Session checkout successful: {session_name} -> {proxy_config.get('proxy_id')}")

            # Checkin immediately
            session_manager.checkin_session_with_proxy(session_name, proxy_config, proxy_manager)
            logger.info(f"🔓 Session checked in: {session_name}")

            return {
                'status': 'success',
                'session_stats': session_stats,
                'test_session': session_name,
                'test_proxy': proxy_config.get('proxy_id', 'unknown')
            }
        else:
            logger.error("❌ No session-proxy pairs available")
            return {
                'status': 'failed',
                'error': 'No session-proxy pairs available',
                'session_stats': session_stats
            }

    except Exception as e:
        logger.error(f"❌ Debug test failed: {e}")
        return {
            'status': 'failed',
            'error': str(e)
        }

@app.task(bind=True, name='facebook_scraper.test_single_target')
def test_single_target(self, target_url: str):
    """Test scraping một target cụ thể với enhanced logging"""
    try:
        logger.info(f"🎯 DEBUG SCRAPE: Testing single target: {target_url}")

        # Run async scraping với enhanced logging
        result = asyncio.run(_async_scan_task_debug({'url': target_url}))

        logger.info(f"✅ Debug scrape result: {result}")
        return {
            'status': 'success',
            'target_url': target_url,
            'result': result,
            'task_id': self.request.id
        }

    except Exception as exc:
        logger.error(f"❌ Debug scrape failed for {target_url}: {exc}")
        return {
            'status': 'failed',
            'target_url': target_url,
            'error': str(exc),
            'task_id': self.request.id
        }

async def _async_scan_task_debug(task_info: dict):
    """
    🔒🔍 SAFE DEBUG ASYNC SCAN TASK with detailed logging and guaranteed cleanup
    """
    target_url = task_info.get('url', '')
    logger.info(f"🔍 DEBUG: Starting SAFE browser session setup for {target_url}")

    db_manager = None
    browser_manager = SafeBrowserManager()

    try:
        # STEP 1: Database connection test
        logger.info("🔍 DEBUG: Step 1 - Testing database connection...")
        db_manager = DatabaseManager()
        logger.info("✅ DEBUG: Database manager initialized")

        # STEP 2: Safe browser session with guaranteed cleanup
        logger.info("🔍 DEBUG: Step 2 - Starting SAFE browser session...")
        async with browser_manager.browser_session() as (page, session_name):
            logger.info(f"✅ DEBUG: SAFE browser session ready - {session_name}")

            # STEP 3: Scraper coordinator setup
            logger.info("🔍 DEBUG: Step 3 - Setting up scraper coordinator...")
            scraper_coordinator = ScraperCoordinator(db_manager, page)
            logger.info("✅ DEBUG: Scraper coordinator ready")

            # STEP 4: Navigate to URL
            logger.info(f"🔍 DEBUG: Step 4 - Navigating to {target_url}")
            await page.goto(target_url, wait_until='domcontentloaded', timeout=60000)
            logger.info("✅ DEBUG: Navigation completed")

            # STEP 5: Process URL với detailed logging
            logger.info("🔍 DEBUG: Step 5 - Processing URL for posts and reactions...")
            scraping_result = await scraper_coordinator.process_url(target_url)
            logger.info(f"✅ DEBUG: Scraping completed with result: {scraping_result}")

            # STEP 6: Success reporting
            if session_name:
                browser_manager.session_manager.report_outcome(session_name, 'success')
                logger.info(f"✅ DEBUG: Reported success for session {session_name}")

            return scraping_result
        
        # Browser cleanup is automatic from context manager

    except Exception as e:
        logger.error(f"❌ DEBUG: Error during task - {e}")
        raise

    finally:
        logger.info("🔍 DEBUG: Final cleanup phase...")
        # Cleanup database resources
        if db_manager:
            db_manager.close()
            logger.info("✅ DEBUG: Database manager closed")
        logger.info("✅ DEBUG: All resources cleaned up (browser auto-cleaned by context manager)")

@app.task(name='facebook_scraper.health_check')
def health_check():
    """Health check task cho monitoring"""
    db_manager = None
    try:
        # Test database connection
        db_manager = DatabaseManager()
        # Test Redis connection with connection pooling
        import redis
        # Use connection pool for better performance
        redis_pool = redis.ConnectionPool(host='redis', port=6379, max_connections=10, decode_responses=True)
        redis_client = redis.Redis(connection_pool=redis_pool)
        redis_client.ping()

        result = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'worker_id': current_task.request.id
        }
        return result
    except Exception as e:
        result = {
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }
        return result
    finally:
        # Cleanup database resources to avoid connection leaks
        if db_manager:
            db_manager.close()

@app.task(name='facebook_scraper.refresh_login_sessions')
def refresh_login_sessions():
    """🔄 Refresh Facebook login sessions daily to prevent logout"""
    try:
        import subprocess
        logger.info("🔄 Refreshing Facebook login sessions...")

        # Run auto_login.py if exists
        if os.path.exists('/app/auto_login.py'):
            result = subprocess.run(
                ['python', '/app/auto_login.py'],
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )

            if result.returncode == 0:
                logger.info("✅ Sessions refreshed successfully")
                return {'status': 'success', 'message': 'Sessions refreshed'}
            else:
                logger.error(f"❌ Failed to refresh sessions: {result.stderr}")
                return {'status': 'error', 'message': result.stderr}
        else:
            logger.warning("⚠️ auto_login.py not found")
            return {'status': 'skipped', 'message': 'auto_login.py not found'}

    except Exception as e:
        logger.error(f"❌ Session refresh error: {e}")
        return {'status': 'error', 'message': str(e)}

@app.task(name='facebook_scraper.browser_health_check')
def browser_health_check():
    """🔍 Browser Health Monitor - Check and cleanup browser resources"""
    
    async def _async_browser_health_check():
        browser_manager = SafeBrowserManager()
        
        try:
            # Get current browser health metrics
            health_metrics = await browser_manager.get_browser_health_metrics()
            
            logger.info(f"🔍 Browser Health Check:")
            logger.info(f"  📊 Chrome processes: {health_metrics['chrome_process_count']}")
            logger.info(f"  💾 Total memory: {health_metrics['total_memory_mb']} MB")
            
            # Alert if too many processes or high memory usage
            if isinstance(health_metrics['chrome_process_count'], int):
                if health_metrics['chrome_process_count'] > 10:
                    logger.warning(f"⚠️ High Chrome process count: {health_metrics['chrome_process_count']}")
                
                if isinstance(health_metrics['total_memory_mb'], (int, float)):
                    if health_metrics['total_memory_mb'] > 2048:  # 2GB
                        logger.warning(f"⚠️ High Chrome memory usage: {health_metrics['total_memory_mb']} MB")
            
            # Cleanup zombie processes
            cleanup_result = await browser_manager.cleanup_zombie_browsers()
            
            if cleanup_result['killed_zombies'] > 0:
                logger.info(f"🧹 Killed {cleanup_result['killed_zombies']} zombie Chrome processes")
            
            return {
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'metrics': health_metrics,
                'cleanup': cleanup_result
            }
            
        except Exception as e:
            logger.error(f"❌ Browser health check failed: {e}")
            return {
                'status': 'unhealthy', 
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    # Run async function
    return asyncio.run(_async_browser_health_check())

# COMPATIBILITY với existing code
def main():
    """
    MIGRATION: Entry point compatibility với existing docker-compose
    Thay manual worker.process_queues() bằng Celery worker command
    """
    import argparse
    from logging_config import setup_application_logging

    setup_application_logging()

    parser = argparse.ArgumentParser(description="Celery Worker for Facebook Post Monitor")
    parser.add_argument("--worker-id", type=str, help="Worker ID (for compatibility)")
    parser.add_argument("--queues", type=str, nargs="+", default=["all"], help="Queues (for compatibility)")
    parser.add_argument("--headless", action="store_true", default=True, help="Headless mode")
    parser.add_argument("--auto-restart", action="store_true", help="Auto-restart (handled by Celery)")

    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        FACEBOOK POST MONITOR - ENTERPRISE EDITION           ║")
    print("║              CELERY-BASED WORKER PHASE 3.2                  ║")
    print("║                                                              ║")
    print("║  🔄 Distributed task processing with Celery                 ║")
    print("║  ⚡ Automatic retries and priority queues                   ║")
    print("║  🎯 Built-in monitoring and scaling                         ║")
    print("║  🔧 Session-proxy binding preserved                         ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # Celery worker được start bởi docker command
    print("🚀 Starting Celery worker...")
    print("📋 Queues: scan_high, scan_normal, discovery, maintenance")
    print("🎯 Use: celery -A multi_queue_worker worker --loglevel=info")
    print()

if __name__ == "__main__":
    main()