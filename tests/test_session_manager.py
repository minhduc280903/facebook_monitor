#!/usr/bin/env python3
"""
Unit Tests for SessionManager - Facebook Post Monitor Enterprise Edition
Tests cho thread-safe session pool management
"""

import pytest
import tempfile
import os
import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

# Import the module under test
from core.session_manager import SessionManager, ManagedResource, AccountRole


class TestSessionManager:
    """Test suite cho SessionManager"""

    @pytest.fixture
    def temp_dirs(self):
        """Tạo temporary directories cho test"""
        temp_dir = tempfile.mkdtemp()
        sessions_dir = os.path.join(temp_dir, "test_sessions")
        status_file = os.path.join(temp_dir, "test_session_status.json")
        
        os.makedirs(sessions_dir, exist_ok=True)
        
        yield sessions_dir, status_file
        
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def session_manager(self, temp_dirs):
        """SessionManager instance với temporary files"""
        sessions_dir, status_file = temp_dirs
        # Patch to prevent initial file creation based on folder scan
        with patch.object(SessionManager, '_create_initial_status_file', return_value=None):
            manager = SessionManager(status_file, sessions_dir)
            manager.resource_pool = {} # Start with a clean pool
            return manager

    @pytest.fixture
    def valid_session_folder(self, temp_dirs):
        """Tạo valid session folder cho test"""
        sessions_dir, _ = temp_dirs
        session_path = os.path.join(sessions_dir, "test_account")
        os.makedirs(session_path, exist_ok=True)
        
        # Tạo các file/folder required
        os.makedirs(os.path.join(session_path, "Default"), exist_ok=True)
        with open(os.path.join(session_path, "Local State"), 'w') as f:
            f.write('{"test": "data"}')
        
        return session_path

    def test_initialization(self, temp_dirs):
        """Test khởi tạo SessionManager"""
        sessions_dir, status_file = temp_dirs
        
        manager = SessionManager(status_file, sessions_dir)
        
        assert manager.status_file == status_file
        assert manager.sessions_dir == sessions_dir
        assert os.path.exists(status_file)

    def test_initialization_with_existing_session(self, temp_dirs, valid_session_folder):
        """Test khởi tạo với session folder có sẵn"""
        sessions_dir, status_file = temp_dirs
        
        manager = SessionManager(status_file, sessions_dir)
        
        status = manager.get_status()
        assert len(status) > 0
        assert any(info["status"] == "READY" for info in status.values())

    def test_is_valid_session_folder_true(self, session_manager, valid_session_folder):
        """Test _is_valid_session_folder với folder hợp lệ"""
        result = session_manager._is_valid_session_folder(valid_session_folder)
        assert result is True

    def test_is_valid_session_folder_false(self, session_manager, temp_dirs):
        """Test _is_valid_session_folder với folder không hợp lệ"""
        sessions_dir, _ = temp_dirs
        invalid_path = os.path.join(sessions_dir, "invalid_session")
        os.makedirs(invalid_path, exist_ok=True)
        
        result = session_manager._is_valid_session_folder(invalid_path)
        assert result is False

    def test_checkout_session_success(self, session_manager, valid_session_folder):
        """Test checkout session thành công"""
        session_name = os.path.basename(valid_session_folder)
        resource = ManagedResource(session_name)
        session_manager.resource_pool = {session_name: resource}
        
        result = session_manager.checkout_session(timeout=1)
        
        assert result == session_name
        status = session_manager.get_status()
        assert status[session_name]["status"] == "IN_USE"

    def test_checkout_session_no_available(self, session_manager):
        """Test checkout session khi không có session nào sẵn sàng"""
        resource1 = ManagedResource("session1")
        resource1.status = "IN_USE"
        resource2 = ManagedResource("session2")
        resource2.status = "NEEDS_LOGIN"
        session_manager.resource_pool = {"session1": resource1, "session2": resource2}
        
        result = session_manager.checkout_session(timeout=1)
        
        assert result is None

    def test_checkout_session_invalid_folder(self, session_manager, temp_dirs):
        """Test checkout session với folder không hợp lệ"""
        session_name = "nonexistent_session"
        resource = ManagedResource(session_name)
        session_manager.resource_pool = {session_name: resource}

        result = session_manager.checkout_session(timeout=1)
        
        assert result is None
        status = session_manager.get_status()
        assert status[session_name]["status"] == "NEEDS_LOGIN"

    def test_checkin_session_success(self, session_manager):
        """Test checkin session thành công"""
        session_name = "test_session"
        resource = ManagedResource(session_name)
        resource.status = "IN_USE"
        session_manager.resource_pool = {session_name: resource}
        
        session_manager.checkin_session(session_name, "READY")
        
        status = session_manager.get_status()
        assert status[session_name]["status"] == "READY"

    def test_checkin_session_nonexistent(self, session_manager):
        """Test checkin session không tồn tại"""
        session_manager.checkin_session("nonexistent_session", "READY")
        # Should not raise exception

    def test_get_session_path(self, session_manager):
        """Test lấy đường dẫn session"""
        expected_path = os.path.join(session_manager.sessions_dir, "test_session")
        result = session_manager.get_session_path("test_session")
        assert result == expected_path

    def test_get_stats(self, session_manager):
        """Test lấy thống kê sessions"""
        res1 = ManagedResource("s1")
        res1.status = "READY"
        res2 = ManagedResource("s2")
        res2.status = "IN_USE"
        res3 = ManagedResource("s3")
        res3.status = "NEEDS_LOGIN"
        res4 = ManagedResource("s4")
        res4.status = "DISABLED"
        session_manager.resource_pool = {"s1": res1, "s2": res2, "s3": res3, "s4": res4}

        stats = session_manager.get_stats()
        
        assert stats['total'] == 4
        assert stats['ready'] == 1
        assert stats['in_use'] == 1
        assert stats['needs_login'] == 1
        assert stats['disabled'] == 1

    def test_mark_session_invalid(self, session_manager):
        """Test đánh dấu session không hợp lệ"""
        session_name = "test_session"
        resource = ManagedResource(session_name)
        resource.status = "IN_USE"
        session_manager.resource_pool = {session_name: resource}
        
        session_manager.mark_session_invalid(session_name, "Login failed")
        
        status = session_manager.get_status()
        assert status[session_name]["status"] == "NEEDS_LOGIN"

    def test_reset_all_sessions(self, session_manager):
        """Test reset tất cả sessions"""
        res1 = ManagedResource("s1"); res1.status="IN_USE"; res1.consecutive_failures=3
        res2 = ManagedResource("s2"); res2.status="NEEDS_LOGIN"; res2.consecutive_failures=1
        session_manager.resource_pool = {"s1": res1, "s2": res2}
        
        session_manager.reset_all_sessions()
        
        status = session_manager.get_status()
        for session_info in status.values():
            assert session_info["status"] == "READY"
            assert session_info["consecutive_failures"] == 0

    def test_report_outcome_failure_below_threshold(self, session_manager):
        """Test report_outcome 'failure' dưới threshold"""
        session_name = "test_session"
        resource = ManagedResource(session_name)
        resource.consecutive_failures = 1
        session_manager.resource_pool = {session_name: resource}
        session_manager.consecutive_failure_threshold = 3
        
        session_manager.report_outcome(session_name, 'failure')
        
        status = session_manager.get_status()
        assert status[session_name]["consecutive_failures"] == 2
        assert status[session_name]["status"] == "READY"

    def test_report_outcome_failure_exceed_threshold(self, session_manager):
        """Test report_outcome 'failure' vượt threshold"""
        session_name = "test_session"
        resource = ManagedResource(session_name)
        resource.consecutive_failures = 2
        session_manager.resource_pool = {session_name: resource}
        session_manager.consecutive_failure_threshold = 3
        
        session_manager.report_outcome(session_name, 'failure')
        
        status = session_manager.get_status()
        assert status[session_name]["status"] == "QUARANTINED"
        
    def test_report_outcome_success(self, session_manager):
        """Test report_outcome 'success' reset failure count"""
        session_name = "test_session"
        resource = ManagedResource(session_name)
        resource.consecutive_failures = 5
        session_manager.resource_pool = {session_name: resource}
        
        session_manager.report_outcome(session_name, 'success')
        
        status = session_manager.get_status()
        assert status[session_name]["consecutive_failures"] == 0

    def test_list_sessions(self, session_manager):
        """Test lấy danh sách session names"""
        res1 = ManagedResource("s1")
        res2 = ManagedResource("s2")
        session_manager.resource_pool = {"s1": res1, "s2": res2}
        
        sessions = session_manager.list_sessions()
        
        assert len(sessions) == 2
        assert "s1" in sessions

    def test_migration_legacy_format(self, session_manager):
        """Test migration từ format cũ sang format mới"""
        legacy_data = {
            "session1": "READY",
            "session2": {"status": "IN_USE", "failure_count": 3}
        }
        
        migrated_data = session_manager._migrate_old_format(legacy_data)
        
        assert isinstance(migrated_data["session1"], dict)
        assert migrated_data["session1"]["status"] == "READY"
        assert migrated_data["session1"]["consecutive_failures"] == 0
        assert migrated_data["session2"]["consecutive_failures"] == 3
    
    def test_locks_context_manager_basic(self, session_manager):
        """Test locks() context manager unifies thread and file locks"""
        # This test verifies the locks() context manager works correctly
        # It should handle both thread lock and file lock (if available)
        
        import threading
        results = []
        
        def worker():
            """Worker thread that uses locks() context manager"""
            with session_manager.locks():
                # Do some work inside locks
                time.sleep(0.01)  # Small delay to ensure concurrent access
                results.append(threading.current_thread().name)
        
        # Create multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, name=f"Worker-{i}")
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # All workers should have completed
        assert len(results) == 5
        
        # Verify no race conditions (all thread names should be unique)
        assert len(set(results)) == 5
    
    def test_locks_context_manager_exception_safety(self, session_manager):
        """Test locks() context manager properly releases locks on exception"""
        # Verify that locks are released even when exception occurs
        
        try:
            with session_manager.locks():
                # Simulate an error inside the lock
                raise ValueError("Test exception")
        except ValueError:
            pass  # Expected
        
        # Lock should be released, so we can acquire it again
        with session_manager.locks():
            # If we get here, lock was properly released
            assert True

class TestSessionManagerConcurrency:
    """Test concurrent access để verify thread-safety"""
    
    @pytest.fixture
    def concurrent_session_manager(self, temp_dirs):
        """SessionManager cho concurrent tests"""
        sessions_dir, status_file = temp_dirs
        
        for i in range(5):
            session_path = os.path.join(sessions_dir, f"session_{i}")
            os.makedirs(os.path.join(session_path, "Default"), exist_ok=True)
            with open(os.path.join(session_path, "Local State"), 'w') as f:
                f.write('{"test": "data"}')
        
        return SessionManager(status_file, sessions_dir)
    
    def test_concurrent_checkout_checkin(self, concurrent_session_manager):
        """Test concurrent checkout/checkin operations"""
        manager = concurrent_session_manager
        errors = []
        
        def worker(worker_id):
            try:
                for i in range(2):
                    session = manager.checkout_session(timeout=10)
                    if session:
                        time.sleep(0.05)
                        manager.checkin_session(session)
                    else:
                        # This can happen and is not an error
                        pass
            except Exception as e:
                errors.append(f"worker_{worker_id}_error_{e}")
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(10)]
            for future in futures:
                future.result(timeout=20)
        
        assert len(errors) == 0, f"Concurrent errors: {errors}"
        final_stats = manager.get_stats()
        assert final_stats['in_use'] == 0


class TestSessionProxyBinding:
    """Test session-proxy binding integration"""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing"""
        test_dir = tempfile.mkdtemp()
        status_file = os.path.join(test_dir, "test_session_status.json")
        sessions_dir = os.path.join(test_dir, "test_sessions")
        proxy_file = os.path.join(test_dir, "test_proxies.txt")
        proxy_status_file = os.path.join(test_dir, "test_proxy_status.json")
        
        yield {
            "status_file": status_file,
            "sessions_dir": sessions_dir,
            "proxy_file": proxy_file,
            "proxy_status_file": proxy_status_file
        }
        
        shutil.rmtree(test_dir)

    @pytest.fixture
    def session_proxy_managers(self, temp_dirs):
        """Create session and proxy managers for testing"""
        from core.proxy_manager import ProxyManager
        
        # Create proxy file with test data
        with open(temp_dirs["proxy_file"], 'w') as f:
            f.write("192.168.1.100:8080:user:pass\n")
            f.write("192.168.1.101:8080:user2:pass2\n")
        
        # Create managers
        session_manager = SessionManager(
            temp_dirs["status_file"], 
            temp_dirs["sessions_dir"]
        )
        proxy_manager = ProxyManager(
            temp_dirs["proxy_file"],
            temp_dirs["proxy_status_file"]
        )
        
        return session_manager, proxy_manager

    @pytest.fixture
    def valid_session_folder(self, temp_dirs):
        """Create a valid session folder for testing"""
        session_name = "test_session_binding"
        session_path = os.path.join(temp_dirs["sessions_dir"], session_name)
        os.makedirs(session_path)
        os.makedirs(os.path.join(session_path, "Default"))
        
        with open(os.path.join(session_path, "Local State"), 'w') as f:
            f.write('{"test": "data"}')
        
        return session_name

    def test_checkout_session_with_proxy_success(self, session_proxy_managers, valid_session_folder):
        """Test successful session-proxy checkout"""
        session_manager, proxy_manager = session_proxy_managers
        
        # Add session to pool
        resource = ManagedResource(valid_session_folder)
        resource.status = "READY"
        session_manager.resource_pool[valid_session_folder] = resource
        
        # Test checkout
        result = session_manager.checkout_session_with_proxy(proxy_manager, timeout=5)
        
        assert result is not None
        session_name, proxy_config = result
        assert session_name == valid_session_folder
        assert "proxy_id" in proxy_config
        assert proxy_config["host"] in ["192.168.1.100", "192.168.1.101"]
        
        # Verify binding was created
        binding_stats = session_manager.proxy_binder.get_binding_stats()
        assert binding_stats["total_bindings"] == 1
        assert valid_session_folder in binding_stats["bindings"]

    def test_checkin_session_with_proxy_success(self, session_proxy_managers, valid_session_folder):
        """Test successful session-proxy checkin"""
        session_manager, proxy_manager = session_proxy_managers
        
        # Setup session and checkout
        resource = ManagedResource(valid_session_folder)
        resource.status = "READY"
        session_manager.resource_pool[valid_session_folder] = resource
        
        result = session_manager.checkout_session_with_proxy(proxy_manager, timeout=5)
        assert result is not None
        
        session_name, proxy_config = result
        
        # Test checkin
        session_manager.checkin_session_with_proxy(
            session_name, proxy_config, proxy_manager, "READY", "READY"
        )
        
        # Verify session and proxy are back to READY
        session_status = session_manager.get_status()
        assert session_status[session_name]["status"] == "READY"
        
        proxy_stats = proxy_manager.get_stats()
        assert proxy_stats["ready"] >= 1

    def test_consistent_session_proxy_binding(self, session_proxy_managers, valid_session_folder):
        """Test that same session gets same proxy consistently"""
        session_manager, proxy_manager = session_proxy_managers
        
        # Add session to pool
        resource = ManagedResource(valid_session_folder)
        resource.status = "READY"
        session_manager.resource_pool[valid_session_folder] = resource
        
        # First checkout
        result1 = session_manager.checkout_session_with_proxy(proxy_manager, timeout=5)
        assert result1 is not None
        
        session_name1, proxy_config1 = result1
        proxy_id1 = proxy_config1["proxy_id"]
        
        # Checkin
        session_manager.checkin_session_with_proxy(
            session_name1, proxy_config1, proxy_manager
        )
        
        # Second checkout - should get same proxy
        result2 = session_manager.checkout_session_with_proxy(proxy_manager, timeout=5)
        assert result2 is not None
        
        session_name2, proxy_config2 = result2
        proxy_id2 = proxy_config2["proxy_id"]
        
        # Should be same binding
        assert session_name1 == session_name2 == valid_session_folder
        assert proxy_id1 == proxy_id2

    def test_multiple_sessions_different_proxies(self, session_proxy_managers, temp_dirs):
        """Test that different sessions get different proxies when possible"""
        session_manager, proxy_manager = session_proxy_managers
        
        # Create two sessions
        session_names = ["test_session_1", "test_session_2"]
        for session_name in session_names:
            session_path = os.path.join(temp_dirs["sessions_dir"], session_name)
            os.makedirs(session_path)
            os.makedirs(os.path.join(session_path, "Default"))
            
            with open(os.path.join(session_path, "Local State"), 'w') as f:
                f.write('{"test": "data"}')
            
            # Add to pool
            resource = ManagedResource(session_name)
            resource.status = "READY"
            session_manager.resource_pool[session_name] = resource
        
        # Checkout both sessions
        results = []
        for _ in range(2):
            result = session_manager.checkout_session_with_proxy(proxy_manager, timeout=5)
            assert result is not None
            results.append(result)
        
        # Should get different proxy IDs if possible
        session1, proxy1 = results[0]
        session2, proxy2 = results[1]
        
        # Different sessions
        assert session1 != session2
        
        # Should try to get different proxies when available
        if proxy_manager.get_stats()["total"] > 1:
            assert proxy1["proxy_id"] != proxy2["proxy_id"]

    def test_no_available_proxies(self, session_proxy_managers, valid_session_folder):
        """Test behavior when no proxies are available"""
        session_manager, proxy_manager = session_proxy_managers
        
        # Mark all proxies as IN_USE
        for proxy_resource in proxy_manager.resource_pool.values():
            proxy_resource.status = "IN_USE"
        
        # Add session to pool
        resource = ManagedResource(valid_session_folder)
        resource.status = "READY"
        session_manager.resource_pool[valid_session_folder] = resource
        
        # Should return None when no proxies available
        result = session_manager.checkout_session_with_proxy(proxy_manager, timeout=2)
        assert result is None

    def test_binding_persistence_across_restarts(self, temp_dirs):
        """Test that bindings persist across manager restarts"""
        from core.proxy_manager import ProxyManager
        
        # Create proxy file
        with open(temp_dirs["proxy_file"], 'w') as f:
            f.write("192.168.1.100:8080:user:pass\n")
        
        session_name = "persistent_test_session"
        session_path = os.path.join(temp_dirs["sessions_dir"], session_name)
        os.makedirs(session_path)
        os.makedirs(os.path.join(session_path, "Default"))
        
        with open(os.path.join(session_path, "Local State"), 'w') as f:
            f.write('{"test": "data"}')
        
        # First manager instance
        session_manager1 = SessionManager(
            temp_dirs["status_file"], 
            temp_dirs["sessions_dir"]
        )
        proxy_manager1 = ProxyManager(
            temp_dirs["proxy_file"],
            temp_dirs["proxy_status_file"]
        )
        
        # Create binding
        resource = ManagedResource(session_name)
        resource.status = "READY"
        session_manager1.resource_pool[session_name] = resource
        
        result1 = session_manager1.checkout_session_with_proxy(proxy_manager1, timeout=5)
        assert result1 is not None
        
        _, proxy_config1 = result1
        proxy_id1 = proxy_config1["proxy_id"]
        
        session_manager1.checkin_session_with_proxy(
            session_name, proxy_config1, proxy_manager1
        )
        
        # Second manager instance (simulating restart)
        session_manager2 = SessionManager(
            temp_dirs["status_file"], 
            temp_dirs["sessions_dir"]
        )
        proxy_manager2 = ProxyManager(
            temp_dirs["proxy_file"],
            temp_dirs["proxy_status_file"]
        )
        
        # Should get same binding
        result2 = session_manager2.checkout_session_with_proxy(proxy_manager2, timeout=5)
        assert result2 is not None
        
        _, proxy_config2 = result2
        proxy_id2 = proxy_config2["proxy_id"]
        
        assert proxy_id1 == proxy_id2