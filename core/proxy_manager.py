#!/usr/bin/env python3
"""
Proxy Manager for Facebook Post Monitor - Enterprise Edition Phase 3.1
Quản lý pool proxy để mỗi worker sử dụng proxy riêng biệt

Mục đích:
- Quản lý pool các proxy servers đã cấu hình
- Thread-safe checkout/checkin proxies
- Tránh multiple workers sử dụng cùng proxy (tránh bị phát hiện)
- Rotation và health checking cho proxies
- Tái sử dụng pattern từ SessionManager (đã proven và hoàn thiện)
"""

import json
import os
import threading
import time
import asyncio
import requests
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
    
    def __init__(self, proxy_file: str = "proxies.txt", status_file: str = "proxy_status.json"):
        """
        Khởi tạo ProxyManager với cross-process file locking
        
        Args:
            proxy_file: File chứa danh sách proxy (format: ip:port:user:pass hoặc ip:port)
            status_file: File JSON theo dõi trạng thái proxies
        """
        self.proxy_file = proxy_file
        self.status_file = status_file
        self.lock = threading.Lock()  # Thread-safe access
        
        # Performance thresholds for intelligent proxy management
        self.consecutive_failure_threshold = 3  # Lower than sessions
        self.success_rate_threshold = 0.7  # Higher than sessions (proxies need to be reliable)
        self.min_tasks_for_rate_calc = 5  # Lower threshold for faster quarantine
        self.quarantine_duration_minutes = 30  # Shorter quarantine for proxies
        self.health_check_interval_minutes = 15
        
        # Proxy pool (in-memory cache) using ManagedResource
        self.resource_pool: Dict[str, ManagedResource] = {}
        
        # Last health check timestamp
        self.last_health_check = None
        
        # Cross-process file locking (same pattern as SessionManager)
        if FILELOCK_AVAILABLE:
            self.file_lock_path = self.status_file + ".lock"
            self.file_lock = FileLock(self.file_lock_path)
            logger.info("🔒 Cross-process file locking enabled for proxies")
        else:
            self.file_lock = None
            logger.warning("⚠️ FileLock not available - only thread-safe within process")
        
        # Ensure files exist and load resources
        self._ensure_structure()
        self._load_resources_to_memory()
        
        logger.info(f"🔐 ProxyManager khởi tạo: {proxy_file} -> {status_file}")
    
    def _load_resources_to_memory(self):
        """Load tất cả proxy resources từ file vào memory cache."""
        status_data = self._read_status_file()
        self.resource_pool.clear()
        
        for resource_id, resource_data in status_data.items():
            try:
                resource = ManagedResource.from_dict(resource_data)
                # Ensure it's marked as proxy type
                resource.type = "proxy"
                self.resource_pool[resource_id] = resource
            except Exception as e:
                logger.warning(f"⚠️ Lỗi load proxy resource {resource_id}: {e}")
                # Fallback to basic resource
                resource = ManagedResource(resource_id, "proxy")
                if isinstance(resource_data, dict):
                    resource.status = resource_data.get("status", "DISABLED")
                    if "config" in resource_data:
                        resource.metadata["config"] = resource_data["config"]
                self.resource_pool[resource_id] = resource
        
        logger.info(f"📋 Loaded {len(self.resource_pool)} proxy resources to memory")
    
    def _sync_resources_to_file(self):
        """Sync in-memory proxy resources back to file."""
        status_data = {}
        for resource_id, resource in self.resource_pool.items():
            status_data[resource_id] = resource.to_dict()
        self._write_status_file(status_data)
    
    def _process_cooldowns(self):
        """Process quarantined proxies and release those past cooldown period."""
        current_time = datetime.now()
        
        for resource in self.resource_pool.values():
            if resource.status == "QUARANTINED" and resource.quarantine_until_timestamp:
                if current_time >= resource.quarantine_until_timestamp:
                    resource.status = "READY"
                    resource.quarantine_until_timestamp = None
                    resource.consecutive_failures = 0  # Reset failures after cooldown
                    logger.info(f"🎆 Proxy {resource.id} released from quarantine")
    
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
        
        for resource in candidates:
            try:
                resource.status = "TESTING"
                proxy_config = resource.metadata.get("config")
                if proxy_config:
                    is_healthy = self.health_check_proxy({**proxy_config, "proxy_id": resource.id})
                    if is_healthy:
                        resource.status = "READY"
                        logger.debug(f"✅ Health check passed for proxy {resource.id}")
                    else:
                        resource.status = "FAILED"
                        resource.consecutive_failures += 1
                        logger.warning(f"❌ Health check failed for proxy {resource.id}")
            except Exception as e:
                logger.error(f"❌ Health check error for proxy {resource.id}: {e}")
                resource.status = "FAILED"
    
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
        
        logger.debug(f"📊 Proxy stats: {stats}")
    
    def _ensure_structure(self):
        """Đảm bảo cấu trúc file proxy tồn tại (tương tự SessionManager)"""
        
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
        
        # Tạo status file nếu chưa có
        if not os.path.exists(self.status_file):
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
        """Load danh sách proxy từ file cấu hình"""
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
                    logger.warning(f"⚠️ Invalid proxy format at line {line_num}: {line}")
            
            logger.info(f"📋 Loaded {len(proxies)} proxies from {self.proxy_file}")
            return proxies
            
        except Exception as e:
            logger.error(f"❌ Lỗi load proxy file: {e}")
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
        """Đọc proxy status từ file (thread-safe) - tương tự SessionManager"""
        try:
            with open(self.status_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"❌ Lỗi đọc proxy status: {e}")
            return {}
    
    def _write_status_file(self, status_data: Dict[str, Any]):
        """Ghi proxy status vào file (thread-safe) - tương tự SessionManager"""
        try:
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(status_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"❌ Lỗi ghi proxy status: {e}")
            raise
    
    def checkout_proxy(self, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """
        Intelligent proxy checkout với performance-based selection
        
        ⚠️ DEPRECATED: Use SessionManager.checkout_session_with_proxy() for production
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
                            self._sync_resources_to_file()
                            return result
                else:
                    result = self._intelligent_checkout()
                    if result:
                        self._sync_resources_to_file()
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
                    logger.warning(f"⚠️ Proxy config invalid: {resource_id}")
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
            
            logger.info(f"🎯 Intelligently selected proxy: {selected.id} (success_rate: {selected.success_rate:.2f})")
            return proxy_config
        
        except Exception as e:
            logger.error(f"❌ Lỗi intelligent proxy checkout: {e}")
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
            logger.warning("⚠️ Proxy config thiếu proxy_id, không thể checkin")
            return
        
        with self.lock:
            if self.file_lock:
                with self.file_lock:
                    self._intelligent_checkin(proxy_id, status)
                    self._sync_resources_to_file()
            else:
                self._intelligent_checkin(proxy_id, status)
                self._sync_resources_to_file()
    
    def _intelligent_checkin(self, proxy_id: str, status: str):
        """Intelligent checkin với performance tracking."""
        try:
            if proxy_id not in self.resource_pool:
                logger.warning(f"⚠️ Proxy không tồn tại: {proxy_id}")
                return
            
            resource = self.resource_pool[proxy_id]
            old_status = resource.status
            resource.status = status
            
            logger.info(f"🔓 Checked in proxy: {proxy_id} ({old_status} → {status})")
            
        except Exception as e:
            logger.error(f"❌ Lỗi intelligent checkin proxy {proxy_id}: {e}")
    
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
                logger.warning(f"⚠️ Proxy {proxy_id} failed connectivity test, skipping")
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
            logger.info(f"✅ Validated and converted proxy for Playwright: {proxy_id}")
            return playwright_proxy

        except Exception as e:
            logger.error(f"❌ Lỗi convert proxy cho Playwright: {e}")
            return None
    
    def health_check_proxy(self, proxy_config: Dict[str, Any]) -> bool:
        """
        Enhanced health check với response time tracking
        
        Args:
            proxy_config: Config dict của proxy
            
        Returns:
            True nếu proxy hoạt động tốt, False nếu có vấn đề
        """
        proxy_id = proxy_config.get("proxy_id")
        
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
            
            # Test với httpbin.org
            start_time = time.time()
            response = session.get("http://httpbin.org/ip", timeout=10)
            response_time = time.time() - start_time
            
            # Update response time in metadata
            if proxy_id and proxy_id in self.resource_pool:
                self.resource_pool[proxy_id].metadata["response_time"] = response_time
                self.resource_pool[proxy_id].metadata["last_checked"] = datetime.now().isoformat()
            
            if response.status_code == 200:
                logger.debug(f"✅ Proxy health check OK: {proxy_id} ({response_time:.2f}s)")
                return True
            else:
                logger.warning(f"⚠️ Proxy health check failed: {proxy_id} - Status {response.status_code}")
                return False
                
        except Exception as e:
            logger.warning(f"⚠️ Proxy health check error: {proxy_id} - {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Lấy thống kê chi tiết về proxies và performance."""
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
        """Đánh dấu proxy bị lỗi và update performance metrics."""
        proxy_id = proxy_config.get("proxy_id")
        if proxy_id:
            logger.warning(f"❌ Marking proxy failed: {proxy_id} - {reason}")
            # Report failure for performance tracking
            self.report_outcome(proxy_id, 'failure', {'reason': reason})
            # Check in with FAILED status if not quarantined
            if proxy_id in self.resource_pool and not self.resource_pool[proxy_id].is_quarantined():
                self.checkin_proxy(proxy_config, "FAILED")
    
    def reset_all_proxies(self):
        """Reset tất cả proxies về trạng thái READY (debug only)"""
        with self.lock:
            for resource in self.resource_pool.values():
                resource.status = "READY"
                resource.consecutive_failures = 0
                resource.quarantine_until_timestamp = None
                resource.quarantine_reason = None
            
            if self.file_lock:
                with self.file_lock:
                    self._sync_resources_to_file()
            else:
                self._sync_resources_to_file()
            
            logger.info("🔄 Reset tất cả proxies về READY")
    
    def report_outcome(self, proxy_id: str, outcome: str, details: Dict[str, Any] = None):
        """
        Báo cáo kết quả task để cập nhật performance metrics cho proxy
        
        Args:
            proxy_id: ID của proxy
            outcome: 'success' hoặc 'failure'
            details: Thông tin chi tiết về task (có thể chứa response_time)
        """
        with self.lock:
            if proxy_id not in self.resource_pool:
                logger.warning(f"⚠️ Proxy không tồn tại để report outcome: {proxy_id}")
                return
            
            resource = self.resource_pool[proxy_id]
            resource.total_tasks += 1
            
            if outcome == 'success':
                resource.successful_tasks += 1
                resource.consecutive_failures = 0
                
                # Update response time if provided
                if details and 'response_time' in details:
                    resource.metadata["response_time"] = details['response_time']
                
                logger.debug(f"✅ Success reported for proxy {proxy_id}")
            elif outcome == 'failure':
                resource.consecutive_failures += 1
                logger.debug(f"❌ Failure reported for proxy {proxy_id} (consecutive: {resource.consecutive_failures})")
            
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
            if self.file_lock:
                with self.file_lock:
                    self._sync_resources_to_file()
            else:
                self._sync_resources_to_file()
    
    def quarantine_resource(self, proxy_id: str, reason: str = "Performance issues"):
        """
        Cách ly proxy vào quarantine với cooldown period
        
        Args:
            proxy_id: ID của proxy
            reason: Lý do cách ly
        """
        with self.lock:
            if proxy_id not in self.resource_pool:
                logger.warning(f"⚠️ Proxy không tồn tại để quarantine: {proxy_id}")
                return
            
            resource = self.resource_pool[proxy_id]
            resource.status = "QUARANTINED"
            resource.quarantine_reason = reason
            resource.quarantine_count += 1
            resource.quarantine_until_timestamp = datetime.now() + timedelta(minutes=self.quarantine_duration_minutes)
            
            logger.warning(f"🚨 Proxy {proxy_id} quarantined until {resource.quarantine_until_timestamp.strftime('%H:%M:%S')} - {reason}")
            
            # Sync to file
            if self.file_lock:
                with self.file_lock:
                    self._sync_resources_to_file()
            else:
                self._sync_resources_to_file()
    
    def get_proxy_performance(self, proxy_id: str) -> Optional[Dict[str, Any]]:
        """
        Lấy performance metrics của một proxy cụ thể
        
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
    
    def check_cooldowns(self):
        """
        Public method để kiểm tra và xử lý cooldowns (có thể gọi từ scheduler)
        """
        with self.lock:
            self._process_cooldowns()
            if self.file_lock:
                with self.file_lock:
                    self._sync_resources_to_file()
            else:
                self._sync_resources_to_file()


    def run_comprehensive_health_check(self):
        """
        Chạy health check toàn diện cho tất cả proxies (sử dụng cho maintenance)
        """
        logger.info("🛠️ Bắt đầu comprehensive health check cho tất cả proxies")
        
        with self.lock:
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
            if self.file_lock:
                with self.file_lock:
                    self._sync_resources_to_file()
            else:
                self._sync_resources_to_file()
            
            logger.info(f"✅ Comprehensive health check hoàn thành: {healthy_count}/{checked_count} proxies healthy")
            
            return {
                "checked_count": checked_count,
                "healthy_count": healthy_count,
                "unhealthy_count": checked_count - healthy_count
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
        print(f"✅ Checkout proxy: {proxy}")
        
        # Test stats
        stats = manager.get_stats()
        print(f"✅ Stats: {stats}")
        
        # Test checkin
        if proxy:
            manager.checkin_proxy(proxy)
            print(f"✅ Checkin proxy: {proxy.get('proxy_id')}")
        
        print("✅ ProxyManager test completed!")
        
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
