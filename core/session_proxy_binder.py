#!/usr/bin/env python3
"""
Session-Proxy Binding Manager
[LOCK] Đảm bảo mỗi session Facebook chỉ dùng 1 proxy cố định

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

    def __init__(self, binding_file: str = "session_proxy_bindings.json", db_manager=None):
        """
        Initialize SessionProxyBinder

        Args:
            binding_file: File JSON lưu trữ session-proxy mappings
            db_manager: DatabaseManager instance for migration (optional)
        """
        self.binding_file = binding_file
        self.lock = threading.Lock()
        
        # Database manager for migration
        if db_manager is None:
            from core.database_manager import DatabaseManager
            self.db = DatabaseManager()
        else:
            self.db = db_manager

        # Cross-process file locking
        if FILELOCK_AVAILABLE:
            self.file_lock_path = self.binding_file + ".lock"
            self.file_lock = FileLock(self.file_lock_path)
            logger.info("[LOCK] Cross-process file locking enabled for session-proxy bindings")
        else:
            self.file_lock = None
            logger.warning("[WARN] FileLock not available - only thread-safe within process")

        # In-memory cache của bindings
        self.bindings_cache: Dict[str, str] = {}

        # Ensure file structure exists
        self._ensure_structure()
        self._load_bindings_to_memory()

        logger.info(f"🔗 SessionProxyBinder initialized: {binding_file}")

    def _ensure_structure(self):
        """Đảm bảo binding file exists"""
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
        """
        Load bindings từ file vào memory cache
        
        ✅ FIX: Auto-migrate old database IDs (proxy_X) to stable identifiers (host:port)
        
        ⚠️ CRITICAL: Must be called INSIDE locks() context to prevent race conditions!
        Caller MUST wrap this with: with self.locks():
        """
        try:
            data = self._read_bindings_file()
            raw_bindings = data.get("bindings", {})
            
            # ✅ MIGRATION: Convert old proxy_X format to host:port format
            migrated_bindings = {}
            migration_count = 0
            
            for session_name, proxy_id in raw_bindings.items():
                # Check if proxy_id is old format (proxy_1, proxy_2, etc.)
                if proxy_id.startswith("proxy_"):
                    try:
                        # Extract database ID
                        db_id = int(proxy_id.split("_")[1])
                        
                        # Query database for proxy info
                        proxies = self.db.get_all_proxies()
                        matching_proxy = None
                        for p in proxies:
                            if p['id'] == db_id:
                                matching_proxy = p
                                break
                        
                        if matching_proxy:
                            # Migrate to host:port format
                            new_proxy_id = f"{matching_proxy['host']}:{matching_proxy['port']}"
                            migrated_bindings[session_name] = new_proxy_id
                            migration_count += 1
                            logger.info(f"[MIGRATE] Session {session_name}: {proxy_id} → {new_proxy_id}")
                        else:
                            # Proxy not found in DB - skip binding (will be rejected during checkout)
                            logger.warning(f"[MIGRATE] Session {session_name}: {proxy_id} not found in database - REMOVING binding")
                    except (ValueError, IndexError, KeyError) as e:
                        logger.error(f"[MIGRATE] Failed to migrate {session_name}: {proxy_id} - {e}")
                        # Keep old binding for manual review
                        migrated_bindings[session_name] = proxy_id
                else:
                    # Already in host:port format or custom format - keep as is
                    migrated_bindings[session_name] = proxy_id
            
            self.bindings_cache = migrated_bindings
            
            if migration_count > 0:
                logger.info(f"✅ [MIGRATE] Migrated {migration_count} bindings from proxy_X to host:port format")
                # Auto-save migrated bindings
                self._sync_bindings_to_file()
            
            logger.info(f"📥 Loaded {len(self.bindings_cache)} session-proxy bindings to memory")
        except Exception as e:
            logger.error(f"[ERROR] Error loading bindings to memory: {e}")
            self.bindings_cache = {}

    def _sync_bindings_to_file(self):
        """
        Sync memory cache back to file
        
        ⚠️ CRITICAL: Must be called INSIDE locks() context to prevent race conditions!
        Caller MUST wrap this with: with self.locks():
        """
        try:
            data = self._read_bindings_file()
            
            # ✅ FIX: Ensure _metadata exists (defensive programming)
            if "_metadata" not in data:
                data["_metadata"] = {
                    "created": datetime.now().isoformat(),
                    "version": "1.0",
                    "description": "Session-Proxy bindings for consistent Facebook scraping"
                }
            
            data["bindings"] = self.bindings_cache.copy()
            data["_metadata"]["last_updated"] = datetime.now().isoformat()
            self._write_bindings_file(data)
        except Exception as e:
            logger.error(f"[ERROR] Error syncing bindings to file: {e}")

    def _read_bindings_file(self) -> Dict[str, Any]:
        """Đọc binding file (thread-safe)"""
        try:
            with open(self.binding_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"[ERROR] Error reading binding file: {e}")
            return {"bindings": {}}

    def _write_bindings_file(self, data: Dict[str, Any]):
        """Ghi binding file (thread-safe)"""
        try:
            with open(self.binding_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[ERROR] Error writing binding file: {e}")
            raise

    def locks(self):
        """
        Context manager for unified lock handling (thread + cross-process).
        
        Usage:
            with binder.locks():
                # ... modify bindings_cache ...
                # ... sync to file ...
        """
        from contextlib import contextmanager
        
        @contextmanager
        def _locks_impl():
            with self.lock:
                if self.file_lock:
                    with self.file_lock:
                        yield
                else:
                    yield
        
        return _locks_impl()

    def bind_session_atomic(self, session_name: str, proxy_id: str) -> bool:
        """
        ✅ ATOMIC: Bind session to proxy with full lock protection
        
        Use this method from external callers (like auto_login.py) to ensure
        thread-safe and cross-process-safe binding operations.
        
        Args:
            session_name: Name of session
            proxy_id: ID of proxy to bind
            
        Returns:
            True if binding successful, False otherwise
        """
        try:
            with self.locks():
                # Reload from file to get latest state
                self._load_bindings_to_memory()
                
                # Update binding
                old_proxy = self.bindings_cache.get(session_name)
                self.bindings_cache[session_name] = proxy_id
                
                # Sync back to file (still inside lock)
                self._sync_bindings_to_file()
                
                if old_proxy and old_proxy != proxy_id:
                    logger.info(f"🔄 Rebound session: {session_name} ({old_proxy} → {proxy_id})")
                else:
                    logger.info(f"🔗 Bound session: {session_name} → {proxy_id}")
                
                return True
                
        except Exception as e:
            logger.error(f"[ERROR] Failed to bind session {session_name} to {proxy_id}: {e}")
            return False

    def get_proxy_for_session(self, session_name: str, available_proxies: List[str]) -> Optional[str]:
        """
        Lấy proxy được bind với session, hoặc assign proxy mới

        Args:
            session_name: Tên của session
            available_proxies: List các proxy ID có sẵn từ ProxyManager

        Returns:
            Proxy ID được bind với session, None nếu không có proxy available
        """
        with self.locks():
            # ✅ FIX: Reload from file to get latest bindings from other processes
            self._load_bindings_to_memory()
            return self._get_or_assign_proxy(session_name, available_proxies)

    def _get_or_assign_proxy(self, session_name: str, available_proxies: List[str]) -> Optional[str]:
        """
        [OK] PERMANENT BINDING - NEVER reassign proxy once bound!
        
        Policy:
        - If session has binding + proxy available → USE IT
        - If session has binding + proxy unavailable → SKIP SESSION (return None)
        - If session has NO binding → assign new proxy (first-time only)
        """
        try:
            # Check nếu session done: có proxy được bind
            existing_proxy = self.bindings_cache.get(session_name)

            # [OK] Check if session is PERMANENT_QUARANTINE
            # (Do this before checking proxy, as session might be quarantined)
            
            if existing_proxy and existing_proxy in available_proxies:
                logger.info(f"🔗 Using existing binding: {session_name} -> {existing_proxy}")
                return existing_proxy

            if existing_proxy and existing_proxy not in available_proxies:
                # [LOCK] CRITICAL: NEVER reassign! Proxy unavailable → SKIP this session
                logger.error(f"[STOP] PERMANENT BINDING: {session_name} → {existing_proxy} (UNAVAILABLE)")
                logger.warning(f"[PAUSE] Skipping session {session_name} - proxy {existing_proxy} not ready. Will retry later.")
                
                # [OK] Return None → Session will NOT scrape until proxy recovers
                return None

            # [LOCK] STRICT POLICY: NO AUTO-ASSIGNMENT!
            # Nếu session KHÔNG CÓ binding → REJECT (không tự động assign)
            logger.error(f"[STOP] REJECTED: Session {session_name} has NO pre-configured binding!")
            logger.warning(f"[TIP] Only sessions in session_proxy_bindings.json are allowed to scrape.")
            logger.warning(f"[TIP] To use this session, manually add it to session_proxy_bindings.json")
            
            # Return None → Session will be REJECTED from scraping
            return None

        except Exception as e:
            logger.error(f"[ERROR] Error in proxy assignment: {e}")
            return None

    def unbind_session(self, session_name: str):
        """
        [LOCK] DISABLED - PERMANENT BINDING POLICY
        
        Unbinding is NOT ALLOWED to maintain stable session-proxy pairs.
        This prevents IP changes that cause Facebook logout.
        """
        logger.error(f"[STOP] REJECTED: unbind_session() is DISABLED by permanent binding policy!")
        logger.warning(f"[TIP] Session {session_name} will remain bound to its proxy forever")
        return  # Do nothing

    def _unbind_session_internal(self, session_name: str):
        """Internal unbind method"""
        try:
            if session_name in self.bindings_cache:
                old_proxy = self.bindings_cache.pop(session_name)
                self._sync_bindings_to_file()
                logger.info(f"[UNLOCK] Unbound session: {session_name} from proxy {old_proxy}")
            else:
                logger.debug(f"Session {session_name} was not bound to any proxy")
        except Exception as e:
            logger.error(f"[ERROR] Error unbinding session {session_name}: {e}")

    def rebind_session_to_new_proxy(self, session_name: str, new_proxy_id: str):
        """
        [LOCK] DISABLED - PERMANENT BINDING POLICY
        
        Rebinding is NOT ALLOWED to maintain stable session-proxy pairs.
        Once a session is bound to a proxy, it stays with that proxy FOREVER.
        This prevents IP changes that cause Facebook logout/checkpoint.
        """
        logger.error(f"[STOP] REJECTED: rebind_session_to_new_proxy() is DISABLED!")
        logger.warning(f"[TIP] Session {session_name} cannot be rebound from its original proxy")
        return  # Do nothing

    def _rebind_session_internal(self, session_name: str, new_proxy_id: str):
        """Internal rebind method"""
        try:
            old_proxy = self.bindings_cache.get(session_name)
            self.bindings_cache[session_name] = new_proxy_id
            self._sync_bindings_to_file()

            if old_proxy:
                logger.info(f"[RELOAD] Rebound session: {session_name} from {old_proxy} to {new_proxy_id}")
            else:
                logger.info(f"🔗 Bound session: {session_name} to {new_proxy_id}")

        except Exception as e:
            logger.error(f"[ERROR] Error rebinding session {session_name} to {new_proxy_id}: {e}")

    def get_session_for_proxy(self, proxy_id: str) -> Optional[str]:
        """
        Lấy session đang bind với proxy

        Args:
            proxy_id: ID của proxy

        Returns:
            Session name nếu có, None nếu proxy chưa được bind
        """
        with self.locks():
            # ✅ FIX: Reload to get fresh data (method rarely called, performance OK)
            self._load_bindings_to_memory()
            for session_name, bound_proxy in self.bindings_cache.items():
                if bound_proxy == proxy_id:
                    return session_name
            return None

    def get_all_bindings(self) -> Dict[str, str]:
        """Lấy tất cả bindings hiện tại"""
        with self.locks():
            # ✅ FIX: Reload to get fresh data (method rarely called for display)
            self._load_bindings_to_memory()
            return self.bindings_cache.copy()

    def get_binding_stats(self) -> Dict[str, Any]:
        """Lấy thống kê về bindings"""
        with self.locks():
            # ✅ FIX: Reload to get fresh data (stats should be accurate)
            self._load_bindings_to_memory()
            unique_proxies = set(self.bindings_cache.values())
            return {
                "total_bindings": len(self.bindings_cache),
                "unique_proxies_used": len(unique_proxies),
                "sessions_per_proxy": len(self.bindings_cache) / max(len(unique_proxies), 1),
                "bindings": self.bindings_cache.copy()
            }
    
    def get_valid_pairs_count(self, session_manager, proxy_manager) -> int:
        """
        [OK] SMART: Đếm số VALID session-proxy pairs (cả 2 đều healthy)
        
        Args:
            session_manager: SessionManager instance để check session status
            proxy_manager: ProxyManager instance để check proxy health
            
        Returns:
            Số lượng pairs thật sự sẵn sàng để scrape
        """
        valid_count = 0
        
        with self.locks():
            # ✅ FIX: Reload to get fresh data (important for accurate count)
            self._load_bindings_to_memory()
            for session_name, proxy_id in self.bindings_cache.items():
                # ✅ FIX: Access resource_pool directly (get_session_info/get_proxy_info don't exist)
                # Check 1: Session must be READY
                if session_name not in session_manager.resource_pool:
                    continue
                session_resource = session_manager.resource_pool[session_name]
                if session_resource.status != 'READY':
                    continue
                
                # Check 2: Proxy must be READY
                if proxy_id not in proxy_manager.resource_pool:
                    continue
                proxy_resource = proxy_manager.resource_pool[proxy_id]
                if proxy_resource.status != 'READY':
                    continue
                
                # Check 3: Proxy not quarantined
                if proxy_resource.is_quarantined():
                    continue
                
                # [OK] This pair is VALID!
                valid_count += 1
        
        logger.debug(f"[STATS] Valid session-proxy pairs: {valid_count}/{len(self.bindings_cache)}")
        return valid_count

    def cleanup_invalid_bindings(self, valid_sessions: List[str], valid_proxies: List[str]):
        """
        Cleanup bindings không hợp lệ

        Args:
            valid_sessions: List sessions hợp lệ
            valid_proxies: List proxies hợp lệ
        """
        with self.locks():
            # ✅ FIX: Reload before cleanup to ensure we have latest data
            self._load_bindings_to_memory()
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
                logger.info(f"[CLEAN] Cleaned up {removed_count} invalid bindings")

        except Exception as e:
            logger.error(f"[ERROR] Error during binding cleanup: {e}")


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


def add_binding_cli(session_name: str, proxy_id: str, binding_file: str = "session_proxy_bindings.json") -> bool:
    """
    CLI helper to add a new session-proxy binding

    This function allows adding new bindings without manual JSON editing.
    Use this when setting up new sessions.

    Args:
        session_name: Name of the session folder (e.g., "session_100123456789")
        proxy_id: Proxy identifier in host:port format (e.g., "123.45.67.89:8080")
        binding_file: Path to binding file

    Returns:
        True if binding was added successfully

    Example usage:
        python -c "from core.session_proxy_binder import add_binding_cli; add_binding_cli('session_100123456789', '123.45.67.89:8080')"
    """
    try:
        binder = SessionProxyBinder(binding_file)
        result = binder.bind_session_atomic(session_name, proxy_id)
        if result:
            print(f"✅ Successfully bound: {session_name} → {proxy_id}")
        else:
            print(f"❌ Failed to bind: {session_name} → {proxy_id}")
        return result
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def list_bindings_cli(binding_file: str = "session_proxy_bindings.json") -> None:
    """
    CLI helper to list all current bindings

    Example usage:
        python -c "from core.session_proxy_binder import list_bindings_cli; list_bindings_cli()"
    """
    try:
        binder = SessionProxyBinder(binding_file)
        bindings = binder.get_all_bindings()

        print(f"\n📋 Session-Proxy Bindings ({len(bindings)} total):")
        print("-" * 60)
        for session, proxy in sorted(bindings.items()):
            print(f"  {session} → {proxy}")
        print("-" * 60)
    except Exception as e:
        print(f"❌ Error: {e}")


def auto_assign_unbound_sessions(
    binding_file: str = "session_proxy_bindings.json",
    sessions_dir: str = "sessions"
) -> int:
    """
    CLI helper to auto-assign proxies to sessions that don't have bindings yet.

    This uses round-robin assignment based on available proxies in database.
    Only assigns to sessions that exist in sessions_dir but don't have bindings.

    Args:
        binding_file: Path to binding file
        sessions_dir: Directory containing session folders

    Returns:
        Number of new bindings created

    Example usage:
        python -c "from core.session_proxy_binder import auto_assign_unbound_sessions; auto_assign_unbound_sessions()"
    """
    import os

    try:
        binder = SessionProxyBinder(binding_file)

        # Get existing bindings
        existing_bindings = binder.get_all_bindings()
        bound_sessions = set(existing_bindings.keys())

        # Get available proxies from database
        proxies = binder.db.get_all_proxies()
        if not proxies:
            print("❌ No proxies found in database. Add proxies first.")
            return 0

        proxy_ids = [f"{p['host']}:{p['port']}" for p in proxies if p.get('status') in ('READY', 'IN_USE', None)]
        if not proxy_ids:
            print("❌ No available proxies found.")
            return 0

        # Get unbound sessions from sessions directory
        unbound_sessions = []
        if os.path.exists(sessions_dir):
            for item in os.listdir(sessions_dir):
                session_path = os.path.join(sessions_dir, item)
                if os.path.isdir(session_path) and item not in bound_sessions:
                    # Verify it's a valid session folder
                    if os.path.exists(os.path.join(session_path, "Default")):
                        unbound_sessions.append(item)

        if not unbound_sessions:
            print("✅ All sessions already have bindings.")
            return 0

        # Round-robin assignment
        print(f"\n🔗 Auto-assigning {len(unbound_sessions)} unbound sessions...")
        assigned_count = 0

        for i, session_name in enumerate(unbound_sessions):
            proxy_id = proxy_ids[i % len(proxy_ids)]
            if binder.bind_session_atomic(session_name, proxy_id):
                print(f"  ✅ {session_name} → {proxy_id}")
                assigned_count += 1
            else:
                print(f"  ❌ Failed: {session_name}")

        print(f"\n✅ Assigned {assigned_count}/{len(unbound_sessions)} sessions")
        return assigned_count

    except Exception as e:
        print(f"❌ Error: {e}")
        return 0


if __name__ == "__main__":
    import sys

    try:
        from logging_config import setup_application_logging
        setup_application_logging()
    except ImportError:
        import logging
        logging.basicConfig(level=logging.INFO)

    # CLI interface
    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "list":
            list_bindings_cli()
        elif command == "add" and len(sys.argv) >= 4:
            session_name = sys.argv[2]
            proxy_id = sys.argv[3]
            add_binding_cli(session_name, proxy_id)
        elif command == "auto":
            auto_assign_unbound_sessions()
        else:
            print("Usage:")
            print("  python session_proxy_binder.py list              - List all bindings")
            print("  python session_proxy_binder.py add <session> <proxy>  - Add binding")
            print("  python session_proxy_binder.py auto              - Auto-assign unbound sessions")
    else:
        # Run test
        test_session_proxy_binder()