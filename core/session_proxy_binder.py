#!/usr/bin/env python3
"""
Session-Proxy Binding Manager
🔒 Đảm bảo mỗi session Facebook chỉ dùng 1 proxy cố định

Mục đích:
- Bind cố định session với proxy để tránh bị phát hiện
- Track session-proxy mapping trong persistent storage
- Automatic proxy assignment khi session được checkout
- Consistent proxy cho cùng session qua nhiều lần restart
"""

import json
import os
import threading
import hashlib
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple

try:
    from logging_config import get_logger
except ImportError:
    import logging
    def get_logger(name):
        return logging.getLogger(name)

# Cross-process file locking
try:
    from filelock import FileLock
    FILELOCK_AVAILABLE = True
except ImportError:
    FILELOCK_AVAILABLE = False
    FileLock = None

logger = get_logger(__name__)


class SessionProxyBinder:
    """
    Manager để bind cố định session với proxy

    Features:
    - Persistent session-proxy mapping
    - Automatic proxy assignment cho session mới
    - Thread-safe operations với file locking
    - Proxy rotation chỉ khi proxy fail hoàn toàn
    """

    def __init__(self, binding_file: str = "session_proxy_bindings.json"):
        """
        Khởi tạo SessionProxyBinder

        Args:
            binding_file: File JSON lưu trữ session-proxy mappings
        """
        self.binding_file = binding_file
        self.lock = threading.Lock()

        # Cross-process file locking
        if FILELOCK_AVAILABLE:
            self.file_lock_path = self.binding_file + ".lock"
            self.file_lock = FileLock(self.file_lock_path)
            logger.info("🔒 Cross-process file locking enabled for session-proxy bindings")
        else:
            self.file_lock = None
            logger.warning("⚠️ FileLock not available - only thread-safe within process")

        # In-memory cache của bindings
        self.bindings_cache: Dict[str, str] = {}

        # Ensure file structure exists
        self._ensure_structure()
        self._load_bindings_to_memory()

        logger.info(f"🔗 SessionProxyBinder initialized: {binding_file}")

    def _ensure_structure(self):
        """Đảm bảo binding file tồn tại"""
        if not os.path.exists(self.binding_file):
            initial_bindings = {
                "_metadata": {
                    "created": datetime.now().isoformat(),
                    "version": "1.0",
                    "description": "Session-Proxy bindings for consistent Facebook scraping"
                },
                "bindings": {}
            }
            self._write_bindings_file(initial_bindings)
            logger.info(f"📄 Created binding file template: {self.binding_file}")

    def _load_bindings_to_memory(self):
        """Load bindings từ file vào memory cache"""
        try:
            data = self._read_bindings_file()
            self.bindings_cache = data.get("bindings", {})
            logger.info(f"📥 Loaded {len(self.bindings_cache)} session-proxy bindings to memory")
        except Exception as e:
            logger.error(f"❌ Error loading bindings to memory: {e}")
            self.bindings_cache = {}

    def _sync_bindings_to_file(self):
        """Sync memory cache back to file"""
        try:
            data = self._read_bindings_file()
            data["bindings"] = self.bindings_cache.copy()
            data["_metadata"]["last_updated"] = datetime.now().isoformat()
            self._write_bindings_file(data)
        except Exception as e:
            logger.error(f"❌ Error syncing bindings to file: {e}")

    def _read_bindings_file(self) -> Dict[str, Any]:
        """Đọc binding file (thread-safe)"""
        try:
            with open(self.binding_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"❌ Error reading binding file: {e}")
            return {"bindings": {}}

    def _write_bindings_file(self, data: Dict[str, Any]):
        """Ghi binding file (thread-safe)"""
        try:
            with open(self.binding_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"❌ Error writing binding file: {e}")
            raise

    def get_proxy_for_session(self, session_name: str, available_proxies: List[str]) -> Optional[str]:
        """
        Lấy proxy được bind với session, hoặc assign proxy mới

        Args:
            session_name: Tên của session
            available_proxies: List các proxy ID có sẵn từ ProxyManager

        Returns:
            Proxy ID được bind với session, None nếu không có proxy available
        """
        with self.lock:
            if self.file_lock:
                with self.file_lock:
                    return self._get_or_assign_proxy(session_name, available_proxies)
            else:
                return self._get_or_assign_proxy(session_name, available_proxies)

    def _get_or_assign_proxy(self, session_name: str, available_proxies: List[str]) -> Optional[str]:
        """Internal method để get hoặc assign proxy"""
        try:
            # Check nếu session đã có proxy được bind
            existing_proxy = self.bindings_cache.get(session_name)

            if existing_proxy and existing_proxy in available_proxies:
                logger.info(f"🔗 Using existing binding: {session_name} -> {existing_proxy}")
                return existing_proxy

            if existing_proxy and existing_proxy not in available_proxies:
                logger.warning(f"⚠️ Bound proxy {existing_proxy} not available for session {session_name}")

            # Assign proxy mới nếu chưa có binding hoặc proxy cũ không available
            if not available_proxies:
                logger.warning(f"⚠️ No available proxies to bind with session {session_name}")
                return None

            # Chọn proxy chưa được bind với session khác (nếu có)
            unbound_proxies = []
            for proxy_id in available_proxies:
                if proxy_id not in self.bindings_cache.values():
                    unbound_proxies.append(proxy_id)

            # Ưu tiên proxy chưa bind, fallback to any available
            target_proxies = unbound_proxies if unbound_proxies else available_proxies

            # Deterministic selection based on session name hash
            session_hash = hashlib.md5(session_name.encode()).hexdigest()
            proxy_index = int(session_hash[:8], 16) % len(target_proxies)
            selected_proxy = target_proxies[proxy_index]

            # Create binding
            self.bindings_cache[session_name] = selected_proxy
            self._sync_bindings_to_file()

            logger.info(f"🔗 New binding created: {session_name} -> {selected_proxy}")
            return selected_proxy

        except Exception as e:
            logger.error(f"❌ Error in proxy assignment: {e}")
            return None

    def unbind_session(self, session_name: str):
        """
        Hủy bind giữa session và proxy

        Args:
            session_name: Tên session cần unbind
        """
        with self.lock:
            if self.file_lock:
                with self.file_lock:
                    self._unbind_session_internal(session_name)
            else:
                self._unbind_session_internal(session_name)

    def _unbind_session_internal(self, session_name: str):
        """Internal unbind method"""
        try:
            if session_name in self.bindings_cache:
                old_proxy = self.bindings_cache.pop(session_name)
                self._sync_bindings_to_file()
                logger.info(f"🔓 Unbound session: {session_name} from proxy {old_proxy}")
            else:
                logger.debug(f"Session {session_name} was not bound to any proxy")
        except Exception as e:
            logger.error(f"❌ Error unbinding session {session_name}: {e}")

    def rebind_session_to_new_proxy(self, session_name: str, new_proxy_id: str):
        """
        Force rebind session to new proxy (khi proxy cũ bị fail)

        Args:
            session_name: Tên session
            new_proxy_id: ID của proxy mới
        """
        with self.lock:
            if self.file_lock:
                with self.file_lock:
                    self._rebind_session_internal(session_name, new_proxy_id)
            else:
                self._rebind_session_internal(session_name, new_proxy_id)

    def _rebind_session_internal(self, session_name: str, new_proxy_id: str):
        """Internal rebind method"""
        try:
            old_proxy = self.bindings_cache.get(session_name)
            self.bindings_cache[session_name] = new_proxy_id
            self._sync_bindings_to_file()

            if old_proxy:
                logger.info(f"🔄 Rebound session: {session_name} from {old_proxy} to {new_proxy_id}")
            else:
                logger.info(f"🔗 Bound session: {session_name} to {new_proxy_id}")

        except Exception as e:
            logger.error(f"❌ Error rebinding session {session_name} to {new_proxy_id}: {e}")

    def get_session_for_proxy(self, proxy_id: str) -> Optional[str]:
        """
        Lấy session đang bind với proxy

        Args:
            proxy_id: ID của proxy

        Returns:
            Session name nếu có, None nếu proxy chưa được bind
        """
        with self.lock:
            for session_name, bound_proxy in self.bindings_cache.items():
                if bound_proxy == proxy_id:
                    return session_name
            return None

    def get_all_bindings(self) -> Dict[str, str]:
        """Lấy tất cả bindings hiện tại"""
        with self.lock:
            return self.bindings_cache.copy()

    def get_binding_stats(self) -> Dict[str, Any]:
        """Lấy thống kê về bindings"""
        with self.lock:
            unique_proxies = set(self.bindings_cache.values())
            return {
                "total_bindings": len(self.bindings_cache),
                "unique_proxies_used": len(unique_proxies),
                "sessions_per_proxy": len(self.bindings_cache) / max(len(unique_proxies), 1),
                "bindings": self.bindings_cache.copy()
            }

    def cleanup_invalid_bindings(self, valid_sessions: List[str], valid_proxies: List[str]):
        """
        Cleanup bindings không hợp lệ

        Args:
            valid_sessions: List sessions hợp lệ
            valid_proxies: List proxies hợp lệ
        """
        with self.lock:
            if self.file_lock:
                with self.file_lock:
                    self._cleanup_bindings_internal(valid_sessions, valid_proxies)
            else:
                self._cleanup_bindings_internal(valid_sessions, valid_proxies)

    def _cleanup_bindings_internal(self, valid_sessions: List[str], valid_proxies: List[str]):
        """Internal cleanup method"""
        try:
            cleaned_bindings = {}
            removed_count = 0

            for session_name, proxy_id in self.bindings_cache.items():
                if session_name in valid_sessions and proxy_id in valid_proxies:
                    cleaned_bindings[session_name] = proxy_id
                else:
                    removed_count += 1
                    logger.debug(f"Removing invalid binding: {session_name} -> {proxy_id}")

            self.bindings_cache = cleaned_bindings
            if removed_count > 0:
                self._sync_bindings_to_file()
                logger.info(f"🧹 Cleaned up {removed_count} invalid bindings")

        except Exception as e:
            logger.error(f"❌ Error during binding cleanup: {e}")


# Test function
def test_session_proxy_binder():
    """Test SessionProxyBinder functionality"""
    logger.info("🧪 Testing SessionProxyBinder...")

    test_binding_file = "test_bindings.json"

    try:
        # Create binder
        binder = SessionProxyBinder(test_binding_file)

        # Test proxy assignment
        available_proxies = ["proxy_1", "proxy_2", "proxy_3"]

        proxy1 = binder.get_proxy_for_session("session_A", available_proxies)
        proxy2 = binder.get_proxy_for_session("session_B", available_proxies)
        proxy3 = binder.get_proxy_for_session("session_A", available_proxies)  # Should be same as proxy1

        print(f"OK Session A -> {proxy1}")
        print(f"OK Session B -> {proxy2}")
        print(f"OK Session A (again) -> {proxy3}")

        assert proxy1 == proxy3, "Session A should get same proxy"
        assert proxy1 != proxy2, "Different sessions should get different proxies"

        # Test stats
        stats = binder.get_binding_stats()
        print(f"OK Stats: {stats}")

        # Test rebind
        binder.rebind_session_to_new_proxy("session_A", "proxy_3")
        new_proxy = binder.get_proxy_for_session("session_A", available_proxies)
        print(f"OK Session A rebound -> {new_proxy}")

        print("OK SessionProxyBinder test completed!")

    finally:
        # Cleanup
        try:
            if os.path.exists(test_binding_file):
                os.remove(test_binding_file)
            if os.path.exists(test_binding_file + ".lock"):
                os.remove(test_binding_file + ".lock")
        except OSError:
            pass


if __name__ == "__main__":
    try:
        from logging_config import setup_application_logging
        setup_application_logging()
    except ImportError:
        import logging
        logging.basicConfig(level=logging.INFO)

    test_session_proxy_binder()