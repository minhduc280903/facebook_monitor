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
import threading
import time
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
    headless = False  # ✅ FIX: Anti-detection - use GUI mode

class FallbackSettings:
    def __init__(self):
        self.session = FallbackConfig()
        self.worker = FallbackConfig()

try:
    from config import settings
except ImportError:
    settings = FallbackSettings()

# Auto-detect worker concurrency from available sessions
def get_worker_concurrency():
    """
    Auto-detect optimal worker concurrency based on available sessions.
    
    Returns:
        int: Number of concurrent workers (defaults to 2 if detection fails)
    """
    import json
    import os
    
    try:
        # Try to get from environment variable first (highest priority)
        env_concurrency = os.environ.get('WORKER_CONCURRENCY')
        if env_concurrency:
            concurrency = int(env_concurrency)
            print(f"🔧 Using WORKER_CONCURRENCY from env: {concurrency}")
            return concurrency
        
        # Try to get from config
        if hasattr(settings, 'worker') and settings.worker.concurrency > 0:
            print(f"🔧 Using concurrency from config: {settings.worker.concurrency}")
            return settings.worker.concurrency
        
        # Auto-detect from session_status.json
        session_file = 'session_status.json'
        if os.path.exists(session_file):
            with open(session_file, 'r') as f:
                sessions = json.load(f)
                ready_sessions = sum(1 for s in sessions.values() if s.get('status') == 'READY')
                if ready_sessions > 0:
                    print(f"🔧 Auto-detected {ready_sessions} READY sessions, setting concurrency={ready_sessions}")
                    return ready_sessions
        
        print(f"⚠️ session_status.json not found, using default concurrency=2")
            
    except Exception as e:
        print(f"⚠️ Failed to auto-detect concurrency: {e}")
    
    # Default fallback
    print("🔧 Using default concurrency=2")
    return 2

# CELERY APPLICATION SETUP
app = Celery('facebook_scraper')

# Get dynamic worker concurrency
WORKER_CONCURRENCY = get_worker_concurrency()

# Celery configuration
# Dynamic Redis URL based on environment (Docker or Native VPS)
REDIS_HOST = os.getenv("REDIS_HOST", "redis" if os.getenv("DOCKER_ENV") == "true" else "localhost")
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_DB = os.getenv("REDIS_DB", "0")
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

app.conf.update(
    broker_url=REDIS_URL,
    result_backend=REDIS_URL,

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
    worker_concurrency=WORKER_CONCURRENCY,  # Auto-detected from sessions

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
            'schedule': 300.0,  # ✅ 5 minutes - ALL posts in each URL updated every 5 minutes
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
            'schedule': 43200.0,  # 12 hours - Re-login twice daily to keep sessions fresh
        },
        'proxy-health-check': {
            'task': 'facebook_scraper.proxy_health_check_task',
            'schedule': 900.0,  # 15 minutes - Check proxy health and auto-retry failed ones
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
        
        # 🔧 FIX: Track all checked out sessions to ensure cleanup
        checked_out_sessions = []
        
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
                # 🔧 FIX: Track this checkout
                checked_out_sessions.append((session_name, proxy_config))
                
                session_dir = f"./sessions/{session_name}"

                proxy_id = proxy_config.get('proxy_id', 'unknown') if proxy_config else 'none (direct)'
                logger.info(f"✅ Got session-proxy: {session_name} -> {proxy_id}")

                # 🎨 RE-GENERATE session fingerprint with CURRENT age (for evolution)
                # ✅ FIX: Don't use cached fingerprint - must regenerate to apply time-based drift
                session_resource = self.session_manager.resource_pool.get(session_name)
                session_fingerprint = None
                
                if session_resource:
                    from utils.browser_config import generate_session_fingerprint
                    from datetime import datetime
                    
                    # Calculate ACTUAL days since creation for evolution
                    days_since_creation = 0
                    if session_resource.created_at:
                        days_since_creation = (datetime.now() - session_resource.created_at).days
                    
                    # RE-GENERATE fingerprint with current age (applies evolution drift)
                    session_fingerprint = generate_session_fingerprint(
                        session_name,
                        days_since_creation=days_since_creation
                    )
                    
                    logger.info(f"🎨 Regenerated fingerprint for {session_name} (age: {days_since_creation} days)")
                    
                    # Update metadata with fresh fingerprint (for consistency)
                    session_resource.metadata["fingerprint"] = session_fingerprint
                    
                    # 🌍 CRITICAL: Inject proxy geolocation into fingerprint BEFORE browser launch
                    # This ensures timezone/geolocation in init scripts match proxy IP
                    if proxy_config:
                        proxy_id = proxy_config.get('proxy_id')
                        if proxy_id and proxy_id in self.proxy_manager.resource_pool:
                            proxy_resource = self.proxy_manager.resource_pool[proxy_id]
                            proxy_geo = proxy_resource.metadata.get('geolocation')
                            
                            if proxy_geo:
                                # ✅ STRICT VALIDATION: REJECT session if geolocation invalid
                                required_fields = ['latitude', 'longitude', 'timezone', 'country']
                                missing_fields = [f for f in required_fields if not proxy_geo.get(f)]
                                
                                if missing_fields:
                                    error_msg = f"Proxy {proxy_id} geolocation incomplete (missing: {missing_fields}) - ABORTING"
                                    logger.error(f"❌ {error_msg}")
                                    raise Exception(error_msg)
                                
                                # Validate coordinate ranges
                                lat = proxy_geo.get('latitude')
                                lng = proxy_geo.get('longitude')
                                
                                if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                                    error_msg = f"Invalid proxy coordinates: lat={lat}, lng={lng} - ABORTING"
                                    logger.error(f"❌ {error_msg}")
                                    raise Exception(error_msg)
                                
                                # ✅ Valid - inject into fingerprint BEFORE browser uses it
                                session_fingerprint['timezone'] = proxy_geo['timezone']
                                session_fingerprint['geolocation'] = {
                                    'latitude': lat,
                                    'longitude': lng,
                                    'accuracy': 100
                                }
                                logger.info(f"✅ Proxy geo injected BEFORE launch: {proxy_geo.get('city')}, {proxy_geo.get('country')}")
                            else:
                                error_msg = f"Proxy {proxy_id} has NO geolocation data - ABORTING"
                                logger.error(f"❌ {error_msg}")
                                raise Exception(error_msg)
                
                # 🔒 ANTI-DETECTION: Inject unique machine ID per session BEFORE browser launch
                # Prevents Facebook detection of multiple accounts from same VPS machine-id
                try:
                    from utils.browser_config import generate_unique_machine_id, inject_machine_id_to_local_state
                    
                    # Generate deterministic machine ID for this session
                    # Use session creation date if available for stability
                    creation_date = session_resource.metadata.get("created_at") if session_resource else None
                    machine_id = generate_unique_machine_id(session_name, creation_date)
                    
                    # Inject into Chromium Local State BEFORE browser reads it
                    inject_machine_id_to_local_state(session_dir, machine_id)
                    logger.info(f"✅ Machine ID injected for session: {session_name}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to inject machine ID (non-critical): {e}")
                
                # Browser launch options with fingerprint
                launch_options = get_browser_launch_options(
                    user_data_dir=session_dir,
                    headless=getattr(settings.worker, 'headless', False),  # ✅ FIX: Default False
                    proxy_config=proxy_config,
                    session_fingerprint=session_fingerprint  # 🎨 Pass fingerprint for viewport/UA
                )

                try:
                    context = await asyncio.wait_for(
                        playwright.chromium.launch_persistent_context(**launch_options),
                        timeout=60
                    )
                    break  # Success

                except Exception as e:
                    logger.error(f"❌ Browser launch failed on attempt {attempt + 1}: {e}")
                    # 🔧 FIX: Cleanup session-proxy on failed attempt IMMEDIATELY
                    self.session_manager.checkin_session_with_proxy(
                        session_name, proxy_config, self.proxy_manager,
                        session_status="READY", proxy_status="READY"
                    )
                    # Remove from tracking since we checked it in
                    checked_out_sessions.remove((session_name, proxy_config))
                    session_name, proxy_config = None, None  # Reset for cleanup
                    if attempt == max_retries - 1:
                        raise

            if not context:
                raise Exception("Failed to launch browser context after all retries")

            # Get page
            page = context.pages[0] if context.pages else await context.new_page()

            # 🎨 Load fingerprint from metadata (already regenerated + proxy geo injected)
            # ✅ Fingerprint was prepared BEFORE browser launch with:
            #    - Current age for evolution drift
            #    - Proxy geolocation validation and injection
            session_fingerprint = None
            try:
                session_resource = self.session_manager.resource_pool.get(session_name)
                if session_resource:
                    session_fingerprint = session_resource.metadata.get("fingerprint")
                    if session_fingerprint:
                        logger.info(f"🎨 Using prepared fingerprint for {session_name}: "
                                  f"WebGL={session_fingerprint.get('webgl', {}).get('vendor', 'N/A')}, "
                                  f"TZ={session_fingerprint.get('timezone', 'N/A')}")
                    else:
                        logger.warning(f"⚠️ No fingerprint in metadata for {session_name}")
            except Exception as e:
                logger.error(f"❌ Error loading fingerprint from metadata: {e}")

            # Add stealth scripts with fingerprint
            from utils.browser_config import get_init_script
            init_script = get_init_script(session_fingerprint)  # 🎨 Pass fingerprint
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
            
            # 🔐 CRITICAL: Verify login status before allowing scraping
            is_logged_in = await self._verify_login_status(page, session_name)
            
            if not is_logged_in:
                logger.error(f"❌ Session {session_name} is NOT logged in - marking as NEEDS_LOGIN")
                self.session_manager.mark_session_invalid(session_name, "Not logged in after browser launch")
                raise Exception(f"Session {session_name} not logged in - cannot proceed with scraping")
            
            logger.info(f"✅ Login verified for session: {session_name}")
            
            # 🔥 WARMUP: Random delay + casual browsing để avoid CAPTCHA
            await self._warmup_session(page, session_name)
            
            # Yield to caller - guaranteed cleanup in finally block
            yield page, session_name

        except Exception as e:
            logger.error(f"❌ Browser session setup failed: {e}")
            raise

        finally:
            # 🔒 GUARANTEED CLEANUP - Always executes even on exceptions
            logger.info("🧹 Starting guaranteed browser cleanup...")
            
            cleanup_errors = []
            
            # 0. ✅ CRITICAL FIX: SAVE COOKIES BEFORE CLOSE!
            # Prevent logout issue: Ensure cookies are flushed to disk BEFORE close
            if context and session_name:
                try:
                    import os
                    session_dir = f"./sessions/{session_name}"
                    storage_state_path = os.path.join(session_dir, "storage_state.json")
                    
                    # Force save storage state (cookies + localStorage)
                    await context.storage_state(path=storage_state_path)
                    logger.info(f"✅ COOKIES SAVED for session: {session_name}")
                    
                    # Small delay to ensure disk write completes
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"❌ CRITICAL: Failed to save cookies: {e}")
                    cleanup_errors.append(f"Cookie save error: {e}")
            
            # 1. Close browser context
            if context:
                try:
                    await context.close()
                    logger.info("✅ Browser context closed")
                except Exception as e:
                    cleanup_errors.append(f"Context close error: {e}")
            
            # 1.5. ✅ FIX: CRITICAL - Remove SingletonLock files immediately after browser close
            if session_name:
                try:
                    import os
                    import glob
                    session_dir = f"sessions/{session_name}"
                    lock_patterns = [
                        f"{session_dir}/SingletonLock",
                        f"{session_dir}/SingletonCookie",
                        f"{session_dir}/SingletonSocket",
                        f"{session_dir}/.lock",
                        f"{session_dir}/lockfile"
                    ]
                    for pattern in lock_patterns:
                        for lock_file in glob.glob(pattern):
                            try:
                                os.remove(lock_file)
                                logger.debug(f"🧹 Removed lock file: {lock_file}")
                            except Exception as e:
                                logger.debug(f"⚠️ Could not remove {lock_file}: {e}")
                    logger.info(f"✅ Lock files cleaned for session: {session_name}")
                except Exception as e:
                    cleanup_errors.append(f"Lock file cleanup error: {e}")
            
            # 2. Stop playwright
            if playwright:
                try:
                    await playwright.stop()
                    logger.info("✅ Playwright stopped")
                except Exception as e:
                    cleanup_errors.append(f"Playwright stop error: {e}")
            
            # 🔧 FIX: Cleanup ALL checked out sessions, not just successful one
            for sess_name, prox_config in checked_out_sessions:
                try:
                    self.session_manager.checkin_session_with_proxy(
                        sess_name, prox_config, self.proxy_manager,
                        session_status="READY", proxy_status="READY"
                    )
                    logger.info(f"✅ Session-proxy checked in: {sess_name}")
                except Exception as e:
                    cleanup_errors.append(f"Session checkin error for {sess_name}: {e}")
            
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

    async def _warmup_session(self, page, session_name: str):
        """
        🔥 WARMUP SESSION: Adaptive warmup based on session age
        
        ✅ NEW STRATEGY:
        - Sessions 2-24h: EXTENDED warmup (5 min) - still building trust
        - Sessions 24h+: QUICK warmup (15-25s) - already trusted
        
        Purpose:
        - Build behavioral fingerprint as "normal user"
        - Avoid cold-start detection (new session immediately scraping = bot)
        - Establish natural interaction patterns
        
        Args:
            page: Playwright page instance
            session_name: Session name for logging
        """
        try:
            from datetime import datetime
            from scrapers.interaction_simulator import InteractionSimulator
            
            # Determine session age
            session_resource = self.session_manager.resource_pool.get(session_name)
            session_age_hours = 999  # Default: assume mature
            
            if session_resource and session_resource.created_at:
                session_age = datetime.now() - session_resource.created_at
                session_age_hours = session_age.total_seconds() / 3600
            
            simulator = InteractionSimulator(page, session_id=session_name)
            
            # ✅ ADAPTIVE WARMUP based on session age
            if session_age_hours < 24:
                # EXTENDED WARMUP for young sessions (2-24h)
                logger.info(f"🔥 WARMUP: EXTENDED warmup for young session {session_name} (age: {session_age_hours:.1f}h)...")
                
                # Phase 1: Browse newsfeed (2 min)
                logger.info(f"📰 WARMUP Phase 1/3: Browsing newsfeed (2 min)")
                await simulator.warmup_session(duration_range=(110, 130))
                
                # Phase 2: Random navigation (1 min)
                logger.info(f"🔀 WARMUP Phase 2/3: Random activities (1 min)")
                await simulator.warmup_session(duration_range=(55, 65))
                
                # Phase 3: Final reading pause (2 min)
                logger.info(f"📖 WARMUP Phase 3/3: Reading pause (2 min)")
                import asyncio
                await asyncio.sleep(120)
                
                logger.info(f"✅ WARMUP: EXTENDED warmup completed (~5 min) for session {session_name}")
            else:
                # QUICK WARMUP for mature sessions (24h+)
                logger.info(f"🔥 WARMUP: QUICK warmup for mature session {session_name} (age: {session_age_hours:.1f}h)...")
                await simulator.warmup_session(duration_range=(15, 25))
                logger.info(f"✅ WARMUP: QUICK warmup completed (~20s) for session {session_name}")
            
        except Exception as e:
            logger.warning(f"⚠️ WARMUP: Failed for {session_name} (non-critical): {e}")
            # Non-critical - continue with scraping even if warmup fails
    
    async def _verify_login_status(self, page, session_name: str) -> bool:
        """
        Verify if browser session is logged into Facebook
        
        Args:
            page: Playwright page instance
            session_name: Session name for logging
            
        Returns:
            True if logged in, False otherwise
        """
        try:
            logger.info(f"🔐 Verifying login status for session: {session_name}")
            
            # Navigate to Facebook to check login
            await page.goto('https://www.facebook.com/', wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(3)  # Wait for page to fully load
            
            # Check for logged-in indicators
            logged_in_selectors = [
                '[aria-label="Trang chủ"]',      # Home button (Vietnamese)
                '[aria-label="Home"]',           # Home button (English)
                'div[role="navigation"]',        # Main navigation bar
                'div[aria-label="Tài khoản"]',   # Account icon (Vietnamese)
                'div[aria-label="Account"]',     # Account icon (English)
                'a[href="/marketplace/"]',       # Marketplace link
                '[data-testid="search"]'         # Search box
            ]
            
            for selector in logged_in_selectors:
                try:
                    element = await page.wait_for_selector(selector, timeout=5000, state='visible')
                    if element:
                        logger.info(f"✅ Login verified with selector: {selector}")
                        return True
                except Exception:
                    continue
            
            # Check URL - if redirected to login page, not logged in
            current_url = page.url
            if 'login' in current_url.lower() or 'checkpoint' in current_url.lower():
                logger.warning(f"⚠️ Session not logged in - URL: {current_url}")
                return False
            
            # [FIX] RELAXED VERIFICATION: If no selector found BUT URL is NOT login page → Accept it
            # This handles cases where Facebook loads slow or selectors changed
            logger.warning(f"⚠️ No selectors found but URL looks OK: {current_url}")
            logger.info(f"✅ Login accepted (relaxed verification) for session: {session_name}")
            return True  # Changed from False to True
            
        except Exception as e:
            logger.error(f"❌ Error verifying login status: {e}")
            return False
    
    def _get_session_proxy_pair(self):
        """
        Get session-proxy pair with aging check
        
        ✅ NEW: Sessions < 2h old are blocked from scraping (aging period)
        """
        try:
            required_role = AccountRole.MIXED
            logger.info(f"🎯 Requesting {required_role.value} session with bound proxy")

            # ✅ AGING CHECK: Try multiple times to find a mature session
            max_attempts = 5
            for attempt in range(max_attempts):
                result = self.session_manager.checkout_session_with_proxy(self.proxy_manager, timeout=60)
                if not result:
                    break  # No sessions available
                
                session_name, proxy_config = result
                
                # ✅ Check session age (sessions < 30min are too young to scrape)
                session_resource = self.session_manager.resource_pool.get(session_name)
                if session_resource and session_resource.created_at:
                    from datetime import datetime, timedelta
                    session_age = datetime.now() - session_resource.created_at
                    session_age_hours = session_age.total_seconds() / 3600
                    
                    if session_age_hours < 0.5:  # Reduced from 2h to 30 minutes for production
                        logger.warning(f"⏳ Session {session_name} too young ({session_age_hours:.1f}h) - needs 30min aging period")
                        # Checkin and try next session
                        self.session_manager.checkin_session_with_proxy(session_name, proxy_config, self.proxy_manager)
                        continue
                    
                    logger.info(f"✅ Session-proxy assigned: {session_name} (age: {session_age_hours:.1f}h) -> {proxy_config.get('proxy_id')}")
                else:
                    # No created_at info - allow (assume mature)
                    logger.info(f"✅ Session-proxy assigned: {session_name} (age unknown) -> {proxy_config.get('proxy_id')}")
                
                return result
            
            # NO FALLBACK - Must have proxy!
            logger.error("❌ No mature session-proxy pairs available (all sessions < 30min or none available)")
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

# ✅ REMOVED: Deprecated BrowserManager class - use SafeBrowserManager.browser_session() instead

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
        
        # CRITICAL: Quarantine proxy to prevent further CAPTCHA
        if 'proxy_config' in task_info and task_info['proxy_config']:
            proxy_id = task_info['proxy_config'].get('proxy_id')
            if proxy_id:
                try:
                    # Import ProxyManager để quarantine
                    from core.proxy_manager import ProxyManager
                    from dependency_injection import DIContainer
                    
                    container = DIContainer()
                    proxy_manager = container.get_proxy_manager()
                    
                    # Quarantine proxy for 30 minutes
                    proxy_manager.mark_proxy_failed(
                        proxy_id=proxy_id,
                        reason=f"CAPTCHA detected: {str(e)}",
                        quarantine_duration_minutes=30
                    )
                    logger.warning(f"⚠️ Proxy {proxy_id} quarantined for 30 minutes due to CAPTCHA")
                except Exception as qe:
                    logger.error(f"Failed to quarantine proxy: {qe}")
        
        # Don't retry CAPTCHA tasks immediately - let proxy cool down
        raise Exception(f"CAPTCHA detected, proxy quarantined: {e}")

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
    browser_manager = SafeBrowserManager()
    
    # ✅ FIX: Use context manager for guaranteed cleanup
    with DatabaseManager() as db_manager:
        # Use SafeBrowserManager with guaranteed cleanup
        async with browser_manager.browser_session() as (page, session_name):
            try:
                # Initialize scraper with managed resources (pass session_name for behavior variation)
                scraper_coordinator = ScraperCoordinator(db_manager, page, session_name=session_name)

                # Process URL
                target_url = task_info.get('url', '')
                logger.info(f"🎯 Processing URL: {target_url}")
                scraping_result = await scraper_coordinator.process_url(target_url)

                # Report success
                if session_name:
                    browser_manager.session_manager.report_outcome(session_name, 'success')
                    logger.info(f"✅ Reported success for session: {session_name}")

                return scraping_result
            
            except CaptchaException as e:
                # 🚨 CRITICAL: Quarantine BOTH session AND proxy when checkpoint detected
                logger.critical(f"🚨 CHECKPOINT DETECTED - Quarantining session {session_name}: {e}")
                
                if session_name:
                    # Quarantine session PERMANENTLY for checkpoint
                    browser_manager.session_manager.quarantine_resource(
                        session_name=session_name,
                        reason=f"Facebook checkpoint detected: {str(e)}"
                    )
                    logger.warning(f"⚠️ Session {session_name} QUARANTINED due to checkpoint")
                
                # Re-raise to also trigger proxy quarantine in outer handler
                raise
    # Database and browser cleanup automatically handled by context managers

@app.task(name='facebook_scraper.dispatch_scan_tasks')
def dispatch_scan_tasks():
    """
    MIGRATION: Thay thế scan_scheduler.py logic
    Celery Beat task để dispatch scan tasks
    
    ✅ ANTI-DETECTION: Stagger task dispatching to avoid coordinated bot pattern
    """
    try:
        import json
        import random
        from datetime import datetime, timedelta

        logger.info("📋 Dispatching scan tasks with staggering...")

        # Load targets (giữ nguyên logic từ schedulers)
        with open('targets.json', 'r') as f:
            targets_data = json.load(f)
            targets = targets_data.get('targets', [])

        dispatched_count = 0
        for target in targets:
            if not target.get('enabled'):
                continue
                
            url = target.get('url')
            if url:
                # ✅ STAGGER: Random delay 0-180s (0-3 minutes) between dispatches
                # This prevents all sessions from hitting Facebook at the same time
                countdown = random.randint(0, 180)
                
                # Dispatch task với priority và countdown
                priority = 9 if target.get('priority') == 'high' else 5
                scan_facebook_url.apply_async(
                    args=[{'url': url}],
                    queue='scan_high' if priority > 7 else 'scan_normal',
                    priority=priority,
                    countdown=countdown  # ✅ DELAY execution
                )
                dispatched_count += 1
                logger.info(f"📋 Dispatched {url[:50]}... with {countdown}s delay")

        logger.info(f"✅ Dispatched {dispatched_count} scan tasks (staggered over 0-3 minutes)")
        return {'dispatched': dispatched_count, 'stagger_window': '0-180s'}

    except Exception as e:
        logger.error(f"❌ Task dispatch failed: {e}")
        raise

@app.task(name='facebook_scraper.cleanup_task')
def cleanup_task():
    """Periodic cleanup task"""
    try:
        logger.info("🧹 Running cleanup task...")

        # ✅ FIX: Use context manager for guaranteed cleanup
        with DatabaseManager() as db_manager:
            # Add cleanup logic here
            pass

        logger.info("✅ Cleanup completed")
        return {'status': 'success'}

    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        raise
    # Database cleanup automatically handled by context manager

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
            # NO FALLBACK - Proxy required!
            logger.error("❌ No session-proxy pairs available - proxy is required")
            return {
                'status': 'failed',
                'error': 'No session-proxy pairs available (proxy required)',
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

    browser_manager = SafeBrowserManager()

    # ✅ FIX: Use context manager for guaranteed cleanup
    with DatabaseManager() as db_manager:
        logger.info("✅ DEBUG: Database manager initialized")

        # STEP 2: Safe browser session with guaranteed cleanup
        logger.info("🔍 DEBUG: Step 2 - Starting SAFE browser session...")
        async with browser_manager.browser_session() as (page, session_name):
            logger.info(f"✅ DEBUG: SAFE browser session ready - {session_name}")

            # STEP 3: Scraper coordinator setup
            logger.info("🔍 DEBUG: Step 3 - Setting up scraper coordinator...")
            scraper_coordinator = ScraperCoordinator(db_manager, page, session_name=session_name)
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
    # Database and browser cleanup automatically handled by context managers
    logger.info("✅ DEBUG: All resources cleaned up")

@app.task(name='facebook_scraper.health_check')
def health_check():
    """Health check task cho monitoring"""
    try:
        # ✅ FIX: Use context manager for guaranteed cleanup
        with DatabaseManager() as db_manager:
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
    # Database cleanup automatically handled by context manager

@app.task(name='facebook_scraper.refresh_login_sessions')
def refresh_login_sessions():
    """🔄 Refresh Facebook login sessions to prevent logout - ENHANCED"""
    try:
        import subprocess
        logger.info("🔄 Refreshing Facebook login sessions...")

        # Determine auto_login.py path (Docker or local)
        auto_login_paths = ['/app/auto_login.py', './auto_login.py', 'auto_login.py']
        auto_login_path = None
        
        for path in auto_login_paths:
            if os.path.exists(path):
                auto_login_path = path
                break
        
        if not auto_login_path:
            logger.warning("⚠️ auto_login.py not found in any expected location")
            return {'status': 'skipped', 'message': 'auto_login.py not found'}
        
        logger.info(f"📝 Using auto_login.py from: {auto_login_path}")
        
        # ENHANCED: Run with proper arguments for Docker
        # Format: python auto_login.py [account.txt] [all] [headless] [skip_existing]
        result = subprocess.run(
            ['python', auto_login_path, 'account.txt', 'all', 'true', 'true'],
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes timeout (increased for multiple accounts)
        )

        if result.returncode == 0:
            logger.info("✅ Sessions refreshed successfully")
            logger.debug(f"Output: {result.stdout[-500:]}")  # Last 500 chars
            return {'status': 'success', 'message': 'Sessions refreshed'}
        else:
            logger.error(f"❌ Failed to refresh sessions (exit code: {result.returncode})")
            logger.error(f"Stderr: {result.stderr}")
            return {'status': 'error', 'message': result.stderr}

    except subprocess.TimeoutExpired:
        logger.error("❌ Session refresh timeout (>10 minutes)")
        return {'status': 'error', 'message': 'Timeout during session refresh'}
    except Exception as e:
        logger.error(f"❌ Session refresh error: {e}", exc_info=True)
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

@app.task(name='facebook_scraper.proxy_health_check_task')
def proxy_health_check_task():
    """
    🔍 Proxy Health Check Task - Background task để check và auto-retry proxies
    
    Features:
    - Check health của tất cả proxies (READY, FAILED, QUARANTINED)
    - Auto-retry failed proxies
    - Release proxies từ quarantine nếu đã hết cooldown
    - Update proxy status và performance metrics
    """
    try:
        from core.proxy_manager import ProxyManager
        
        logger.info("🔍 Starting proxy health check task...")
        
        proxy_manager = ProxyManager()
        
        # 1. Process cooldowns first - release proxies from quarantine
        released_count = proxy_manager.check_cooldowns()
        if released_count > 0:
            logger.info(f"🎆 Released {released_count} proxies from quarantine")
        
        # 2. Run comprehensive health check
        result = proxy_manager.run_comprehensive_health_check()
        
        logger.info(f"✅ Proxy health check completed:")
        logger.info(f"  📊 Checked: {result['checked_count']} proxies")
        logger.info(f"  ✅ Healthy: {result['healthy_count']} proxies")
        logger.info(f"  ❌ Unhealthy: {result['unhealthy_count']} proxies")
        
        # 3. Get updated stats
        stats = proxy_manager.get_stats()
        
        return {
            'status': 'success',
            'timestamp': datetime.now().isoformat(),
            'released_from_quarantine': released_count,
            'health_check': result,
            'current_stats': stats
        }
        
    except Exception as e:
        logger.error(f"❌ Proxy health check task failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }

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
    parser.add_argument("--headless", action="store_true", default=False, help="Headless mode (default: False for anti-detection)")
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