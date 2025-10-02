#!/usr/bin/env python3
"""
Session Manager for Facebook Post Monitor - Enterprise Edition Phase 3.0
Quản lý pool sessions đã đăng nhập để workers sử dụng chung

Mục đích:
- Quản lý pool các profile Facebook đã đăng nhập
- Thread-safe checkout/checkin sessions
- Tránh multiple workers sử dụng cùng session
- Giải quyết vấn đề checkpoint bằng session reuse
"""

import json
import os
import threading
import time
import logging
import asyncio
from contextlib import contextmanager
from logging_config import get_logger
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from enum import Enum

# Cross-process file locking
try:
    from filelock import FileLock
    FILELOCK_AVAILABLE = True
except ImportError:
    FILELOCK_AVAILABLE = False
    FileLock = None

logger = get_logger(__name__)


class AccountRole(Enum):
    """
    Định nghĩa vai trò của account trong hệ thống scraping
    
    DISCOVERY: Account chỉ dùng để lướt trang nhóm, reload, lấy danh sách posts mới
    TRACKING: Account chỉ dùng để vào từng post cụ thể, cập nhật reaction count
    MIXED: Account có thể làm cả hai (fallback khi không đủ chuyên biệt)
    """
    DISCOVERY = "discovery_only"   # 5 accounts lướt nhóm  
    TRACKING = "tracking_only"     # 5 accounts cập nhật detail
    MIXED = "mixed"                # Fallback cho flexibility


class ManagedResource:
    """
    Lớp đại diện cho một resource được quản lý (session hoặc proxy)
    với metadata đầy đủ và tracking hiệu suất
    """
    
    def __init__(self, resource_id: str, resource_type: str = "session", role: AccountRole = AccountRole.MIXED):
        self.id = resource_id
        self.type = resource_type
        self.role = role  # Account role: DISCOVERY, TRACKING, or MIXED
        self.status = "READY"  # READY, IN_USE, QUARANTINED, COOLDOWN, DISABLED
        
        # Performance tracking
        self.consecutive_failures = 0
        self.total_tasks = 0
        self.successful_tasks = 0
        self.success_rate = 1.0
        
        # Timestamps
        self.created_at = datetime.now()
        self.last_used_timestamp = None
        self.quarantine_until_timestamp = None
        
        # Quarantine reasons tracking
        self.quarantine_reason = None
        self.quarantine_count = 0
        
        # Additional metadata
        self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "type": self.type,
            "role": self.role.value,  # Serialize enum value
            "status": self.status,
            "consecutive_failures": self.consecutive_failures,
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "success_rate": self.success_rate,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used_timestamp": self.last_used_timestamp.isoformat() if self.last_used_timestamp else None,
            "quarantine_until_timestamp": self.quarantine_until_timestamp.isoformat() if self.quarantine_until_timestamp else None,
            "quarantine_reason": self.quarantine_reason,
            "quarantine_count": self.quarantine_count,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ManagedResource':
        """Create instance from dictionary."""
        # Parse role from data, default to MIXED for backward compatibility
        role_str = data.get("role", "mixed")
        try:
            role = AccountRole(role_str)
        except ValueError:
            role = AccountRole.MIXED
            
        resource = cls(data["id"], data.get("type", "session"), role)
        resource.status = data.get("status", "READY")
        resource.consecutive_failures = data.get("consecutive_failures", 0)
        resource.total_tasks = data.get("total_tasks", 0)
        resource.successful_tasks = data.get("successful_tasks", 0)
        resource.success_rate = data.get("success_rate", 1.0)
        
        # Parse timestamps
        if data.get("created_at"):
            resource.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("last_used_timestamp"):
            resource.last_used_timestamp = datetime.fromisoformat(data["last_used_timestamp"])
        if data.get("quarantine_until_timestamp"):
            resource.quarantine_until_timestamp = datetime.fromisoformat(data["quarantine_until_timestamp"])
        
        resource.quarantine_reason = data.get("quarantine_reason")
        resource.quarantine_count = data.get("quarantine_count", 0)
        resource.metadata = data.get("metadata", {})
        
        return resource
    
    def calculate_success_rate(self):
        """
        Recalculate success rate based on current stats.
        
        ⚠️ THREAD-SAFETY NOTE: This method reads total_tasks and successful_tasks
        which may be updated by other threads. For critical accuracy, caller should
        hold appropriate locks. For metrics/monitoring, eventual consistency is acceptable.
        """
        # Read values atomically (Python GIL ensures single reads are atomic)
        total = self.total_tasks
        successful = self.successful_tasks
        
        if total == 0:
            self.success_rate = 1.0
        else:
            self.success_rate = successful / total
        return self.success_rate
    
    def is_quarantined(self) -> bool:
        """Check if resource is currently quarantined."""
        if self.status != "QUARANTINED":
            return False
        
        if self.quarantine_until_timestamp and datetime.now() >= self.quarantine_until_timestamp:
            # Quarantine period ended
            self.status = "READY"
            self.quarantine_until_timestamp = None
            return False
        
        return True
    
    def should_be_quarantined(self, failure_threshold: int = 5, success_rate_threshold: float = 0.6, min_tasks: int = 10) -> bool:
        """Check if resource should be quarantined based on performance."""
        # Check consecutive failures
        if self.consecutive_failures >= failure_threshold:
            return True
        
        # Check success rate (only after minimum tasks)
        if self.total_tasks >= min_tasks and self.success_rate < success_rate_threshold:
            return True
        
        return False


class SessionManager:
    """
    Thread-safe manager cho pool sessions Facebook với advanced metadata và quarantine logic
    
    Session States:
    - READY: Session sẵn sàng sử dụng
    - IN_USE: Session đang được worker sử dụng 
    - QUARANTINED: Session bị cách ly tạm thời do performance kém
    - COOLDOWN: Session đang trong thời gian hạ nhiệt
    - DISABLED: Session bị vô hiệu hóa vĩnh viễn
    - NEEDS_LOGIN: Session cần đăng nhập lại
    """
    
    def __init__(self, status_file: str = "session_status.json", sessions_dir: str = "sessions"):
        """
        Khởi tạo SessionManager với cross-process file locking và session-proxy binding
        
        Args:
            status_file: File JSON theo dõi trạng thái sessions
            sessions_dir: Thư mục chứa các session folders
        """
        from config import settings
        
        self.status_file = status_file
        self.sessions_dir = sessions_dir
        self.lock = threading.Lock()  # Thread-safe access
        
        # Load performance thresholds from config instead of hard-coded values
        resource_config = settings.resource_management
        self.consecutive_failure_threshold = resource_config.session_failure_threshold
        self.success_rate_threshold = resource_config.session_success_rate_threshold
        self.min_tasks_for_rate_calc = resource_config.min_tasks_for_rate_calc
        self.quarantine_duration_minutes = resource_config.session_quarantine_minutes
        
        # Resource pool (in-memory cache)
        self.resource_pool: Dict[str, ManagedResource] = {}
        
        # 🔧 PERFORMANCE OPTIMIZATION: Batch file writes to reduce I/O (from config)
        self.pending_file_sync = False
        self.last_file_sync_time = datetime.now()
        self.file_sync_interval_seconds = resource_config.file_sync_interval_seconds
        self.file_sync_change_threshold = resource_config.file_sync_change_threshold
        self.changes_since_last_sync = 0
        
        # 🔗 PRODUCTION FIX: Session-Proxy binding
        from .session_proxy_binder import SessionProxyBinder
        self.proxy_binder = SessionProxyBinder("session_proxy_bindings.json")
        
        # 🔧 PRODUCTION FIX: Cross-process file locking
        if FILELOCK_AVAILABLE:
            self.file_lock_path = self.status_file + ".lock"
            self.file_lock = FileLock(self.file_lock_path)
            logger.info("🔒 Cross-process file locking enabled")
        else:
            self.file_lock = None
            logger.warning("⚠️ FileLock not available - only thread-safe within process")
        
        # Ensure directories exist
        self._ensure_structure()
        
        logger.info(f"🔐 SessionManager khởi tạo: {status_file}")
        logger.info(f"📁 Sessions directory: {sessions_dir}")
        logger.info("🔗 Session-Proxy binding enabled")    
    def _ensure_structure(self):
        """Đảm bảo cấu trúc thư mục và file tồn tại"""
        # Tạo sessions directory nếu chưa có
        if not os.path.exists(self.sessions_dir):
            os.makedirs(self.sessions_dir)
            logger.info(f"📁 Tạo thư mục sessions: {self.sessions_dir}")
        
        # Tạo status file nếu chưa có
        if not os.path.exists(self.status_file):
            self._create_initial_status_file()
        else:
            # Sync existing status file với session folders
            self._sync_session_folders_to_status()
        
        # Load resources vào memory
        self._load_resources_to_memory()
    
    def _is_valid_session_folder(self, session_path: str) -> bool:
        """
        Kiểm tra session folder có hợp lệ không
        
        Args:
            session_path: Đường dẫn đến session folder
            
        Returns:
            True nếu session folder hợp lệ
        """
        try:
            # Kiểm tra có các file/folder của Playwright session
            required_items = ['Local State', 'Default']
            
            for item in required_items:
                if not os.path.exists(os.path.join(session_path, item)):
                    return False
            
            return True
        except (OSError, FileNotFoundError):
            return False
    
    def _create_initial_status_file(self):
        """Tạo status file ban đầu với sessions được phát hiện."""
        initial_resources = {}
        
        # Tìm tất cả session folders có sẵn
        try:
            for item in os.listdir(self.sessions_dir):
                session_path = os.path.join(self.sessions_dir, item)
                if os.path.isdir(session_path):
                    # Auto-assign role based on naming or default to MIXED
                    role = AccountRole.MIXED  # Default
                    if "discovery" in item.lower():
                        role = AccountRole.DISCOVERY
                    elif "tracking" in item.lower():
                        role = AccountRole.TRACKING
                    
                    resource = ManagedResource(item, "session", role)
                    # Kiểm tra xem có phải session folder không
                    if self._is_valid_session_folder(session_path):
                        resource.status = "READY"
                    else:
                        resource.status = "NEEDS_LOGIN"
                    initial_resources[item] = resource.to_dict()
        except OSError:
            logger.warning("⚠️ Không thể scan sessions directory")
        
        # Nếu không có session nào, tạo template với role examples
        if not initial_resources:
            template_accounts = [
                ("account_discovery_1", AccountRole.DISCOVERY),
                ("account_discovery_2", AccountRole.DISCOVERY), 
                ("account_tracking_1", AccountRole.TRACKING),
                ("account_tracking_2", AccountRole.TRACKING),
                ("account_mixed_1", AccountRole.MIXED)
            ]
            
            for account_id, role in template_accounts:
                resource = ManagedResource(account_id, "session", role)
                resource.status = "NEEDS_LOGIN"
                initial_resources[account_id] = resource.to_dict()
            logger.info("📝 Tạo template session status - cần setup sessions")
        
        self._write_status_file(initial_resources)
        logger.info(f"📄 Tạo session status file với {len(initial_resources)} sessions")
    
    def _sync_session_folders_to_status(self):
        """Sync existing status file với session folders có sẵn"""
        try:
            # Load existing status data
            existing_status = self._read_status_file()
            updated = False
            
            # Scan session folders
            if os.path.exists(self.sessions_dir):
                for item in os.listdir(self.sessions_dir):
                    session_path = os.path.join(self.sessions_dir, item)
                    if os.path.isdir(session_path) and item not in existing_status:
                        # Found new session folder not in status file
                        logger.info(f"📁 Discovered new session folder: {item}")
                        
                        # Auto-assign role based on naming or default to MIXED
                        role = AccountRole.MIXED
                        if "discovery" in item.lower():
                            role = AccountRole.DISCOVERY
                        elif "tracking" in item.lower():
                            role = AccountRole.TRACKING
                        
                        resource = ManagedResource(item, "session", role)
                        # Check if valid session folder
                        if self._is_valid_session_folder(session_path):
                            resource.status = "READY"
                            logger.info(f"✅ Session {item} is valid and READY")
                        else:
                            resource.status = "NEEDS_LOGIN"
                            logger.warning(f"⚠️ Session {item} needs login")
                        
                        existing_status[item] = resource.to_dict()
                        updated = True
            
            # Remove sessions that no longer have folders
            sessions_to_remove = []
            for session_id in existing_status.keys():
                session_path = os.path.join(self.sessions_dir, session_id)
                if not os.path.exists(session_path) or not os.path.isdir(session_path):
                    sessions_to_remove.append(session_id)
                    logger.warning(f"⚠️ Session folder not found: {session_id}")
            
            for session_id in sessions_to_remove:
                del existing_status[session_id]
                updated = True
                logger.info(f"🗑️ Removed missing session: {session_id}")
            
            # Update file if changes were made
            if updated:
                self._write_status_file(existing_status)
                logger.info(f"🔄 Synced session status file: {len(existing_status)} sessions")
            else:
                logger.debug("💫 Session status file already in sync")
                
        except Exception as e:
            logger.error(f"❌ Error syncing session folders: {e}")
    
    def _load_resources_to_memory(self):
        """Load tất cả resources từ file vào memory cache."""
        status_data = self._read_status_file()
        self.resource_pool.clear()
        
        for resource_id, resource_data in status_data.items():
            try:
                resource = ManagedResource.from_dict(resource_data)
                self.resource_pool[resource_id] = resource
            except Exception as e:
                logger.warning(f"⚠️ Lỗi load resource {resource_id}: {e}")
                # Fallback to basic resource with MIXED role
                resource = ManagedResource(resource_id, "session", AccountRole.MIXED)
                if isinstance(resource_data, dict):
                    resource.status = resource_data.get("status", "NEEDS_LOGIN")
                self.resource_pool[resource_id] = resource
        
        logger.info(f"📋 Loaded {len(self.resource_pool)} resources to memory")
    
    def _read_status_file(self) -> Dict[str, Any]:
        """
        Đọc session status từ file (thread-safe)
        
        Returns:
            Dict chứa resource data
        """
        try:
            with open(self.status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # ⚡ MIGRATION: Convert old format to new ManagedResource format
                if data and isinstance(list(data.values())[0], (str, dict)):
                    migrated = self._migrate_old_format(data)
                    if migrated:
                        self._write_status_file(migrated)
                        return migrated
                
                return data
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"❌ Lỗi đọc session status: {e}")
            return {}
    
    def _migrate_old_format(self, old_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Migrate old session format to new ManagedResource format."""
        try:
            logger.info("🔄 Migrating to new ManagedResource format")
            migrated_data = {}
            
            for session_name, session_info in old_data.items():
                # Migrate with intelligent role detection or default to MIXED
                role = AccountRole.MIXED
                if "discovery" in session_name.lower():
                    role = AccountRole.DISCOVERY
                elif "tracking" in session_name.lower():
                    role = AccountRole.TRACKING
                    
                resource = ManagedResource(session_name, "session", role)
                
                if isinstance(session_info, str):
                    # Very old format: just status string
                    resource.status = session_info
                elif isinstance(session_info, dict):
                    # Newer format with some fields
                    resource.status = session_info.get("status", "NEEDS_LOGIN")
                    resource.consecutive_failures = session_info.get("failure_count", 0)
                    
                    # Try to preserve any existing tracking data
                    if "successful_tasks" in session_info:
                        resource.successful_tasks = session_info["successful_tasks"]
                    if "total_tasks" in session_info:
                        resource.total_tasks = session_info["total_tasks"]
                        resource.calculate_success_rate()
                
                migrated_data[session_name] = resource.to_dict()
            
            logger.info(f"✅ Migrated {len(migrated_data)} sessions to new format")
            return migrated_data
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            return None
    
    def _write_status_file(self, status_data: Dict[str, Any]):
        """
        Ghi session status vào file (thread-safe)
        
        Args:
            status_data: Dict chứa resource data
        """
        try:
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(status_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"❌ Lỗi ghi session status: {e}")
            raise
    
    def _execute_with_locks(self, operation_func):
        """
        Template Method Pattern - thực thi operation với thread + process locks.
        
        Args:
            operation_func: Callable to execute within locks
            
        Returns:
            Result from operation_func
        """
        with self.lock:
            if self.file_lock:
                with self.file_lock:
                    return operation_func()
            else:
                return operation_func()
    
    @contextmanager
    def locks(self):
        """
        Context manager for unified lock handling.
        Use this for cleaner code instead of _execute_with_locks.
        
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

    def _atomic_try_mark_session_in_use(self, session_name: str) -> bool:
        """
        ✅ FIX RACE CONDITION: Atomically check if session is available and mark as IN_USE.
        
        CRITICAL: This method uses CROSS-PROCESS FileLock to prevent multiple Celery workers
        from checking out the same session simultaneously.
        
        Args:
            session_name: Name of session to mark
            
        Returns:
            True if successfully marked as IN_USE, False if already taken or unavailable
        """
        # 🔒 CRITICAL: Use FileLock for cross-process atomicity (not just threading.Lock!)
        with self.locks():
            # Reload from file to get latest status from other processes
            self._load_resources_to_memory()
            
            if session_name not in self.resource_pool:
                return False
            
            session_resource = self.resource_pool[session_name]
            
            # Re-check all availability conditions atomically
            if session_resource.status == "IN_USE":
                return False
            if session_resource.is_quarantined():
                return False
            if session_resource.status in ["NEEDS_LOGIN", "DISABLED"]:
                return False
            
            # Mark as IN_USE atomically
            session_resource.status = "IN_USE"
            session_resource.last_used_timestamp = datetime.now()
            
            # Write immediately to file so other processes see it
            self._sync_resources_to_file(force=True)
            
            return True
    
    def _sync_resources_to_file(self, force: bool = False):
        """
        Sync in-memory resources back to file with batching optimization.
        
        Args:
            force: If True, sync immediately regardless of batching rules
        """
        # Track that a change was made
        self.changes_since_last_sync += 1
        self.pending_file_sync = True
        
        # Determine if we should write now
        current_time = datetime.now()
        time_elapsed = (current_time - self.last_file_sync_time).total_seconds()
        
        should_sync = (
            force or  # Forced sync
            time_elapsed >= self.file_sync_interval_seconds or  # Time-based
            self.changes_since_last_sync >= self.file_sync_change_threshold  # Change-based
        )
        
        if should_sync and self.pending_file_sync:
            status_data = {}
            for resource_id, resource in self.resource_pool.items():
                status_data[resource_id] = resource.to_dict()
            self._write_status_file(status_data)
            
            # Reset tracking
            self.pending_file_sync = False
            self.last_file_sync_time = current_time
            self.changes_since_last_sync = 0
            logger.debug(f"📝 Synced {len(status_data)} resources to file")
    
    def checkout_session(self, timeout: int = 30) -> Optional[str]:
        """
        Intelligent session checkout với performance-based selection
        
        ⚠️ DEPRECATED: Use checkout_session_with_proxy() for production
        This method is maintained for backward compatibility and unit testing
        
        Args:
            timeout: Thời gian chờ tối đa (giây) để lấy session
            
        Returns:
            Tên session nếu thành công, None nếu không có session sẵn sàng
        """
        import warnings
        warnings.warn(
            "checkout_session() is deprecated. Use checkout_session_with_proxy() for production "
            "to ensure consistent session-proxy binding.",
            DeprecationWarning,
            stacklevel=2
        )
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Process cooldowns first
            self._process_cooldowns()
            
            # Use refactored lock helper
            result = self._execute_with_locks(self._intelligent_checkout)
            if result:
                self._execute_with_locks(self._sync_resources_to_file)
                return result
            
            time.sleep(1)
        
        logger.warning(f"⏰ Timeout checkout session sau {timeout}s")
        return None

    def checkout_session_with_proxy(self, proxy_manager, timeout: int = 30) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Checkout session cùng với proxy đã được bind - PERSISTENT BINDING
        
        Args:
            proxy_manager: Instance của ProxyManager
            timeout: Timeout in seconds
            
        Returns:
            Tuple (session_name, proxy_config) nếu thành công, None nếu thất bại
        """
        import os
        
        try:
            start_time = time.time()
            
            # Process cooldowns first
            self._process_cooldowns()
            
            while time.time() - start_time < timeout:
                # 🔒 FIX RACE CONDITION: Wrap entire checkout in atomic lock
                with self.locks():
                    # Reload from file to get latest status from other processes
                    self._load_resources_to_memory()
                    
                    # Try each available session with ROTATION
                    # Sort sessions by last_used_timestamp (least recently used first) for fair rotation
                    sorted_sessions = sorted(
                        self.resource_pool.items(),
                        key=lambda x: x[1].last_used_timestamp or datetime.min
                    )
                    
                    for session_name, session_resource in sorted_sessions:
                        # Re-check all availability conditions atomically
                        if session_resource.status == "IN_USE":
                            continue
                        if session_resource.is_quarantined():
                            continue
                        if session_resource.status in ["NEEDS_LOGIN", "DISABLED"]:
                            continue
                        
                        try:
                            # 🚀 SIMPLE: Lấy danh sách proxy READY
                            ready_proxy_ids = [
                                pid for pid, pres in proxy_manager.resource_pool.items()
                                if pres.status == "READY" and pres.metadata.get("config")
                            ]
                            
                            if not ready_proxy_ids:
                                logger.debug(f"⚠️ No READY proxies available")
                                continue
                            
                            # Get proxy đã bind hoặc bind mới (tự động xử lý)
                            bound_proxy_id = self.proxy_binder.get_proxy_for_session(
                                session_name, ready_proxy_ids
                            )
                            
                            if not bound_proxy_id:
                                logger.debug(f"⚠️ Session {session_name}: binding failed")
                                continue
                            
                            # Check proxy có READY không
                            proxy_resource = proxy_manager.resource_pool.get(bound_proxy_id)
                            if not proxy_resource:
                                logger.warning(f"⚠️ Proxy {bound_proxy_id} not found")
                                continue
                            
                            if proxy_resource.status != "READY":
                                logger.debug(f"⚠️ Proxy {bound_proxy_id} not READY (status={proxy_resource.status})")
                                continue
                            
                            if proxy_resource.is_quarantined():
                                logger.debug(f"⚠️ Proxy {bound_proxy_id} quarantined")
                                continue
                            
                            proxy_config = proxy_resource.metadata.get("config")
                            if not proxy_config:
                                logger.warning(f"⚠️ Proxy {bound_proxy_id} no config")
                                continue
                            
                            # 🔥 FIX #2: AUTO-UNBIND if proxy repeatedly fails health checks
                            # Check if proxy has consecutive failures
                            if proxy_resource.consecutive_failures >= 2:
                                logger.warning(f"🔓 Auto-unbinding session {session_name} from failing proxy {bound_proxy_id} ({proxy_resource.consecutive_failures} failures)")
                                self.proxy_binder.unbind_session(session_name)
                                # Try next session in the rotation
                                continue
                            
                            # ✅ ATOMIC: Mark both session AND proxy as IN_USE within same lock
                            session_resource.status = "IN_USE"
                            session_resource.last_used_timestamp = datetime.now()
                            
                            proxy_resource.status = "IN_USE"
                            proxy_resource.last_used_timestamp = datetime.now()
                            
                            # Write immediately to file so other processes see it
                            self._sync_resources_to_file(force=True)
                            
                            # Return session + proxy
                            proxy_config_copy = proxy_config.copy()
                            proxy_config_copy["proxy_id"] = bound_proxy_id
                            
                            logger.info(f"✅ Checkout: {session_name} -> {bound_proxy_id}")
                            return (session_name, proxy_config_copy)
                            
                        except Exception as e:
                            logger.error(f"❌ Error binding session {session_name}: {e}")
                            continue
                
                # Sleep outside lock to avoid blocking other workers
                time.sleep(1)
            
            logger.warning("⚠️ Could not bind any available session with proxy")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error in session-proxy checkout: {e}")
            return None
    
    def _checkout_session_with_bound_proxy(self, proxy_manager) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Internal method để checkout session với bound proxy
        """
        try:
            # Get available sessions
            available_sessions = []
            for session_name, resource in self.resource_pool.items():
                if resource.status == "READY" and not resource.is_quarantined():
                    available_sessions.append(session_name)
            
            if not available_sessions:
                return None
            
            # Get available proxies
            proxy_stats = proxy_manager.get_stats()
            if proxy_stats['ready'] == 0:
                logger.warning("⚠️ No ready proxies available for session binding")
                return None
            
            # Try each available session to find one that can get a proxy
            for session_name in available_sessions:
                try:
                    # Get available proxy IDs from proxy manager - WITH HEALTH CHECK
                    available_proxy_ids = []
                    for proxy_id, proxy_resource in proxy_manager.resource_pool.items():
                        if proxy_resource.status == "READY" and not proxy_resource.is_quarantined():
                            # CRITICAL: Verify proxy health before assigning
                            proxy_config = proxy_resource.metadata.get("config", {})
                            if proxy_config:
                                proxy_config["proxy_id"] = proxy_id  # Add proxy_id for health check
                                
                                # Check if proxy recently passed health check (within last 5 minutes)
                                last_checked = proxy_resource.metadata.get("last_checked")
                                if last_checked:
                                    try:
                                        from datetime import datetime, timedelta
                                        last_check_time = datetime.fromisoformat(last_checked)
                                        if datetime.now() - last_check_time < timedelta(minutes=5):
                                            # Recently verified, trust it
                                            available_proxy_ids.append(proxy_id)
                                            continue
                                    except (ValueError, TypeError) as e:
                                        logger.debug(f"Failed to parse last_checked timestamp for proxy {proxy_id}: {e}")
                                        pass
                                
                                # Run health check (sync version)
                                if proxy_manager.health_check_proxy(proxy_config):
                                    # Update last_checked timestamp to cache result
                                    proxy_resource.metadata["last_checked"] = datetime.now().isoformat()
                                    available_proxy_ids.append(proxy_id)
                                    logger.debug(f"✅ Proxy {proxy_id} verified healthy")
                                else:
                                    logger.warning(f"⚠️ Proxy {proxy_id} failed health check, skipping")
                            else:
                                logger.warning(f"⚠️ Proxy {proxy_id} has no config, skipping")
                    
                    if not available_proxy_ids:
                        continue
                    
                    # Get or assign bound proxy for this session
                    bound_proxy_id = self.proxy_binder.get_proxy_for_session(
                        session_name, available_proxy_ids
                    )
                    
                    if not bound_proxy_id:
                        continue
                    
                    # Checkout the bound proxy
                    proxy_resource = proxy_manager.resource_pool.get(bound_proxy_id)
                    if not proxy_resource or proxy_resource.status != "READY":
                        logger.warning(f"⚠️ Bound proxy {bound_proxy_id} not ready, trying next session")
                        continue
                    
                    # Mark proxy as IN_USE
                    proxy_resource.status = "IN_USE"
                    proxy_resource.last_used_timestamp = datetime.now()
                    
                    # Prepare proxy config
                    proxy_config = proxy_resource.metadata.get("config", {}).copy()
                    proxy_config["proxy_id"] = bound_proxy_id
                    
                    # ✅ FIX RACE CONDITION: Atomically mark session as IN_USE
                    if not self._atomic_try_mark_session_in_use(session_name):
                        logger.debug(f"⚠️ Session {session_name} was taken by another worker, trying next...")
                        continue
                    
                    logger.info(f"🔗 Session-Proxy bound checkout: {session_name} -> {bound_proxy_id}")
                    return (session_name, proxy_config)
                    
                except Exception as e:
                    logger.error(f"❌ Error binding session {session_name}: {e}")
                    continue
            
            logger.warning("⚠️ Could not bind any available session with proxy")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error in session-proxy checkout: {e}")
            return None
    
    def checkin_session_with_proxy(self, session_name: str, proxy_config: Dict[str, Any], 
                                 proxy_manager, session_status: str = "READY", 
                                 proxy_status: str = "READY"):
        """
        Checkin session cùng với proxy được bind
        
        Args:
            session_name: Tên session
            proxy_config: Config của proxy (chứa proxy_id)
            proxy_manager: Instance của ProxyManager
            session_status: Status mới của session
            proxy_status: Status mới của proxy
        """
        try:
            # Checkin session
            self.checkin_session(session_name, session_status)
            
            # Checkin proxy
            if proxy_config and "proxy_id" in proxy_config:
                proxy_manager.checkin_proxy(proxy_config, proxy_status)
                
                logger.info(f"🔓 Session-Proxy checkin: {session_name} & {proxy_config['proxy_id']}")
            else:
                logger.warning(f"⚠️ Invalid proxy config for checkin: {proxy_config}")
                
        except Exception as e:
            logger.error(f"❌ Error in session-proxy checkin: {e}")
    
    def checkout_session_by_role(self, role: AccountRole, timeout: int = 30) -> Optional[str]:
        """
        Checkout session theo vai trò cụ thể (SPECIALIZED VERSION)
        
        Args:
            role: Vai trò account cần checkout (DISCOVERY, TRACKING, MIXED)
            timeout: Thời gian chờ tối đa (giây) để lấy session
            
        Returns:
            Tên session nếu thành công, None nếu không có session phù hợp
        """
        start_time = time.time()
        
        logger.debug(f"🎯 Requesting session with role: {role.value}")
        
        while time.time() - start_time < timeout:
            # Process cooldowns first
            self._process_cooldowns()
            
            # Use refactored lock helper
            result = self._execute_with_locks(
                lambda: self._intelligent_checkout_by_role(role)
            )
            if result:
                self._execute_with_locks(self._sync_resources_to_file)
                logger.info(f"✅ Assigned {role.value} session: {result}")
                return result
            
            time.sleep(1)
        
        logger.warning(f"⏰ Timeout checkout session by role {role.value} sau {timeout}s")
        return None
    
    def _intelligent_checkout(self) -> Optional[str]:
        """
        Intelligent session selection dựa trên performance và health
        """
        try:
            # Get available sessions (not in use, not quarantined)
            available_sessions = []
            
            for resource_id, resource in self.resource_pool.items():
                # Skip if in use or quarantined
                if resource.status == "IN_USE" or resource.is_quarantined():
                    continue
                
                # Skip if needs login or disabled
                if resource.status in ["NEEDS_LOGIN", "DISABLED"]:
                    continue
                
                # Validate session folder
                session_path = os.path.join(self.sessions_dir, resource_id)
                if not os.path.exists(session_path) or not self._is_valid_session_folder(session_path):
                    logger.warning(f"⚠️ Session invalid: {resource_id}")
                    resource.status = "NEEDS_LOGIN"
                    self.changes_since_last_sync += 1  # Track change for batching
                    continue
                
                available_sessions.append(resource)
            
            if not available_sessions:
                self._log_resource_stats()
                return None
            
            # Intelligent selection: prioritize by success rate, then by least recently used
            selected = self._select_best_resource(available_sessions)
            
            # Mark as IN_USE and update timestamps
            selected.status = "IN_USE"
            selected.last_used_timestamp = datetime.now()
            
            logger.info(f"🎯 Intelligently selected session: {selected.id} (success_rate: {selected.success_rate:.2f})")
            return selected.id
            
        except Exception as e:
            logger.error(f"❌ Lỗi intelligent checkout: {e}")
            return None
    
    def _intelligent_checkout_by_role(self, role: AccountRole) -> Optional[str]:
        """
        Intelligent session selection dựa trên role và performance
        
        Args:
            role: Required AccountRole (DISCOVERY, TRACKING, MIXED)
            
        Returns:
            Session ID nếu tìm thấy phù hợp, None nếu không có
        """
        try:
            # Get available sessions with matching role or fallback to MIXED
            available_sessions = []
            
            for resource_id, resource in self.resource_pool.items():
                # Skip if in use or quarantined
                if resource.status == "IN_USE" or resource.is_quarantined():
                    continue
                
                # Skip if needs login or disabled
                if resource.status in ["NEEDS_LOGIN", "DISABLED"]:
                    continue
                
                # Validate session folder
                session_path = os.path.join(self.sessions_dir, resource_id)
                if not os.path.exists(session_path) or not self._is_valid_session_folder(session_path):
                    logger.warning(f"⚠️ Session invalid: {resource_id}")
                    resource.status = "NEEDS_LOGIN"
                    continue
                
                # 🎯 ROLE MATCHING LOGIC
                # 1st priority: Exact role match
                if resource.role == role:
                    available_sessions.append((resource, 10))  # Priority 10
                # 2nd priority: MIXED can do anything
                elif resource.role == AccountRole.MIXED:
                    available_sessions.append((resource, 5))   # Priority 5
                # Skip if role doesn't match and not MIXED
            
            if not available_sessions:
                logger.debug(f"🔍 No sessions available for role: {role.value}")
                return None
            
            # Sort by priority (highest first), then by performance
            available_sessions.sort(key=lambda x: (x[1], x[0].success_rate), reverse=True)
            
            # Select best resource (highest priority + best performance)
            selected_resource = available_sessions[0][0]
            
            # Mark as IN_USE and update timestamps
            selected_resource.status = "IN_USE"
            selected_resource.last_used_timestamp = datetime.now()
            
            logger.info(f"🎯 Selected {role.value} session: {selected_resource.id} (role: {selected_resource.role.value}, success_rate: {selected_resource.success_rate:.2f})")
            return selected_resource.id
            
        except Exception as e:
            logger.error(f"❌ Lỗi checkout by role: {e}")
            return None
    
    def _select_best_resource(self, available_resources: List[ManagedResource]) -> ManagedResource:
        """
        Select best resource based on performance metrics
        """
        # Sort by success rate (desc), then by last used (asc)
        sorted_resources = sorted(
            available_resources,
            key=lambda r: (
                -r.success_rate,  # Higher success rate first
                r.consecutive_failures,  # Fewer failures first
                r.last_used_timestamp or datetime.min  # Least recently used first
            )
        )
        
        return sorted_resources[0]
    
    def _process_cooldowns(self) -> int:
        """
        ✅ FIX RACE CONDITION: Process quarantined resources with thread-safe status updates.
        
        Returns:
            Number of resources released from quarantine
        """
        current_time = datetime.now()
        released_count = 0
        
        # Use lock to prevent race conditions when multiple threads call this
        with self.lock:
            for resource in self.resource_pool.values():
                if resource.status == "QUARANTINED" and resource.quarantine_until_timestamp:
                    if current_time >= resource.quarantine_until_timestamp:
                        resource.status = "READY"
                        resource.quarantine_until_timestamp = None
                        resource.consecutive_failures = 0  # Reset failures after cooldown
                        released_count += 1
                        logger.info(f"🎆 Resource {resource.id} released from quarantine")
        
        return released_count
    
    def _log_resource_stats(self) -> None:
        """
        Log current resource statistics for debugging.
        
        Returns:
            None
        """
        stats = {"ready": 0, "in_use": 0, "quarantined": 0, "needs_login": 0, "disabled": 0}
        
        for resource in self.resource_pool.values():
            if resource.status == "READY":
                stats["ready"] += 1
            elif resource.status == "IN_USE":
                stats["in_use"] += 1
            elif resource.is_quarantined():
                stats["quarantined"] += 1
            elif resource.status == "NEEDS_LOGIN":
                stats["needs_login"] += 1
            elif resource.status == "DISABLED":
                stats["disabled"] += 1
        
        logger.debug(f"📊 Resource stats: {stats}")
    
    def checkin_session(self, session_name: str, status: str = "READY"):
        """
        Intelligent session checkin với performance tracking
        
        Args:
            session_name: Tên session cần trả lại
            status: Trạng thái mới của session (default: "READY")
        """
        self._execute_with_locks(
            lambda: self._intelligent_checkin(session_name, status)
        )
        self._execute_with_locks(self._sync_resources_to_file)
    
    def _intelligent_checkin(self, session_name: str, status: str) -> None:
        """
        Intelligent checkin với performance tracking.
        
        Args:
            session_name: Tên session
            status: Status mới
            
        Returns:
            None
        """
        try:
            if session_name not in self.resource_pool:
                logger.warning(f"⚠️ Session không tồn tại: {session_name}")
                return
            
            resource = self.resource_pool[session_name]
            old_status = resource.status
            resource.status = status
            
            logger.info(f"🔓 Checked in session: {session_name} ({old_status} → {status})")
            
        except Exception as e:
            logger.error(f"❌ Lỗi intelligent checkin {session_name}: {e}")
    
    def configure_account_roles(self, role_assignments: Dict[str, AccountRole]) -> int:
        """
        Configure account roles for specialized assignment
        
        Args:
            role_assignments: Dict mapping session_name -> AccountRole
                              e.g., {"account_1": AccountRole.DISCOVERY, "account_2": AccountRole.TRACKING}
                              
        Returns:
            Số lượng accounts đã configure
        """
        def _update_roles():
            updated_count = 0
            for session_name, role in role_assignments.items():
                if session_name in self.resource_pool:
                    old_role = self.resource_pool[session_name].role
                    self.resource_pool[session_name].role = role
                    logger.info(f"🎯 Account {session_name}: {old_role.value} → {role.value}")
                    updated_count += 1
                else:
                    logger.warning(f"⚠️ Session {session_name} không tồn tại để configure role")
            return updated_count
        
        updated_count = self._execute_with_locks(_update_roles)
        
        if updated_count > 0:
            self._execute_with_locks(self._sync_resources_to_file)
            logger.info(f"✅ Đã configure {updated_count} account roles")
            
        return updated_count
    
    def get_accounts_by_role(self, role: AccountRole) -> List[str]:
        """
        Lấy danh sách account names theo role cụ thể
        
        Args:
            role: AccountRole cần tìm
            
        Returns:
            List session names có role phù hợp
        """
        with self.lock:
            return [
                resource_id for resource_id, resource in self.resource_pool.items()
                if resource.role == role
            ]
    
    def get_role_distribution(self) -> Dict[str, int]:
        """
        Lấy phân bổ roles trong pool
        
        Returns:
            Dict với key là role names và value là count
        """
        with self.lock:
            distribution = {}
            for resource in self.resource_pool.values():
                role_name = resource.role.value
                distribution[role_name] = distribution.get(role_name, 0) + 1
            return distribution

    def get_session_path(self, session_name: str) -> str:
        """
        Lấy đường dẫn đầy đủ đến session folder
        
        Args:
            session_name: Tên session
            
        Returns:
            Đường dẫn đầy đủ đến session folder
        """
        return os.path.join(self.sessions_dir, session_name)
    
    def get_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Lấy trạng thái hiện tại của tất cả sessions (thread + process-safe)
        
        Returns:
            Dict chứa session status và performance metrics
        """
        with self.lock:
            result = {}
            for resource_id, resource in self.resource_pool.items():
                result[resource_id] = {
                    "status": resource.status,
                    "role": resource.role.value,  # Include role info
                    "success_rate": resource.success_rate,
                    "consecutive_failures": resource.consecutive_failures,
                    "total_tasks": resource.total_tasks,
                    "quarantine_reason": resource.quarantine_reason,
                    "last_used": resource.last_used_timestamp.isoformat() if resource.last_used_timestamp else None
                }
            return result
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Lấy thống kê chi tiết về sessions và performance
        
        Returns:
            Dict chứa thống kê chi tiết
        """
        with self.lock:
            stats = {
                'total': len(self.resource_pool),
                'ready': 0,
                'in_use': 0,
                'quarantined': 0,
                'needs_login': 0,
                'disabled': 0,
                'cooldown': 0,
                'performance': {
                    'avg_success_rate': 0.0,
                    'total_tasks': 0,
                    'successful_tasks': 0,
                    'high_performers': 0,  # success_rate > 0.8
                    'low_performers': 0,   # success_rate < 0.5
                },
                'role_distribution': {
                    'discovery': 0,
                    'tracking': 0, 
                    'mixed': 0
                }
            }
            
            total_success_rate = 0.0
            resources_with_tasks = 0
            
            for resource in self.resource_pool.values():
                # Count by status
                if resource.status == "READY":
                    stats['ready'] += 1
                elif resource.status == "IN_USE":
                    stats['in_use'] += 1
                elif resource.is_quarantined():
                    stats['quarantined'] += 1
                elif resource.status == "NEEDS_LOGIN":
                    stats['needs_login'] += 1
                elif resource.status == "DISABLED":
                    stats['disabled'] += 1
                elif resource.status == "COOLDOWN":
                    stats['cooldown'] += 1
                
                # Count by role
                role_name = resource.role.value
                if role_name in stats['role_distribution']:
                    stats['role_distribution'][role_name] += 1
                
                # Performance metrics
                stats['performance']['total_tasks'] += resource.total_tasks
                stats['performance']['successful_tasks'] += resource.successful_tasks
                
                if resource.total_tasks > 0:
                    total_success_rate += resource.success_rate
                    resources_with_tasks += 1
                    
                    if resource.success_rate > 0.8:
                        stats['performance']['high_performers'] += 1
                    elif resource.success_rate < 0.5:
                        stats['performance']['low_performers'] += 1
            
            # Calculate average success rate
            if resources_with_tasks > 0:
                stats['performance']['avg_success_rate'] = total_success_rate / resources_with_tasks
            
            return stats

    def get_all_sessions_status(self) -> Dict[str, Any]:
        """
        Lấy trạng thái của tất cả sessions cho diagnostic
        
        Returns:
            Dict chứa thông tin chi tiết về sessions
        """
        with self.lock:
            sessions_status = {}
            ready_count = 0
            in_use_count = 0
            failed_count = 0
            quarantined_count = 0
            
            for session_name, resource in self.resource_pool.items():
                status_info = {
                    "status": resource.status,
                    "success_rate": resource.success_rate,
                    "total_tasks": resource.total_tasks,
                    "consecutive_failures": resource.consecutive_failures,
                    "is_quarantined": resource.is_quarantined(),
                    "last_used": resource.last_used_timestamp.isoformat() if resource.last_used_timestamp else None,
                    "role": resource.metadata.get("role", "MIXED")
                }
                sessions_status[session_name] = status_info
                
                # Count by status
                if resource.status == "READY":
                    ready_count += 1
                elif resource.status == "IN_USE":
                    in_use_count += 1
                elif resource.status == "FAILED":
                    failed_count += 1
                elif resource.is_quarantined():
                    quarantined_count += 1
            
            return {
                "sessions": sessions_status,
                "summary": {
                    "total": len(self.resource_pool),
                    "ready": ready_count,
                    "in_use": in_use_count,
                    "failed": failed_count,
                    "quarantined": quarantined_count
                }
            }
    
    def mark_session_invalid(self, session_name: str, reason: str = ""):
        """
        Đánh dấu session không hợp lệ (cần login lại)
        
        Args:
            session_name: Tên session
            reason: Lý do không hợp lệ
        """
        logger.warning(f"❌ Marking session invalid: {session_name} - {reason}")
        self.checkin_session(session_name, "NEEDS_LOGIN")
    
    def report_outcome(self, session_name: str, outcome: str, details: Optional[Dict[str, Any]] = None) -> None:
        """
        Báo cáo kết quả task để cập nhật performance metrics
        
        Args:
            session_name: Tên session
            outcome: 'success' hoặc 'failure'
            details: Thông tin chi tiết về task
            
        Returns:
            None
        """
        with self.locks():
            if session_name not in self.resource_pool:
                logger.warning(f"⚠️ Session không tồn tại để report outcome: {session_name}")
                return
            
            resource = self.resource_pool[session_name]
            resource.total_tasks += 1
            
            if outcome == 'success':
                resource.successful_tasks += 1
                resource.consecutive_failures = 0
                logger.debug(f"✅ Success reported for {session_name}")
            elif outcome == 'failure':
                resource.consecutive_failures += 1
                logger.debug(f"❌ Failure reported for {session_name} (consecutive: {resource.consecutive_failures})")
                
                # 🔥 FIX #4: CIRCUIT BREAKER - Unbind proxy after repeated failures
                # This breaks the error loop between session and bad proxy
                if resource.consecutive_failures >= 3:
                    logger.critical(f"🔌 CIRCUIT BREAKER: Session {session_name} has {resource.consecutive_failures} consecutive failures")
                    # Unbind from current proxy to allow re-assignment
                    try:
                        self.proxy_binder.unbind_session(session_name)
                        logger.warning(f"🔓 Circuit breaker unbound session {session_name} to break error loop")
                        
                        # 🔥 CRITICAL FIX: Reset failures to allow session recovery
                        resource.consecutive_failures = 0
                        logger.info(f"♻️ Reset consecutive failures for {session_name} after circuit break")
                        
                        # Persist immediately to prevent loss on crash
                        self._sync_resources_to_file()
                        
                    except Exception as e:
                        logger.error(f"❌ Failed to unbind session in circuit breaker: {e}")
            
            # Recalculate success rate
            resource.calculate_success_rate()
            
            # Check if should be quarantined
            if resource.should_be_quarantined(
                self.consecutive_failure_threshold,
                self.success_rate_threshold,
                self.min_tasks_for_rate_calc
            ):
                self.quarantine_resource(session_name, f"Performance threshold exceeded: {resource.consecutive_failures} consecutive failures, {resource.success_rate:.2f} success rate")
            
            # Sync to file
            self._sync_resources_to_file()
    
    def quarantine_resource(self, session_name: str, reason: str = "Performance issues") -> None:
        """
        Cách ly resource vào quarantine với cooldown period
        
        Args:
            session_name: Tên session
            reason: Lý do cách ly
            
        Returns:
            None
        """
        with self.locks():
            if session_name not in self.resource_pool:
                logger.warning(f"⚠️ Session không tồn tại để quarantine: {session_name}")
                return
            
            resource = self.resource_pool[session_name]
            resource.status = "QUARANTINED"
            resource.quarantine_reason = reason
            resource.quarantine_count += 1
            resource.quarantine_until_timestamp = datetime.now() + timedelta(minutes=self.quarantine_duration_minutes)
            
            logger.warning(f"🚨 Session {session_name} quarantined until {resource.quarantine_until_timestamp.strftime('%H:%M:%S')} - {reason}")
            
            # Sync to file
            self._sync_resources_to_file()
    
    def reset_all_sessions(self) -> None:
        """
        Reset tất cả sessions về trạng thái READY (debug only) - thread + process-safe.
        
        Returns:
            None
        """
        with self.locks():
            for resource in self.resource_pool.values():
                resource.status = "READY"
                resource.consecutive_failures = 0
                resource.quarantine_until_timestamp = None
                resource.quarantine_reason = None
            
            self._sync_resources_to_file(force=True)  # Force immediate sync for reset
            logger.info("🔄 Reset tất cả sessions về READY")
    
    def check_cooldowns(self) -> int:
        """
        Public method để kiểm tra và xử lý cooldowns (có thể gọi từ scheduler).
        
        Returns:
            Number of resources released from quarantine
        """
        with self.locks():
            released_count = self._process_cooldowns()
            self._sync_resources_to_file(force=True)  # Force sync for cooldown updates
            return released_count
    
    def increment_failure_count(self, session_name: str, threshold: int = 3) -> bool:
        """
        Legacy compatibility - redirects to report_outcome
        
        Args:
            session_name: Tên session
            threshold: Ngưỡng failures (deprecated, uses class settings)
            
        Returns:
            True nếu session đã bị quarantine
        """
        logger.debug(f"Legacy increment_failure_count called for {session_name}")
        
        with self.lock:
            if session_name not in self.resource_pool:
                return False
            
            resource = self.resource_pool[session_name]
            was_quarantined_before = resource.is_quarantined()
            
            # Report failure
            self.report_outcome(session_name, 'failure')
            
            # Check if newly quarantined
            return resource.is_quarantined() and not was_quarantined_before
    
    
    def reset_failure_count(self, session_name: str):
        """
        Legacy compatibility - redirects to report_outcome
        
        Args:
            session_name: Tên session
        """
        logger.debug(f"Legacy reset_failure_count called for {session_name}")
        self.report_outcome(session_name, 'success')
    

    def list_sessions(self) -> List[str]:
        """
        Lấy danh sách tất cả session names
        
        Returns:
            List tên sessions
        """
        with self.lock:
            return list(self.resource_pool.keys())
    
    def get_session_performance(self, session_name: str) -> Optional[Dict[str, Any]]:
        """
        Lấy performance metrics của một session cụ thể
        
        Args:
            session_name: Tên session
            
        Returns:
            Dict chứa performance metrics hoặc None nếu không tìm thấy
        """
        with self.lock:
            if session_name not in self.resource_pool:
                return None
            
            resource = self.resource_pool[session_name]
            return {
                "success_rate": resource.success_rate,
                "total_tasks": resource.total_tasks,
                "successful_tasks": resource.successful_tasks,
                "consecutive_failures": resource.consecutive_failures,
                "quarantine_count": resource.quarantine_count,
                "last_used": resource.last_used_timestamp.isoformat() if resource.last_used_timestamp else None,
                "quarantine_reason": resource.quarantine_reason,
                "is_quarantined": resource.is_quarantined()
            }
    
    def get_best_performers(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Lấy danh sách sessions với performance tốt nhất
        
        Args:
            limit: Số lượng sessions trả về
            
        Returns:
            List các session với performance metrics
        """
        with self.lock:
            # Filter resources with enough tasks
            qualified_resources = [
                resource for resource in self.resource_pool.values()
                if resource.total_tasks >= self.min_tasks_for_rate_calc
            ]
            
            # Sort by success rate descending
            sorted_resources = sorted(
                qualified_resources,
                key=lambda r: (-r.success_rate, -r.total_tasks)
            )
            
            result = []
            for resource in sorted_resources[:limit]:
                result.append({
                    "session_name": resource.id,
                    "success_rate": resource.success_rate,
                    "total_tasks": resource.total_tasks,
                    "consecutive_failures": resource.consecutive_failures,
                    "status": resource.status
                })
            
            return result
    
    def get_quarantined_sessions(self) -> List[Dict[str, Any]]:
        """
        Lấy danh sách các sessions đang bị quarantine
        
        Returns:
            List các session bị quarantine với thông tin chi tiết
        """
        with self.lock:
            quarantined = []
            
            for resource in self.resource_pool.values():
                if resource.is_quarantined():
                    time_left = None
                    if resource.quarantine_until_timestamp:
                        time_left = (resource.quarantine_until_timestamp - datetime.now()).total_seconds()
                        time_left = max(0, time_left)  # Don't show negative time
                    
                    quarantined.append({
                        "session_name": resource.id,
                        "quarantine_reason": resource.quarantine_reason,
                        "quarantine_count": resource.quarantine_count,
                        "time_left_seconds": time_left,
                        "success_rate": resource.success_rate,
                        "consecutive_failures": resource.consecutive_failures
                    })
            
            return quarantined
    
    def auto_cleanup_stuck_sessions(self, timeout_minutes: int = 30) -> int:
        """
        🔥 AUTO CLEANUP: Tự động phát hiện và giải phóng sessions bị stuck
        
        Một session được coi là "stuck" nếu:
        - Status = IN_USE
        - last_used_timestamp > timeout_minutes
        
        Args:
            timeout_minutes: Số phút timeout để coi session là stuck
            
        Returns:
            Số sessions đã được giải phóng
        """
        released_count = 0
        current_time = datetime.now()
        timeout_delta = timedelta(minutes=timeout_minutes)
        
        with self.locks():
            for session_name, resource in self.resource_pool.items():
                # Check if session is stuck
                if resource.status == "IN_USE":
                    # If no last_used_timestamp, use created_at
                    check_time = resource.last_used_timestamp or resource.created_at
                    
                    if check_time:
                        time_in_use = current_time - check_time
                        
                        if time_in_use > timeout_delta:
                            # Session is stuck! Release it
                            logger.warning(
                                f"🚨 STUCK SESSION DETECTED: {session_name} has been IN_USE for "
                                f"{time_in_use.total_seconds()/60:.1f} minutes. Releasing..."
                            )
                            
                            resource.status = "READY"
                            resource.last_used_timestamp = current_time
                            released_count += 1
                            
                            logger.info(f"✅ Released stuck session: {session_name}")
            
            if released_count > 0:
                self._sync_resources_to_file(force=True)
                logger.info(f"🧹 Auto-cleanup released {released_count} stuck sessions")
            
            return released_count
    
    def get_in_use_sessions_info(self) -> List[Dict[str, Any]]:
        """
        Lấy thông tin chi tiết về các sessions đang IN_USE
        Hữu ích cho monitoring và debugging
        
        Returns:
            List thông tin các sessions IN_USE
        """
        with self.lock:
            in_use_sessions = []
            current_time = datetime.now()
            
            for resource in self.resource_pool.values():
                if resource.status == "IN_USE":
                    check_time = resource.last_used_timestamp or resource.created_at
                    time_in_use = None
                    
                    if check_time:
                        time_in_use = (current_time - check_time).total_seconds() / 60  # minutes
                    
                    in_use_sessions.append({
                        "session_name": resource.id,
                        "role": resource.role.value,
                        "last_used": check_time.isoformat() if check_time else None,
                        "time_in_use_minutes": round(time_in_use, 2) if time_in_use else None,
                        "total_tasks": resource.total_tasks,
                        "success_rate": resource.success_rate,
                        "consecutive_failures": resource.consecutive_failures
                    })
            
            return in_use_sessions
    
    def health_check_sessions(self) -> Dict[str, Any]:
        """
        🏥 HEALTH CHECK: Kiểm tra sức khỏe toàn bộ session pool
        
        Returns:
            Dict với thông tin health check và recommendations
        """
        with self.lock:
            stats = self.get_stats()
            in_use_info = self.get_in_use_sessions_info()
            quarantined_info = self.get_quarantined_sessions()
            
            # Calculate health score (0-100)
            health_score = 100
            warnings = []
            recommendations = []
            
            # Check 1: Too many sessions stuck in IN_USE
            stuck_sessions = [s for s in in_use_info if s.get("time_in_use_minutes", 0) > 15]
            if stuck_sessions:
                health_score -= 20
                warnings.append(f"{len(stuck_sessions)} sessions stuck IN_USE for >15 minutes")
                recommendations.append("Run auto_cleanup_stuck_sessions()")
            
            # Check 2: Too many quarantined sessions
            if stats['quarantined'] > stats['total'] * 0.3:  # More than 30% quarantined
                health_score -= 25
                warnings.append(f"High quarantine rate: {stats['quarantined']}/{stats['total']} sessions")
                recommendations.append("Investigate and fix underlying issues causing failures")
            
            # Check 3: No ready sessions available
            if stats['ready'] == 0:
                health_score -= 30
                warnings.append("No READY sessions available - system may be deadlocked")
                recommendations.append("URGENT: Run reset_all_sessions() or auto_cleanup_stuck_sessions()")
            
            # Check 4: Sessions requiring login
            if stats['needs_login'] > stats['total'] * 0.2:  # More than 20% need login
                health_score -= 15
                warnings.append(f"{stats['needs_login']} sessions need re-login")
                recommendations.append("Re-login required sessions using auto_login.py")
            
            # Check 5: Low average success rate
            if stats['average_success_rate'] < 0.5:  # Below 50%
                health_score -= 10
                warnings.append(f"Low average success rate: {stats['average_success_rate']:.1%}")
                recommendations.append("Review scraping logic and error handling")
            
            health_status = "HEALTHY" if health_score >= 80 else "DEGRADED" if health_score >= 50 else "CRITICAL"
            
            return {
                "health_status": health_status,
                "health_score": max(0, health_score),
                "timestamp": datetime.now().isoformat(),
                "stats": stats,
                "warnings": warnings,
                "recommendations": recommendations,
                "in_use_sessions": in_use_info,
                "quarantined_sessions": quarantined_info,
                "stuck_sessions_count": len(stuck_sessions) if stuck_sessions else 0
            }
    
    def auto_recovery(self, max_stuck_minutes: int = 30) -> Dict[str, Any]:
        """
        🚑 AUTO RECOVERY: Tự động phục hồi hệ thống từ trạng thái lỗi
        
        Thực hiện các actions:
        1. Release stuck sessions
        2. Process cooldowns
        3. Return health status
        
        Args:
            max_stuck_minutes: Số phút để coi session là stuck
            
        Returns:
            Dict với kết quả recovery
        """
        logger.info("🚑 Starting auto-recovery process...")
        
        # Step 1: Release stuck sessions
        released = self.auto_cleanup_stuck_sessions(timeout_minutes=max_stuck_minutes)
        
        # Step 2: Process cooldowns
        cooldown_released = self.check_cooldowns()
        
        # Step 3: Get health status
        health = self.health_check_sessions()
        
        recovery_result = {
            "timestamp": datetime.now().isoformat(),
            "actions_taken": {
                "stuck_sessions_released": released,
                "cooldowns_processed": cooldown_released
            },
            "health_after_recovery": health
        }
        
        if released > 0 or cooldown_released > 0:
            logger.info(
                f"✅ Auto-recovery completed: "
                f"Released {released} stuck sessions, "
                f"Processed {cooldown_released} cooldowns"
            )
        else:
            logger.info("✅ Auto-recovery completed: No actions needed")
        
        return recovery_result


# Test functions
def test_session_manager():
    """Test cơ bản cho SessionManager"""
    logger.info("🧪 Testing SessionManager...")
    
    # Test với temporary files
    test_status_file = "test_session_status.json"
    test_sessions_dir = "test_sessions"
    
    try:
        # Create test environment
        os.makedirs(test_sessions_dir, exist_ok=True)
        
        # Tạo một session folder giả
        test_session_path = os.path.join(test_sessions_dir, "test_account")
        os.makedirs(test_session_path, exist_ok=True)
        os.makedirs(os.path.join(test_session_path, "Default"), exist_ok=True)
        
        with open(os.path.join(test_session_path, "Local State"), 'w') as f:
            f.write('{"test": "data"}')
        
        # Test SessionManager
        manager = SessionManager(test_status_file, test_sessions_dir)
        
        # Test checkout
        session = manager.checkout_session(timeout=5)
        print(f"✅ Checkout session: {session}")
        
        # Test stats
        stats = manager.get_stats()
        print(f"✅ Stats: {stats}")
        
        # Test checkin
        if session:
            manager.checkin_session(session)
            print(f"✅ Checkin session: {session}")
        
        print("✅ SessionManager test completed!")
        
    finally:
        # Cleanup
        try:
            import shutil
            if os.path.exists(test_sessions_dir):
                shutil.rmtree(test_sessions_dir)
            if os.path.exists(test_status_file):
                os.remove(test_status_file)
        except (OSError, FileNotFoundError):
            pass


if __name__ == "__main__":
    # Test session manager with centralized logging
    from logging_config import setup_application_logging
    setup_application_logging()
    
    # Get debug logger for testing
    test_logger = get_logger(__name__, level="DEBUG")
    
    test_session_manager()
