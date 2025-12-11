#!/usr/bin/env python3
"""
Proxy Manager for Facebook Post Monitor - Enterprise Edition Phase 3.1
Quản lý pool proxy để mỗi worker sử dụng proxy riêng biệt

Mục đích:
- Quản lý pool các proxy servers done: cấu hình
- Thread-safe checkout/checkin proxies
- Tránh multiple workers sử dụng cùng proxy (tránh bị phát hiện)
- Rotation và health checking cho proxies
- Tái sử dụng pattern từ SessionManager (done: proven và hoàn thiện)
"""

import json
import os
import threading
import time
import asyncio
import requests
from contextlib import contextmanager
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from .session_manager import ManagedResource  # Reuse the ManagedResource class
from logging_config import get_logger

# Cross-process file locking (same as SessionManager)
try:
    from filelock import FileLock
    FILELOCK_AVAILABLE = True
except ImportError:
    FILELOCK_AVAILABLE = False
    FileLock = None

logger = get_logger(__name__)


class ProxyManager:
    """
    Intelligent proxy manager với performance tracking và quarantine logic
    
    Tích hợp tất cả enhancements từ SessionManager:
    
    Proxy States:
    - READY: Proxy sẵn sàng sử dụng với performance tốt
    - IN_USE: Proxy đang được worker sử dụng 
    - QUARANTINED: Proxy bị cách ly do performance kém
    - COOLDOWN: Proxy đang trong thời gian hạ nhiệt
    - DISABLED: Proxy bị vô hiệu hóa vĩnh viễn
    - TESTING: Proxy đang được health check
    """
    
    def __init__(self, db_manager = None, proxy_file: str = "proxies.txt", status_file: str = "proxy_status.json"):
        """
        Initialize ProxyManager với DATABASE-FIRST approach
        
        Args:
            db_manager: DatabaseManager instance (từ DI)
            proxy_file: Legacy file (deprecated, for migration only)
            status_file: Legacy file (deprecated, for migration only)
        """
        from config import settings
        
        # Database manager (primary storage)
        if db_manager is None:
            from core.database_manager import DatabaseManager
            self.db = DatabaseManager()
        else:
            self.db = db_manager
        
        self.proxy_file = proxy_file  # Deprecated
        self.status_file = status_file  # Deprecated
        self.lock = threading.Lock()  # Thread-safe access
        
        # Load performance thresholds from config instead of hard-coded values
        resource_config = settings.resource_management
        self.consecutive_failure_threshold = resource_config.proxy_failure_threshold
        self.success_rate_threshold = resource_config.proxy_success_rate_threshold
        self.min_tasks_for_rate_calc = resource_config.min_tasks_for_rate_calc
        self.quarantine_duration_minutes = resource_config.proxy_quarantine_minutes
        self.health_check_interval_minutes = 15  # Keep this for now
        
        # Proxy pool (in-memory cache) using ManagedResource
        self.resource_pool: Dict[str, ManagedResource] = {}
        
        # Last health check timestamp
        self.last_health_check = None
        
        # Cross-process file locking (same pattern as SessionManager)
        if FILELOCK_AVAILABLE:
            self.file_lock_path = self.status_file + ".lock"
            self.file_lock = FileLock(self.file_lock_path)
            logger.info("[LOCK] Cross-process file locking enabled for proxies")
        else:
            self.file_lock = None
            logger.warning("[WARN] FileLock not available - only thread-safe within process")
        
        # Load resources from database
        self._load_proxies_from_db()
        
        logger.info(f"[DB] ProxyManager initialized with database backend")
    
    def _load_proxies_from_db(self):
        """
        Load tất cả proxy resources từ DATABASE vào memory cache
        
        REPLACES: _load_proxies_from_file() + _load_proxies_from_db()
        
        ✅ FIX: Use stable identifier (host:port) instead of database ID
        """
        proxies = self.db.get_all_proxies()
        self.resource_pool.clear()
        
        for proxy in proxies:
            # ✅ FIX: Use stable identifier format: host:port
            resource_id = f"{proxy['host']}:{proxy['port']}"
            resource = ManagedResource(resource_id, "proxy")
            
            # Map DB fields to ManagedResource
            resource.status = proxy['status']
            resource.consecutive_failures = proxy['consecutive_failures']
            resource.total_tasks = proxy['total_tasks']
            resource.successful_tasks = proxy['successful_tasks']
            resource.success_rate = proxy['success_rate']
            resource.quarantine_reason = proxy['quarantine_reason']
            resource.quarantine_count = proxy['quarantine_count']
            resource.quarantine_until_timestamp = proxy['quarantine_until']
            resource.last_used_timestamp = proxy['last_used_at']
            
            # Store proxy config in metadata
            resource.metadata = {
                'db_id': proxy['id'],  # CRITICAL: Link to DB row
                'config': {
                    'type': proxy['proxy_type'],
                    'host': proxy['host'],
                    'port': proxy['port'],
                    'username': proxy['username'],
                    'password': proxy['password']
                },
                'response_time': proxy['response_time'],
                'last_checked': proxy['last_checked_at'].isoformat() if proxy['last_checked_at'] else None,
                'geolocation': proxy['geolocation']
            }
            
            self.resource_pool[resource_id] = resource
        
        logger.info(f"[DB] Loaded {len(self.resource_pool)} proxy resources from database (using host:port as ID)")
    
    def _sync_resources_to_db(self):
        """
        Sync in-memory proxy resources back to DATABASE
        
        REPLACES: _sync_resources_to_db()
        
        ⚠️ CALLER MUST HOLD LOCK! This method does NOT acquire locks.
        """
        for resource_id, resource in self.resource_pool.items():
            db_id = resource.metadata.get('db_id')
            if not db_id:
                logger.warning(f"[DB] Resource {resource_id} has no db_id, skipping sync")
                continue
            
            # Prepare metadata for DB update
            metadata = {
                'consecutive_failures': resource.consecutive_failures,
                'total_tasks': resource.total_tasks,
                'successful_tasks': resource.successful_tasks,
                'success_rate': resource.success_rate,
                'last_checked_at': resource.metadata.get('last_checked'),
                'response_time': resource.metadata.get('response_time'),
                'geolocation': resource.metadata.get('geolocation'),
                'quarantine_reason': resource.quarantine_reason,
                'quarantine_until': resource.quarantine_until_timestamp,
                'last_used_at': resource.last_used_timestamp
            }
            
            # Update database
            self.db.update_proxy_status(
                proxy_id=db_id,
                status=resource.status,
                metadata=metadata
            )
        
        logger.debug(f"[DB] Synced {len(self.resource_pool)} resources to database")
    
    def _process_cooldowns(self) -> int:
        """
        Process quarantined proxies and release those past cooldown period.
        
        Returns:
            Number of proxies released from quarantine
        """
        current_time = datetime.now()
        released_count = 0
        
        for resource in self.resource_pool.values():
            if resource.status == "QUARANTINED" and resource.quarantine_until_timestamp:
                if current_time >= resource.quarantine_until_timestamp:
                    resource.status = "READY"
                    resource.quarantine_until_timestamp = None
                    resource.consecutive_failures = 0  # Reset failures after cooldown
                    released_count += 1
                    logger.info(f"[SUCCESS] Proxy {resource.id} released from quarantine")
        
        return released_count
    
    def _maybe_run_health_checks(self):
        """Run health checks if enough time has passed."""
        current_time = datetime.now()
        
        if (self.last_health_check is None or 
            (current_time - self.last_health_check).total_seconds() > self.health_check_interval_minutes * 60):
            
            self.last_health_check = current_time
            self._run_background_health_checks()
    
    def _run_background_health_checks(self):
        """Run health checks on a subset of proxies."""
        # Select a few proxies for health checking (avoid blocking)
        candidates = []
        for resource in self.resource_pool.values():
            if resource.status in ["READY", "FAILED"] and len(candidates) < 3:
                candidates.append(resource)
        
        if not candidates:
            return
        
        for resource in candidates:
            try:
                resource.status = "TESTING"
                proxy_config = resource.metadata.get("config")
                if proxy_config:
                    is_healthy = self.health_check_proxy({**proxy_config, "proxy_id": resource.id})
                    if is_healthy:
                        resource.status = "READY"
                        logger.debug(f"[OK] Health check passed for proxy {resource.id}")
                    else:
                        resource.status = "FAILED"
                        resource.consecutive_failures += 1
                        logger.warning(f"[ERROR] Health check failed for proxy {resource.id}")
            except Exception as e:
                logger.error(f"[ERROR] Health check error for proxy {resource.id}: {e}")
                resource.status = "FAILED"
        
        # ✅ Sync results after batch health checks (already in caller's context)
        # NOTE: This is called from background thread, need lock
        with self.locks():
            self._sync_resources_to_db()
    
    def _log_proxy_stats(self):
        """Log current proxy statistics for debugging."""
        stats = {"ready": 0, "in_use": 0, "quarantined": 0, "failed": 0, "disabled": 0, "testing": 0}
        
        for resource in self.resource_pool.values():
            if resource.status == "READY":
                stats["ready"] += 1
            elif resource.status == "IN_USE":
                stats["in_use"] += 1
            elif resource.is_quarantined():
                stats["quarantined"] += 1
            elif resource.status == "FAILED":
                stats["failed"] += 1
            elif resource.status == "DISABLED":
                stats["disabled"] += 1
            elif resource.status == "TESTING":
                stats["testing"] += 1
        
        logger.debug(f"[STATS] Proxy stats: {stats}")
    
    def _ensure_structure(self):
        """
        ⚠️ DEPRECATED - DATABASE-FIRST APPROACH
        
        This method is NO LONGER USED - ProxyManager now loads from DATABASE.
        Kept for backward compatibility with migration scripts only.
        """
        
        # Tạo proxy file template nếu chưa có
        if not os.path.exists(self.proxy_file):
            template_content = """# Proxy Configuration File
# Format: ip:port:username:password (for authenticated proxies)
# Format: ip:port (for non-authenticated proxies)
# Format: socks5://username:password@ip:port (for SOCKS5 proxies)
#
# Examples:
# 192.168.1.100:8080:user:pass
# 203.0.113.1:3128
# socks5://user:pass@192.168.1.200:1080
#
# Add your proxy list below:

"""
            with open(self.proxy_file, 'w', encoding='utf-8') as f:
                f.write(template_content)
            logger.info(f"📄 Tạo template proxy file: {self.proxy_file}")
        
        # [OK] FIX: Tạo status file nếu chưa có HOẶC nếu empty
        needs_init = False
        if not os.path.exists(self.status_file):
            needs_init = True
        else:
            # Check if file is empty or only contains {}
            try:
                with open(self.status_file, 'r') as f:
                    existing_data = json.load(f)
                    if not existing_data or len(existing_data) == 0:
                        needs_init = True
                        logger.warning(f"[WARN] proxy_status.json is empty, reinitializing from {self.proxy_file}")
            except:
                needs_init = True
        
        if needs_init:
            # Scan proxy file để tạo initial status
            proxies = self._load_proxies_from_file()
            initial_status = {}
            
            for i, proxy in enumerate(proxies):
                proxy_id = f"proxy_{i+1}"
                resource = ManagedResource(proxy_id, "proxy")
                resource.status = "READY"
                resource.metadata = {
                    "config": proxy,
                    "last_checked": None,
                    "response_time": None
                }
                initial_status[proxy_id] = resource.to_dict()
            
            # Nếu không có proxy nào, tạo placeholder
            if not initial_status:
                placeholder_proxy = ManagedResource("proxy_placeholder", "proxy")
                placeholder_proxy.status = "DISABLED"
                placeholder_proxy.metadata = {
                        "config": {"type": "http", "host": "example.com", "port": 8080},
                        "last_checked": None,
                        "response_time": None
                    }
                initial_status = {
                    "proxy_placeholder": placeholder_proxy.to_dict()
                }
                logger.info("📝 Tạo template proxy status - cần cấu hình proxies")
            
            self._write_status_file(initial_status)
            logger.info(f"📄 Tạo proxy status file với {len(initial_status)} proxies")
    
    def _load_proxies_from_file(self) -> List[Dict[str, Any]]:
        """
        ⚠️ DEPRECATED - DATABASE-FIRST APPROACH
        
        Load danh sách proxy từ file cấu hình (LEGACY)
        
        This method is ONLY used by migration script (migrate_proxies_to_db.py).
        Normal operation uses _load_proxies_from_db() instead.
        """
        proxies = []
        
        try:
            with open(self.proxy_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                
                proxy_config = self._parse_proxy_line(line)
                if proxy_config:
                    proxies.append(proxy_config)
                else:
                    logger.warning(f"[WARN] Invalid proxy format at line {line_num}: {line}")
            
            logger.info(f"[INFO] Loaded {len(proxies)} proxies from {self.proxy_file}")
            return proxies
            
        except Exception as e:
            logger.error(f"[ERROR] Error load proxy file: {e}")
            return []
    
    def _parse_proxy_line(self, line: str) -> Optional[Dict[str, Any]]:
        """Parse một dòng proxy thành config dict"""
        try:
            # SOCKS5 format: socks5://user:pass@host:port
            if line.startswith('socks5://'):
                import urllib.parse
                parsed = urllib.parse.urlparse(line)
                return {
                    "type": "socks5",
                    "host": parsed.hostname,
                    "port": parsed.port,
                    "username": parsed.username,
                    "password": parsed.password
                }
            
            # HTTP format: host:port:user:pass or host:port
            parts = line.split(':')
            
            if len(parts) == 2:
                # No authentication
                return {
                    "type": "http",
                    "host": parts[0],
                    "port": int(parts[1]),
                    "username": None,
                    "password": None
                }
            elif len(parts) == 4:
                # With authentication
                return {
                    "type": "http",
                    "host": parts[0],
                    "port": int(parts[1]),
                    "username": parts[2],
                    "password": parts[3]
                }
            else:
                return None
                
        except Exception as e:
            logger.debug(f"Parse error for line '{line}': {e}")
            return None
    
    def _read_status_file(self) -> Dict[str, Any]:
        """
        Đọc proxy status từ file với ERROR RECOVERY strategy
        
        ✅ CRITICAL FIX: Proper error handling với backup restore
        ✅ CRITICAL FIX: Validation để detect corruption sớm
        """
        import shutil
        
        try:
            with open(self.status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # ✅ FIX #2: Validate data integrity
                if not isinstance(data, dict):
                    raise ValueError(f"Invalid status file format: expected dict, got {type(data)}")
                
                return data
                
        except FileNotFoundError:
            # ✅ OK: File doesn't exist yet (first run)
            logger.warning(f"[WARN] Proxy status file not found: {self.status_file} (will be created)")
            return {}
            
        except json.JSONDecodeError as e:
            # ❌ CRITICAL: File is corrupted!
            logger.error(f"[CRITICAL] Proxy status file corrupted: {e}")
            
            # ✅ FIX #2: Try to restore from backup
            backup_path = self.status_file + ".backup"
            if os.path.exists(backup_path):
                try:
                    logger.info(f"[RECOVERY] Attempting restore from backup: {backup_path}")
                    
                    # Validate backup before restore
                    with open(backup_path, 'r', encoding='utf-8') as f:
                        backup_data = json.load(f)
                        if not isinstance(backup_data, dict):
                            raise ValueError("Backup file also corrupted")
                    
                    # Backup is valid, restore it
                    shutil.copy2(backup_path, self.status_file)
                    logger.info("[RECOVERY] ✅ Successfully restored proxy status from backup")
                    
                    return backup_data
                    
                except Exception as backup_error:
                    logger.error(f"[RECOVERY] ❌ Backup restore failed: {backup_error}")
            else:
                logger.error("[RECOVERY] ❌ No backup file available")
            
            # ✅ FIX #2: Raise exception instead of silent failure
            raise RuntimeError(
                f"Proxy status file corrupted and recovery failed. "
                f"Manual intervention required: {self.status_file}"
            )
            
        except Exception as e:
            # Other unexpected errors
            logger.error(f"[ERROR] Unexpected error reading proxy status file: {e}")
            raise
    
    def _write_status_file(self, status_data: Dict[str, Any]):
        """
        Ghi proxy status vào file với ATOMIC WRITE + BACKUP strategy
        
        ✅ CRITICAL FIX: Atomic write prevents corruption on crash
        ✅ CRITICAL FIX: Backup enables recovery from corruption
        """
        import tempfile
        import shutil
        
        try:
            # ✅ FIX #6: Backup current file trước khi write (nếu exists)
            backup_path = self.status_file + ".backup"
            if os.path.exists(self.status_file):
                try:
                    shutil.copy2(self.status_file, backup_path)
                except Exception as e:
                    logger.warning(f"[WARN] Cannot create proxy backup: {e}")
            
            # ✅ FIX #1: ATOMIC WRITE - Write to temp file first
            temp_fd, temp_path = tempfile.mkstemp(
                dir=os.path.dirname(self.status_file) or '.',
                prefix='.tmp_proxy_',
                suffix='.json'
            )
            
            try:
                # Write to temp file
                with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(status_data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())  # Force write to disk
                
                # ✅ ATOMIC: Rename is atomic on all modern OS
                os.replace(temp_path, self.status_file)
                
                logger.debug(f"📝 Atomic write: {len(status_data)} proxies to {self.status_file}")
                
            except Exception as e:
                # Clean up temp file if write failed
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
                
        except Exception as e:
            logger.error(f"[ERROR] Error writing proxy status: {e}")
            raise
    
    @contextmanager
    def locks(self):
        """
        Context manager for unified lock handling (same as SessionManager).
        
        Usage:
            with self.locks():
                # ... do work ...
        """
        with self.lock:
            if self.file_lock:
                with self.file_lock:
                    yield
            else:
                yield
    
    def checkout_proxy(self, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """
        Intelligent proxy checkout với performance-based selection
        
        [WARN] DEPRECATED: Use SessionManager.checkout_session_with_proxy() for production
        This method is maintained for backward compatibility and unit testing
        
        Args:
            timeout: Thời gian chờ tối đa (giây) để lấy proxy
            
        Returns:
            Dict chứa proxy config nếu thành công, None nếu không có proxy sẵn sàng
        """
        import warnings
        warnings.warn(
            "checkout_proxy() is deprecated. Use SessionManager.checkout_session_with_proxy() for production "
            "to ensure consistent session-proxy binding.",
            DeprecationWarning,
            stacklevel=2
        )
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Process cooldowns and health checks
            self._process_cooldowns()
            self._maybe_run_health_checks()
            
            # Intelligent proxy selection
            with self.lock:
                if self.file_lock:
                    with self.file_lock:
                        result = self._intelligent_checkout()
                        if result:
                            self._sync_resources_to_db()
                            return result
                else:
                    result = self._intelligent_checkout()
                    if result:
                        self._sync_resources_to_db()
                        return result
            
            time.sleep(1)
        
        logger.warning(f"⏰ Timeout checkout proxy sau {timeout}s")
        return None
    
    def _intelligent_checkout(self) -> Optional[Dict[str, Any]]:
        """
        Intelligent proxy selection dựa trên performance và health metrics
        """
        try:
            # Get available proxies (not in use, not quarantined)
            available_proxies = []
            
            for resource_id, resource in self.resource_pool.items():
                # Skip if in use or quarantined
                if resource.status == "IN_USE" or resource.is_quarantined():
                    continue
                
                # Skip if disabled or testing
                if resource.status in ["DISABLED", "TESTING"]:
                    continue
                
                # Validate proxy config
                proxy_config = resource.metadata.get("config")
                if not proxy_config or not self._validate_proxy_config(proxy_config):
                    logger.warning(f"[WARN] Proxy config invalid: {resource_id}")
                    resource.status = "DISABLED"
                    continue
                    
                available_proxies.append(resource)
            
            if not available_proxies:
                self._log_proxy_stats()
                return None
            
            # Intelligent selection: prioritize by response time, success rate
            selected = self._select_best_proxy(available_proxies)
            
            # Mark as IN_USE and update timestamps
            selected.status = "IN_USE"
            selected.last_used_timestamp = datetime.now()
            
            # Prepare return config
            proxy_config = selected.metadata["config"].copy()
            proxy_config["proxy_id"] = selected.id
            
            logger.info(f"[TARGET] Intelligently selected proxy: {selected.id} (success_rate: {selected.success_rate:.2f})")
            return proxy_config
        
        except Exception as e:
            logger.error(f"[ERROR] Error intelligent proxy checkout: {e}")
            return None
    
    def _select_best_proxy(self, available_proxies: List[ManagedResource]) -> ManagedResource:
        """
        Select best proxy based on performance metrics and response time
        """
        # Sort by multiple criteria: success rate, response time, least recently used
        sorted_proxies = sorted(
            available_proxies,
            key=lambda r: (
                -r.success_rate,  # Higher success rate first
                r.consecutive_failures,  # Fewer failures first
                r.metadata.get("response_time") or 999.0,  # Faster response time first (handle None)
                r.last_used_timestamp or datetime.min  # Least recently used first
            )
        )
        
        return sorted_proxies[0]
    
    def checkin_proxy(self, proxy_config: Dict[str, Any], status: str = "READY"):
        """
        Intelligent proxy checkin với performance tracking
        
        Args:
            proxy_config: Config dict từ checkout_proxy (chứa proxy_id)
            status: Trạng thái mới của proxy (default: "READY")
        """
        proxy_id = proxy_config.get("proxy_id")
        if not proxy_id:
            logger.warning("[WARN] Proxy config missing proxy_id, cannot checkin")
            return
        
        with self.locks():
            self._intelligent_checkin(proxy_id, status)
            self._sync_resources_to_db()
    
    def _intelligent_checkin(self, proxy_id: str, status: str):
        """
        Intelligent checkin với performance tracking.
        
        [OK] FIX CRITICAL: Reload file first to prevent overwriting changes from other workers!
        """
        try:
            # [OK] FIX: Reload from file to get latest state from other workers
            # CRITICAL for multi-process (Celery workers) to prevent lost updates
            self._load_proxies_from_db()
            
            if proxy_id not in self.resource_pool:
                logger.warning(f"[WARN] Proxy không exists: {proxy_id}")
                return
            
            resource = self.resource_pool[proxy_id]
            old_status = resource.status
            resource.status = status
            
            logger.info(f"[UNLOCK] Checked in proxy: {proxy_id} ({old_status} → {status})")
            
        except Exception as e:
            logger.error(f"[ERROR] Error intelligent checkin proxy {proxy_id}: {e}")
    
    def _validate_proxy_config(self, config: Dict[str, Any]) -> bool:
        """Enhanced proxy configuration validation."""
        if not isinstance(config, dict):
            return False
        
        required_fields = ["type", "host", "port"]
        if not all(field in config for field in required_fields):
            return False
        
        # Validate proxy type
        if config["type"] not in ["http", "https", "socks5"]:
            return False
        
        # Validate port range
        try:
            port = int(config["port"])
            if not (1 <= port <= 65535):
                return False
        except (ValueError, TypeError):
            return False
        
        # Validate host is not empty
        if not config["host"] or not isinstance(config["host"], str):
            return False
        
        return True
    
    def get_proxy_for_playwright(self, proxy_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert proxy config sang format Playwright với validation

        Args:
            proxy_config: Config dict từ checkout_proxy

        Returns:
            Dict format Playwright hoặc None nếu không hợp lệ hoặc không kết nối được
        """
        try:
            if not proxy_config:
                return None

            # Validate proxy connectivity trước khi convert
            if not self.health_check_proxy(proxy_config):
                proxy_id = proxy_config.get('proxy_id', 'unknown')
                logger.warning(f"[WARN] Proxy {proxy_id} failed connectivity test, skipping")
                return None

            playwright_proxy = {
                "server": f"http://{proxy_config['host']}:{proxy_config['port']}"
            }

            # Add authentication if available
            if proxy_config.get("username") and proxy_config.get("password"):
                playwright_proxy["username"] = proxy_config["username"]
                playwright_proxy["password"] = proxy_config["password"]

            # Handle SOCKS5
            if proxy_config.get("type") == "socks5":
                playwright_proxy["server"] = f"socks5://{proxy_config['host']}:{proxy_config['port']}"

            proxy_id = proxy_config.get('proxy_id', 'unknown')
            logger.info(f"[OK] Validated and converted proxy for Playwright: {proxy_id}")
            return playwright_proxy

        except Exception as e:
            logger.error(f"[ERROR] Error convert proxy cho Playwright: {e}")
            return None
    
    def detect_proxy_geolocation(self, proxy_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        [GEO] PHASE 3: Detect proxy geolocation via IP API (for timezone/location spoofing)
        
        Uses free IP geolocation APIs to detect proxy location.
        Falls back to multiple APIs if one fails (rate limiting).
        
        Args:
            proxy_config: Config dict của proxy
            
        Returns:
            Dict with timezone, latitude, longitude, country, city or None if failed
        """
        try:
            # Build proxy URL for requests
            if proxy_config.get("type") == "socks5":
                proxy_url = f"socks5://{proxy_config['host']}:{proxy_config['port']}"
            else:
                proxy_url = f"http://{proxy_config['host']}:{proxy_config['port']}"
            
            if proxy_config.get("username") and proxy_config.get("password"):
                if proxy_config.get("type") == "socks5":
                    proxy_url = f"socks5://{proxy_config['username']}:{proxy_config['password']}@{proxy_config['host']}:{proxy_config['port']}"
                else:
                    proxy_url = f"http://{proxy_config['username']}:{proxy_config['password']}@{proxy_config['host']}:{proxy_config['port']}"
            
            proxies = {
                'http': proxy_url,
                'https': proxy_url
            }
            
            # Try multiple free geolocation APIs (with fallback)
            apis = [
                ('https://ipapi.co/json/', lambda r: {
                    'timezone': r.get('timezone', 'UTC'),
                    'latitude': r.get('latitude', 0),
                    'longitude': r.get('longitude', 0),
                    'country': r.get('country_name', 'Unknown'),
                    'city': r.get('city', 'Unknown')
                }),
                ('http://ip-api.com/json/', lambda r: {
                    'timezone': r.get('timezone', 'UTC'),
                    'latitude': r.get('lat', 0),
                    'longitude': r.get('lon', 0),
                    'country': r.get('country', 'Unknown'),
                    'city': r.get('city', 'Unknown')
                }),
            ]
            
            for api_url, parser in apis:
                try:
                    response = requests.get(
                        api_url,
                        proxies=proxies,
                        timeout=10,
                        verify=False  # Some proxies have SSL issues
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        geo_data = parser(data)
                        
                        # [OK] FIX ISSUE #3: Validate geolocation data
                        lat = geo_data.get('latitude')
                        lon = geo_data.get('longitude')
                        
                        # Reject invalid coordinates (0,0 or None)
                        if lat and lon and (abs(lat) > 0.01 or abs(lon) > 0.01):
                            logger.info(f"[GEO] Proxy {proxy_config.get('proxy_id')}: {geo_data['city']}, {geo_data['country']} (TZ: {geo_data['timezone']})")
                            return geo_data
                        else:
                            logger.warning(f"[WARN] Invalid coordinates from {api_url}: ({lat}, {lon}), trying next API...")
                            continue
                        
                except Exception as e:
                    logger.debug(f"Geolocation API {api_url} failed: {e}, trying next...")
                    continue
            
            logger.warning(f"[WARN] All geolocation APIs failed for proxy {proxy_config.get('proxy_id')}")
            return None
            
        except Exception as e:
            logger.error(f"[ERROR] Error detecting proxy geolocation: {e}")
            return None

    def health_check_proxy(self, proxy_config: Dict[str, Any], use_cache: bool = True) -> bool:
        """
        Enhanced health check với response time tracking (synchronous version)

        [WARN] WARNING: This is a BLOCKING sync operation using requests.Session().get()

        DO NOT call this from async context (will block event loop)!
        For async operations, use health_check_proxy_async() instead.

        Args:
            proxy_config: Config dict của proxy
            use_cache: If True, return cached result if recently verified (within 5 min)

        Returns:
            True nếu proxy hoạt động tốt, False nếu có vấn đề
        """
        proxy_id = proxy_config.get("proxy_id")

        # FIX C1: Early cache check to avoid blocking health checks
        if use_cache and proxy_id and proxy_id in self.resource_pool:
            resource = self.resource_pool[proxy_id]
            last_checked = resource.metadata.get("last_checked")
            if last_checked:
                try:
                    last_check_time = datetime.fromisoformat(last_checked)
                    cache_age = (datetime.now() - last_check_time).total_seconds()

                    # Return cached result if verified within last 5 minutes
                    if cache_age < 300:  # 5 minutes
                        # Assume healthy if status is READY/IN_USE and no recent failures
                        if resource.status in ["READY", "IN_USE"] and resource.consecutive_failures == 0:
                            logger.debug(f"[CACHE] Proxy {proxy_id} recently verified ({cache_age:.0f}s ago)")
                            return True
                        elif resource.consecutive_failures >= 2:
                            logger.debug(f"[CACHE] Proxy {proxy_id} recently failed ({cache_age:.0f}s ago)")
                            return False
                except Exception as e:
                    logger.debug(f"Cache parse error for {proxy_id}: {e}")

        try:
            # Create requests session with proxy
            session = requests.Session()
            
            proxies = {}
            if proxy_config.get("type") == "socks5":
                proxy_url = f"socks5://{proxy_config['host']}:{proxy_config['port']}"
            else:
                proxy_url = f"http://{proxy_config['host']}:{proxy_config['port']}"
            
            # Add authentication if available
            if proxy_config.get("username") and proxy_config.get("password"):
                if proxy_config.get("type") == "socks5":
                    proxy_url = f"socks5://{proxy_config['username']}:{proxy_config['password']}@{proxy_config['host']}:{proxy_config['port']}"
                else:
                    proxy_url = f"http://{proxy_config['username']}:{proxy_config['password']}@{proxy_config['host']}:{proxy_config['port']}"
            
            proxies = {"http": proxy_url, "https": proxy_url}
            session.proxies.update(proxies)
            
            # Test với multiple endpoints (fallback strategy)
            test_endpoints = [
                "http://ipinfo.io/json",  # More reliable for proxy testing
                "http://httpbin.org/ip",  # Fallback
                "http://www.facebook.com"  # Final fallback - just check connectivity
            ]
            
            for endpoint in test_endpoints:
                try:
                    start_time = time.time()
                    response = session.get(endpoint, timeout=5, allow_redirects=False)
                    response_time = time.time() - start_time
                    
                    # Update response time in metadata
                    if proxy_id and proxy_id in self.resource_pool:
                        self.resource_pool[proxy_id].metadata["response_time"] = response_time
                        self.resource_pool[proxy_id].metadata["last_checked"] = datetime.now().isoformat()
                    
                    # Accept 200, 301, 302 as success
                    if response.status_code in [200, 301, 302]:
                        logger.debug(f"[OK] Proxy health check OK: {proxy_id} ({response_time:.2f}s via {endpoint})")
                        # [HOT] FIX #3: Reset consecutive failures on success
                        if proxy_id and proxy_id in self.resource_pool:
                            resource = self.resource_pool[proxy_id]
                            resource.consecutive_failures = 0
                            
                            # [GEO] PHASE 3: Detect geolocation if not already cached (once per proxy)
                            if "geolocation" not in resource.metadata or not resource.metadata.get("geolocation"):
                                logger.info(f"[GEO] Detecting geolocation for proxy {proxy_id}...")
                                geo_data = self.detect_proxy_geolocation(proxy_config)
                                if geo_data:
                                    resource.metadata["geolocation"] = geo_data
                                    logger.info(f"[OK] Cached geolocation: {geo_data['city']}, {geo_data['country']}")
                            
                            # ✅ FIX RACE: Removed _sync_resources_to_db() - caller must handle sync
                        return True
                except Exception as e:
                    logger.debug(f"Endpoint {endpoint} failed for {proxy_id}: {str(e)[:50]}")
                    continue
            
            # [HOT] FIX #3: AGGRESSIVE QUARANTINE - All endpoints failed
            logger.warning(f"[WARN] Proxy health check failed: {proxy_id} - All test endpoints failed")
            
            # Increment consecutive failures and quarantine if threshold reached
            if proxy_id and proxy_id in self.resource_pool:
                resource = self.resource_pool[proxy_id]
                resource.consecutive_failures += 1
                logger.warning(f"[ALERT] Proxy {proxy_id} consecutive failures: {resource.consecutive_failures}")
                
                # ✅ FIX RACE: Removed _sync_resources_to_db() - caller must handle sync
                
                # Quarantine immediately after 2 consecutive health check failures
                if resource.consecutive_failures >= 2:
                    self.quarantine_resource(
                        proxy_id, 
                        f"Health check failed {resource.consecutive_failures} times consecutively"
                    )
                    logger.critical(f"[STOP] Proxy {proxy_id} QUARANTINED after repeated health check failures")
            
            return False
                
        except Exception as e:
            logger.warning(f"[WARN] Proxy health check error: {proxy_id} - {e}")
            # Also count as failure
            if proxy_id and proxy_id in self.resource_pool:
                self.resource_pool[proxy_id].consecutive_failures += 1
            return False
    
    async def health_check_proxy_async(self, proxy_config: Dict[str, Any]) -> bool:
        """
        ASYNC version of health check - non-blocking for Celery workers
        
        FIX: Removed fallback to sync version to prevent blocking event loop.
        
        Args:
            proxy_config: Config dict của proxy
            
        Returns:
            True nếu proxy hoạt động tốt, False nếu có vấn đề
        """
        proxy_id = proxy_config.get("proxy_id")
        
        try:
            import aiohttp
            
            # Build proxy URL
            if proxy_config.get("type") == "socks5":
                proxy_url = f"socks5://{proxy_config['host']}:{proxy_config['port']}"
            else:
                proxy_url = f"http://{proxy_config['host']}:{proxy_config['port']}"
            
            # Add authentication if available
            if proxy_config.get("username") and proxy_config.get("password"):
                if proxy_config.get("type") == "socks5":
                    proxy_url = f"socks5://{proxy_config['username']}:{proxy_config['password']}@{proxy_config['host']}:{proxy_config['port']}"
                else:
                    proxy_url = f"http://{proxy_config['username']}:{proxy_config['password']}@{proxy_config['host']}:{proxy_config['port']}"
            
            # Test with multiple endpoints (fallback strategy)
            test_endpoints = [
                "http://ipinfo.io/json",
                "http://httpbin.org/ip",
                "http://www.facebook.com"
            ]
            
            start_time = time.time()
            timeout = aiohttp.ClientTimeout(total=5)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Try each endpoint
                for endpoint in test_endpoints:
                    try:
                        async with session.get(endpoint, proxy=proxy_url, allow_redirects=False) as response:
                            response_time = time.time() - start_time
                            
                            # Update response time in metadata
                            if proxy_id and proxy_id in self.resource_pool:
                                self.resource_pool[proxy_id].metadata["response_time"] = response_time
                                self.resource_pool[proxy_id].metadata["last_checked"] = datetime.now().isoformat()
                            
                            # Accept 200, 301, 302 as success
                            if response.status in [200, 301, 302]:
                                logger.debug(f"[OK] Async proxy health check OK: {proxy_id} ({response_time:.2f}s via {endpoint})")
                                return True
                    except Exception as e:
                        logger.debug(f"Endpoint {endpoint} failed for {proxy_id}: {str(e)[:50]}")
                        continue
                
                # All endpoints failed
                logger.warning(f"[WARN] Async proxy health check failed: {proxy_id} - All test endpoints failed")
                return False
                        
        except Exception as e:
            logger.warning(f"[WARN] Async proxy health check error: {proxy_id} - {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Lấy thống kê chi tiết về proxies và performance.
        
        Uses thread-only lock for performance (acceptable stale data for stats).
        """
        with self.lock:
            stats = {
                'total': len(self.resource_pool),
                'ready': 0,
                'in_use': 0,
                'quarantined': 0,
                'failed': 0,
                'disabled': 0,
                'testing': 0,
                'performance': {
                    'avg_success_rate': 0.0,
                    'avg_response_time': 0.0,
                    'total_tasks': 0,
                    'successful_tasks': 0,
                    'high_performers': 0,  # success_rate > 0.9
                    'low_performers': 0,   # success_rate < 0.6
                }
            }
            
            total_success_rate = 0.0
            total_response_time = 0.0
            resources_with_tasks = 0
            resources_with_response_time = 0
            
            for resource in self.resource_pool.values():
                # Count by status
                if resource.status == "READY":
                    stats['ready'] += 1
                elif resource.status == "IN_USE":
                    stats['in_use'] += 1
                elif resource.is_quarantined():
                    stats['quarantined'] += 1
                elif resource.status == "FAILED":
                    stats['failed'] += 1
                elif resource.status == "DISABLED":
                    stats['disabled'] += 1
                elif resource.status == "TESTING":
                    stats['testing'] += 1
                
                # Performance metrics
                stats['performance']['total_tasks'] += resource.total_tasks
                stats['performance']['successful_tasks'] += resource.successful_tasks
                
                if resource.total_tasks > 0:
                    total_success_rate += resource.success_rate
                    resources_with_tasks += 1
                    
                    if resource.success_rate > 0.9:
                        stats['performance']['high_performers'] += 1
                    elif resource.success_rate < 0.6:
                        stats['performance']['low_performers'] += 1
                
                # Response time tracking
                response_time = resource.metadata.get("response_time")
                if response_time is not None:
                    total_response_time += response_time
                    resources_with_response_time += 1
            
            # Calculate averages
            if resources_with_tasks > 0:
                stats['performance']['avg_success_rate'] = total_success_rate / resources_with_tasks
            
            if resources_with_response_time > 0:
                stats['performance']['avg_response_time'] = total_response_time / resources_with_response_time
            
        return stats
    
    def mark_proxy_failed(self, proxy_config: Dict[str, Any], reason: str = ""):
        """Đánh dấu proxy bị error và update performance metrics."""
        proxy_id = proxy_config.get("proxy_id")
        if proxy_id:
            logger.warning(f"[ERROR] Marking proxy failed: {proxy_id} - {reason}")
            # Report failure for performance tracking
            self.report_outcome(proxy_id, 'failure', {'reason': reason})
            # Check in with FAILED status if not quarantined
            if proxy_id in self.resource_pool and not self.resource_pool[proxy_id].is_quarantined():
                self.checkin_proxy(proxy_config, "FAILED")
    
    def reset_all_proxies(self):
        """Reset tất cả proxies về trạng thái READY (debug only)"""
        with self.locks():
            for resource in self.resource_pool.values():
                resource.status = "READY"
                resource.consecutive_failures = 0
                resource.quarantine_until_timestamp = None
                resource.quarantine_reason = None
            
            self._sync_resources_to_db()
            logger.info("[RELOAD] Reset tất cả proxies về READY")
    
    def report_outcome(self, proxy_id: str, outcome: str, details: Optional[Dict[str, Any]] = None) -> None:
        """
        Báo cáo kết quả task để cập nhật performance metrics cho proxy
        
        [OK] FIX CRITICAL: Reload file first to prevent overwriting changes from other workers!
        
        Args:
            proxy_id: ID của proxy
            outcome: 'success' hoặc 'failure'
            details: Thông tin chi tiết về task (có thể chứa response_time)
            
        Returns:
            None
        """
        with self.locks():
            # [OK] FIX: Reload from file to get latest state from other workers
            self._load_proxies_from_db()
            
            if proxy_id not in self.resource_pool:
                logger.warning(f"[WARN] Proxy không exists để report outcome: {proxy_id}")
                return
            
            resource = self.resource_pool[proxy_id]
            resource.total_tasks += 1
            
            if outcome == 'success':
                resource.successful_tasks += 1
                resource.consecutive_failures = 0
                
                # Update response time if provided
                if details and 'response_time' in details:
                    resource.metadata["response_time"] = details['response_time']
                
                logger.debug(f"[OK] Success reported for proxy {proxy_id}")
            elif outcome == 'failure':
                resource.consecutive_failures += 1
                logger.debug(f"[ERROR] Failure reported for proxy {proxy_id} (consecutive: {resource.consecutive_failures})")
            
            # Recalculate success rate
            resource.calculate_success_rate()
            
            # Check if should be quarantined
            if resource.should_be_quarantined(
                self.consecutive_failure_threshold,
                self.success_rate_threshold,
                self.min_tasks_for_rate_calc
            ):
                self.quarantine_resource(proxy_id, f"Performance threshold exceeded: {resource.consecutive_failures} consecutive failures, {resource.success_rate:.2f} success rate")
            
            # Sync to file
            self._sync_resources_to_db()
    
    def quarantine_resource(self, proxy_id: str, reason: str = "Performance issues"):
        """
        Cách ly proxy vào quarantine với cooldown period
        
        Args:
            proxy_id: ID của proxy
            reason: Lý do cách ly
        """
        with self.locks():
            if proxy_id not in self.resource_pool:
                logger.warning(f"[WARN] Proxy không exists để quarantine: {proxy_id}")
                return
            
            resource = self.resource_pool[proxy_id]
            resource.status = "QUARANTINED"
            resource.quarantine_reason = reason
            resource.quarantine_count += 1
            resource.quarantine_until_timestamp = datetime.now() + timedelta(minutes=self.quarantine_duration_minutes)
            
            logger.warning(f"[ALERT] Proxy {proxy_id} quarantined until {resource.quarantine_until_timestamp.strftime('%H:%M:%S')} - {reason}")
            
            # Sync to file
            self._sync_resources_to_db()
    
    def get_proxy_performance(self, proxy_id: str) -> Optional[Dict[str, Any]]:
        """
        Lấy performance metrics của một proxy cụ thể
        
        Uses thread-only lock for performance (read-only operation).
        
        Args:
            proxy_id: ID của proxy
            
        Returns:
            Dict chứa performance metrics hoặc None nếu không tìm thấy
        """
        with self.lock:
            if proxy_id not in self.resource_pool:
                return None
            
            resource = self.resource_pool[proxy_id]
            return {
                "success_rate": resource.success_rate,
                "total_tasks": resource.total_tasks,
                "successful_tasks": resource.successful_tasks,
                "consecutive_failures": resource.consecutive_failures,
                "quarantine_count": resource.quarantine_count,
                "last_used": resource.last_used_timestamp.isoformat() if resource.last_used_timestamp else None,
                "quarantine_reason": resource.quarantine_reason,
                "is_quarantined": resource.is_quarantined(),
                "response_time": resource.metadata.get("response_time"),
                "last_checked": resource.metadata.get("last_checked")
            }
    
    def get_best_performers(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Lấy danh sách proxies với performance tốt nhất
        
        Uses thread-only lock for performance (read-only operation).
        
        Args:
            limit: Số lượng proxies trả về
            
        Returns:
            List các proxy với performance metrics
        """
        with self.lock:
            # Filter resources with enough tasks
            qualified_resources = [
                resource for resource in self.resource_pool.values()
                if resource.total_tasks >= self.min_tasks_for_rate_calc
            ]
            
            # Sort by success rate and response time
            sorted_resources = sorted(
                qualified_resources,
                key=lambda r: (-r.success_rate, r.metadata.get("response_time", 999.0))
            )
            
            result = []
            for resource in sorted_resources[:limit]:
                result.append({
                    "proxy_id": resource.id,
                    "success_rate": resource.success_rate,
                    "total_tasks": resource.total_tasks,
                    "consecutive_failures": resource.consecutive_failures,
                    "status": resource.status,
                    "response_time": resource.metadata.get("response_time")
                })
            
            return result
    
    def check_cooldowns(self) -> int:
        """
        Public method để kiểm tra và xử lý cooldowns (có thể gọi từ scheduler).
        
        Returns:
            Number of proxies released from quarantine
        """
        with self.locks():
            released_count = self._process_cooldowns()
            self._sync_resources_to_db()
            return released_count


    def get_healthy_proxy_ids(self, force_check: bool = False) -> List[str]:
        """
        [OK] FIX #3: Get list of healthy proxy IDs with optional health check
        
        This method pre-validates proxies before checkout to avoid wasting resources
        on failed proxies.
        
        Uses thread-only lock initially, then cross-process lock for metadata updates.
        
        Args:
            force_check: If True, run health check even if recently verified
            
        Returns:
            List of proxy IDs that are healthy and available
        """
        healthy_proxy_ids = []
        
        with self.lock:  # Thread-only lock for reading
            for proxy_id, proxy_resource in self.resource_pool.items():
                # Skip quarantined or disabled
                if proxy_resource.is_quarantined() or proxy_resource.status in ["DISABLED", "TESTING"]:
                    logger.debug(f"[WARN] Proxy {proxy_id} skipped - quarantined or disabled")
                    continue
                
                # Validate config exists
                proxy_config = proxy_resource.metadata.get("config")
                if not proxy_config or not self._validate_proxy_config(proxy_config):
                    logger.debug(f"[WARN] Proxy {proxy_id} skipped - invalid config")
                    continue
                
                # Check if recently verified (within 5 minutes) unless force_check
                if not force_check:
                    last_checked = proxy_resource.metadata.get("last_checked")
                    if last_checked:
                        try:
                            last_check_time = datetime.fromisoformat(last_checked)
                            if datetime.now() - last_check_time < timedelta(minutes=5):
                                healthy_proxy_ids.append(proxy_id)
                                logger.debug(f"[OK] Proxy {proxy_id} recently verified (cached)")
                                continue
                        except Exception as e:
                            logger.debug(f"Failed to parse last_checked for {proxy_id}: {e}")
                
                # Run health check
                proxy_config_copy = proxy_config.copy()
                proxy_config_copy["proxy_id"] = proxy_id
                
                if self.health_check_proxy(proxy_config_copy):
                    # Update last_checked timestamp to cache result
                    proxy_resource.metadata["last_checked"] = datetime.now().isoformat()
                    healthy_proxy_ids.append(proxy_id)
                    logger.debug(f"[OK] Proxy {proxy_id} verified healthy")
                else:
                    logger.warning(f"[WARN] Proxy {proxy_id} failed health check")
        
        # ✅ FIX RACE: Sync metadata updates (last_checked timestamps)
        if any(self.resource_pool[pid].metadata.get("last_checked") for pid in healthy_proxy_ids if pid in self.resource_pool):
            with self.locks():
                self._sync_resources_to_db()
        
        logger.info(f"[STATS] Found {len(healthy_proxy_ids)} healthy proxies out of {len(self.resource_pool)} total")
        return healthy_proxy_ids
    
    def reload_proxies_from_file(self):
        """
        ⚠️ DEPRECATED - DATABASE-FIRST APPROACH
        
        [RELOAD] Reload proxies from file và update resource pool (LEGACY)
        
        This method is DEPRECATED. Use Admin Panel UI to add/remove proxies instead.
        ProxyManager now loads from DATABASE via _load_proxies_from_db().
        """
        logger.info("[RELOAD] Reloading proxies from file...")
        
        with self.locks():
            # Load proxies from file
            new_proxies = self._load_proxies_from_file()
            
            if not new_proxies:
                logger.warning("[WARN] No proxies found in file")
                return {'added': 0, 'removed': 0, 'total': len(self.resource_pool)}
            
            # Track changes
            added_count = 0
            removed_count = 0
            
            # Create set of new proxy configs (unique identifier)
            new_proxy_configs = {
                f"{p['host']}:{p['port']}" for p in new_proxies
            }
            
            # Remove proxies no longer in file
            proxy_ids_to_remove = []
            for proxy_id, resource in self.resource_pool.items():
                config = resource.metadata.get("config", {})
                config_id = f"{config.get('host')}:{config.get('port')}"
                
                if config_id not in new_proxy_configs:
                    proxy_ids_to_remove.append(proxy_id)
            
            for proxy_id in proxy_ids_to_remove:
                del self.resource_pool[proxy_id]
                removed_count += 1
                logger.info(f"🗑️ Removed proxy: {proxy_id}")
            
            # Add new proxies
            existing_configs = {
                f"{r.metadata.get('config', {}).get('host')}:{r.metadata.get('config', {}).get('port')}"
                for r in self.resource_pool.values()
            }
            
            for i, proxy in enumerate(new_proxies):
                config_id = f"{proxy['host']}:{proxy['port']}"
                
                if config_id not in existing_configs:
                    # Generate new proxy_id
                    proxy_id = f"proxy_{len(self.resource_pool) + 1}"
                    
                    # Create new resource
                    resource = ManagedResource(proxy_id, "proxy")
                    resource.status = "READY"
                    resource.metadata = {
                        "config": proxy,
                        "last_checked": None,
                        "response_time": None
                    }
                    
                    self.resource_pool[proxy_id] = resource
                    added_count += 1
                    logger.info(f"➕ Added new proxy: {proxy_id} ({config_id})")
            
            # Sync to file
            self._sync_resources_to_db()
            
            logger.info(f"[OK] Proxy reload completed: +{added_count} -{removed_count} = {len(self.resource_pool)} total")
            
            return {
                'added': added_count,
                'removed': removed_count,
                'total': len(self.resource_pool)
            }
    
    def run_comprehensive_health_check(self):
        """
        Chạy health check toàn diện cho tất cả proxies (sử dụng cho maintenance)
        
        DATABASE-FIRST: Reload proxies từ DATABASE (không dùng file nữa)
        """
        logger.info("🛠️ Bắt đầu comprehensive health check cho tất cả proxies")
        
        # Reload proxies from DATABASE (not file)
        self._load_proxies_from_db()
        logger.info(f"📥 Reloaded {len(self.resource_pool)} proxies from database")
        
        with self.locks():
            checked_count = 0
            healthy_count = 0
            
            for resource in self.resource_pool.values():
                if resource.status in ["READY", "FAILED", "QUARANTINED"]:
                    proxy_config = resource.metadata.get("config")
                    if proxy_config:
                        logger.debug(f"🔍 Health checking proxy {resource.id}")
                        resource.status = "TESTING"
                        
                        is_healthy = self.health_check_proxy({**proxy_config, "proxy_id": resource.id})
                        
                        if is_healthy:
                            resource.status = "READY"
                            resource.consecutive_failures = 0
                            healthy_count += 1
                        else:
                            resource.status = "FAILED"
                            resource.consecutive_failures += 1
                        
                        checked_count += 1
            
            # Sync results to file
            self._sync_resources_to_db()
            
            logger.info(f"[OK] Comprehensive health check completed: {healthy_count}/{checked_count} proxies healthy")
            
            return {
                "checked_count": checked_count,
                "healthy_count": healthy_count,
                "unhealthy_count": checked_count - healthy_count,
                "total_proxies": len(self.resource_pool)
            }


# Test function
def test_proxy_manager():
    """Test cơ bản cho ProxyManager"""
    logger.info("🧪 Testing ProxyManager...")
    
    # Test với temporary files
    test_proxy_file = "test_proxies.txt"
    test_status_file = "test_proxy_status.json"
    
    try:
        # Create test proxy file
        with open(test_proxy_file, 'w') as f:
            f.write("192.168.1.100:8080:user:pass\n")
            f.write("203.0.113.1:3128\n")
            f.write("socks5://user:pass@192.168.1.200:1080\n")
        
        # Test ProxyManager
        manager = ProxyManager(test_proxy_file, test_status_file)
        
        # Test checkout
        proxy = manager.checkout_proxy(timeout=5)
        print(f"[OK] Checkout proxy: {proxy}")
        
        # Test stats
        stats = manager.get_stats()
        print(f"[OK] Stats: {stats}")
        
        # Test checkin
        if proxy:
            manager.checkin_proxy(proxy)
            print(f"[OK] Checkin proxy: {proxy.get('proxy_id')}")
        
        print("[OK] ProxyManager test completed!")
        
    finally:
        # Cleanup
        try:
            if os.path.exists(test_proxy_file):
                os.remove(test_proxy_file)
            if os.path.exists(test_status_file):
                os.remove(test_status_file)
        except (OSError, FileNotFoundError):
            pass


if __name__ == "__main__":
    # Setup logging cho test
    from logging_config import setup_application_logging
    setup_application_logging()
    
    test_proxy_manager()
