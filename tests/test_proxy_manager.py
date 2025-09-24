#!/usr/bin/env python3
"""
Unit Tests for ProxyManager - Facebook Post Monitor Enterprise Edition

Tests cho proxy pool management và integration với Playwright
"""

import pytest
import tempfile
import os
import time
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

# Import the module under test
from core.proxy_manager import ProxyManager


class TestProxyManager:
    """Test suite cho ProxyManager"""
    
    @pytest.fixture
    def temp_files(self):
        """Tạo temporary files cho test"""
        temp_dir = tempfile.mkdtemp()
        proxy_file = os.path.join(temp_dir, "test_proxies.txt")
        status_file = os.path.join(temp_dir, "test_proxy_status.json")
        
        yield proxy_file, status_file
        
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def proxy_manager(self, temp_files):
        """ProxyManager instance với temporary files"""
        proxy_file, status_file = temp_files
        return ProxyManager(proxy_file, status_file)
    
    @pytest.fixture
    def proxy_file_with_data(self, temp_files):
        """Tạo proxy file với test data"""
        proxy_file, status_file = temp_files
        
        with open(proxy_file, 'w') as f:
            f.write("# Test proxy configuration\n")
            f.write("192.168.1.100:8080:user:pass\n")
            f.write("203.0.113.1:3128\n")
            f.write("socks5://user2:pass2@192.168.1.200:1080\n")
            f.write("# Another comment\n")
            f.write("invalid_line_should_be_ignored\n")
            f.write("198.51.100.1:9090:test:secret\n")
        
        return proxy_file, status_file
    
    def test_initialization(self, temp_files):
        """Test khởi tạo ProxyManager"""
        proxy_file, status_file = temp_files
        
        manager = ProxyManager(proxy_file, status_file)
        
        assert manager.proxy_file == proxy_file
        assert manager.status_file == status_file
        assert os.path.exists(proxy_file)  # Template should be created
        assert os.path.exists(status_file)  # Status file should be created
    
    def test_initialization_with_existing_proxies(self, proxy_file_with_data):
        """Test khởi tạo với proxy file có sẵn"""
        proxy_file, status_file = proxy_file_with_data
        
        manager = ProxyManager(proxy_file, status_file)
        
        # Should detect existing proxies
        status = manager._read_status_file()
        assert len(status) > 0
        assert any(info["status"] == "READY" for info in status.values())
    
    def test_parse_proxy_line_http_no_auth(self, proxy_manager):
        """Test parse HTTP proxy không có authentication"""
        result = proxy_manager._parse_proxy_line("192.168.1.100:8080")
        
        expected = {
            "type": "http",
            "host": "192.168.1.100",
            "port": 8080,
            "username": None,
            "password": None
        }
        assert result == expected
    
    def test_parse_proxy_line_http_with_auth(self, proxy_manager):
        """Test parse HTTP proxy có authentication"""
        result = proxy_manager._parse_proxy_line("192.168.1.100:8080:user:pass")
        
        expected = {
            "type": "http",
            "host": "192.168.1.100",
            "port": 8080,
            "username": "user",
            "password": "pass"
        }
        assert result == expected
    
    def test_parse_proxy_line_socks5(self, proxy_manager):
        """Test parse SOCKS5 proxy"""
        result = proxy_manager._parse_proxy_line("socks5://user:pass@192.168.1.200:1080")
        
        expected = {
            "type": "socks5",
            "host": "192.168.1.200",
            "port": 1080,
            "username": "user",
            "password": "pass"
        }
        assert result == expected
    
    def test_parse_proxy_line_invalid(self, proxy_manager):
        """Test parse proxy line không hợp lệ"""
        result = proxy_manager._parse_proxy_line("invalid_proxy_format")
        assert result is None
        
        result = proxy_manager._parse_proxy_line("too:many:colons:here:and:here")
        assert result is None
    
    def test_load_proxies_from_file(self, proxy_file_with_data):
        """Test load proxies từ file"""
        proxy_file, status_file = proxy_file_with_data
        manager = ProxyManager(proxy_file, status_file)
        
        proxies = manager._load_proxies_from_file()
        
        # Should load 3 valid proxies (ignoring comments and invalid lines)
        assert len(proxies) == 3
        
        # Check specific proxy configs
        assert any(p["host"] == "192.168.1.100" and p["port"] == 8080 for p in proxies)
        assert any(p["host"] == "203.0.113.1" and p["port"] == 3128 for p in proxies)
        assert any(p["type"] == "socks5" and p["host"] == "192.168.1.200" for p in proxies)
    
    def test_checkout_proxy_success(self, proxy_file_with_data):
        """Test checkout proxy thành công"""
        proxy_file, status_file = proxy_file_with_data
        manager = ProxyManager(proxy_file, status_file)
        
        proxy = manager.checkout_proxy(timeout=5)
        
        assert proxy is not None
        assert "proxy_id" in proxy
        assert "host" in proxy
        assert "port" in proxy
        
        # Verify proxy is marked as IN_USE
        status = manager._read_status_file()
        proxy_id = proxy["proxy_id"]
        assert status[proxy_id]["status"] == "IN_USE"
    
    def test_checkout_proxy_no_available(self, proxy_file_with_data):
        """Test checkout proxy khi không có proxy nào sẵn sàng"""
        proxy_file, status_file = proxy_file_with_data
        manager = ProxyManager(proxy_file, status_file)
        
        # Mark all proxies as IN_USE
        status_data = manager._read_status_file()
        for proxy_id in status_data:
            status_data[proxy_id]["status"] = "IN_USE"
        manager._write_status_file(status_data)
        
        proxy = manager.checkout_proxy(timeout=2)
        
        assert proxy is None
    
    def test_checkin_proxy_success(self, proxy_file_with_data):
        """Test checkin proxy thành công"""
        proxy_file, status_file = proxy_file_with_data
        manager = ProxyManager(proxy_file, status_file)
        
        # Checkout then checkin
        proxy = manager.checkout_proxy()
        assert proxy is not None
        
        manager.checkin_proxy(proxy, "READY")
        
        # Verify proxy is back to READY
        status = manager._read_status_file()
        proxy_id = proxy["proxy_id"]
        assert status[proxy_id]["status"] == "READY"
    
    def test_checkin_proxy_without_id(self, proxy_manager):
        """Test checkin proxy config thiếu proxy_id"""
        proxy_config = {"host": "192.168.1.100", "port": 8080}
        
        # Should not raise exception
        proxy_manager.checkin_proxy(proxy_config, "READY")
    
    def test_get_proxy_for_playwright_http(self, proxy_manager):
        """Test convert HTTP proxy sang format Playwright"""
        proxy_config = {
            "type": "http",
            "host": "192.168.1.100",
            "port": 8080,
            "username": "user",
            "password": "pass"
        }
        
        result = proxy_manager.get_proxy_for_playwright(proxy_config)
        
        expected = {
            "server": "http://192.168.1.100:8080",
            "username": "user",
            "password": "pass"
        }
        assert result == expected
    
    def test_get_proxy_for_playwright_socks5(self, proxy_manager):
        """Test convert SOCKS5 proxy sang format Playwright"""
        proxy_config = {
            "type": "socks5",
            "host": "192.168.1.200",
            "port": 1080,
            "username": "user",
            "password": "pass"
        }
        
        result = proxy_manager.get_proxy_for_playwright(proxy_config)
        
        expected = {
            "server": "socks5://192.168.1.200:1080",
            "username": "user",
            "password": "pass"
        }
        assert result == expected
    
    def test_get_proxy_for_playwright_no_auth(self, proxy_manager):
        """Test convert proxy không có auth sang format Playwright"""
        proxy_config = {
            "type": "http",
            "host": "203.0.113.1",
            "port": 3128,
            "username": None,
            "password": None
        }
        
        result = proxy_manager.get_proxy_for_playwright(proxy_config)
        
        expected = {
            "server": "http://203.0.113.1:3128"
        }
        assert result == expected
    
    def test_get_proxy_for_playwright_none(self, proxy_manager):
        """Test convert proxy None"""
        result = proxy_manager.get_proxy_for_playwright(None)
        assert result is None
    
    @patch('proxy_manager.requests.Session')
    def test_health_check_proxy_success(self, mock_session_class, proxy_manager):
        """Test health check proxy thành công"""
        # Mock requests session
        mock_session = Mock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response
        mock_session_class.return_value = mock_session
        
        proxy_config = {
            "type": "http",
            "host": "192.168.1.100",
            "port": 8080,
            "username": "user",
            "password": "pass",
            "proxy_id": "proxy_1"
        }
        
        result = proxy_manager.health_check_proxy(proxy_config)
        
        assert result is True
        mock_session.get.assert_called_once()
    
    @patch('proxy_manager.requests.Session')
    def test_health_check_proxy_failure(self, mock_session_class, proxy_manager):
        """Test health check proxy thất bại"""
        # Mock requests session with error
        mock_session = Mock()
        mock_session.get.side_effect = Exception("Connection failed")
        mock_session_class.return_value = mock_session
        
        proxy_config = {
            "type": "http",
            "host": "192.168.1.100",
            "port": 8080,
            "proxy_id": "proxy_1"
        }
        
        result = proxy_manager.health_check_proxy(proxy_config)
        
        assert result is False
    
    def test_get_stats(self, proxy_file_with_data):
        """Test lấy thống kê proxies"""
        proxy_file, status_file = proxy_file_with_data
        manager = ProxyManager(proxy_file, status_file)
        
        # Modify some proxy statuses
        status_data = manager._read_status_file()
        proxy_ids = list(status_data.keys())
        if len(proxy_ids) >= 3:
            status_data[proxy_ids[0]]["status"] = "READY"
            status_data[proxy_ids[1]]["status"] = "IN_USE"
            status_data[proxy_ids[2]]["status"] = "FAILED"
        manager._write_status_file(status_data)
        
        stats = manager.get_stats()
        
        assert stats['total'] >= 3
        assert stats['ready'] >= 1
        assert stats['in_use'] >= 1
        assert stats['failed'] >= 1
        assert stats['disabled'] >= 0
        assert stats['testing'] >= 0
    
    def test_mark_proxy_failed(self, proxy_file_with_data):
        """Test đánh dấu proxy thất bại"""
        proxy_file, status_file = proxy_file_with_data
        manager = ProxyManager(proxy_file, status_file)
        
        proxy = manager.checkout_proxy()
        assert proxy is not None
        
        manager.mark_proxy_failed(proxy, "Connection timeout")
        
        # Verify proxy is marked as FAILED
        status = manager._read_status_file()
        proxy_id = proxy["proxy_id"]
        assert status[proxy_id]["status"] == "FAILED"
    
    def test_reset_all_proxies(self, proxy_file_with_data):
        """Test reset tất cả proxies"""
        proxy_file, status_file = proxy_file_with_data
        manager = ProxyManager(proxy_file, status_file)
        
        # Set various statuses
        status_data = manager._read_status_file()
        proxy_ids = list(status_data.keys())
        for i, proxy_id in enumerate(proxy_ids):
            if i % 3 == 0:
                status_data[proxy_id]["status"] = "IN_USE"
            elif i % 3 == 1:
                status_data[proxy_id]["status"] = "FAILED"
            else:
                status_data[proxy_id]["status"] = "DISABLED"
            status_data[proxy_id]["failure_count"] = 5
        manager._write_status_file(status_data)
        
        manager.reset_all_proxies()
        
        # Verify all proxies are READY with failure_count reset
        status = manager._read_status_file()
        for proxy_info in status.values():
            assert proxy_info["status"] == "READY"
            assert proxy_info["failure_count"] == 0
    
    def test_validate_proxy_config_valid(self, proxy_manager):
        """Test validate proxy config hợp lệ"""
        config = {
            "type": "http",
            "host": "192.168.1.100",
            "port": 8080
        }
        
        result = proxy_manager._validate_proxy_config(config)
        assert result is True
    
    def test_validate_proxy_config_invalid(self, proxy_manager):
        """Test validate proxy config không hợp lệ"""
        config = {
            "type": "http",
            "host": "192.168.1.100"
            # Missing port
        }
        
        result = proxy_manager._validate_proxy_config(config)
        assert result is False


class TestProxyManagerConcurrency:
    """Test concurrent access để verify thread-safety"""
    
    @pytest.fixture
    def concurrent_proxy_manager(self, temp_files):
        """ProxyManager cho concurrent tests"""
        proxy_file, status_file = temp_files
        
        # Tạo proxy file với multiple proxies
        with open(proxy_file, 'w') as f:
            for i in range(5):
                f.write(f"192.168.1.{100+i}:808{i}:user{i}:pass{i}\n")
        
        manager = ProxyManager(proxy_file, status_file)
        return manager
    
    def test_concurrent_checkout_checkin(self, concurrent_proxy_manager):
        """Test concurrent checkout/checkin operations"""
        manager = concurrent_proxy_manager
        results = []
        errors = []
        
        def worker(worker_id):
            try:
                # Multiple checkout/checkin cycles
                for i in range(3):
                    proxy = manager.checkout_proxy(timeout=10)
                    if proxy:
                        results.append(f"worker_{worker_id}_cycle_{i}_checkout_{proxy['proxy_id']}")
                        time.sleep(0.1)  # Simulate work
                        manager.checkin_proxy(proxy)
                        results.append(f"worker_{worker_id}_cycle_{i}_checkin_{proxy['proxy_id']}")
                    else:
                        results.append(f"worker_{worker_id}_cycle_{i}_no_proxy")
            except Exception as e:
                errors.append(f"worker_{worker_id}_error_{e}")
        
        # Run 10 workers concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(10)]
            for future in futures:
                future.result(timeout=30)
        
        # Verify no errors occurred
        assert len(errors) == 0, f"Concurrent errors: {errors}"
        
        # Verify operations completed
        assert len(results) > 0
        
        # Verify all proxies are back to READY
        final_stats = manager.get_stats()
        assert final_stats['in_use'] == 0  # All proxies should be checked in


# Integration tests (cần network connectivity)
class TestProxyManagerIntegration:
    """Integration tests cần network để test real proxy connections"""
    
    @pytest.mark.integration
    def test_real_proxy_health_check(self):
        """Test health check với proxy thật (skip nếu không có proxy)"""
        pytest.skip("Integration test - cần proxy server thật để chạy")


if __name__ == "__main__":
    # Chạy tests với pytest
    import subprocess
    import sys
    
    print("🧪 Running ProxyManager tests...")
    result = subprocess.run([
        sys.executable, "-m", "pytest", __file__, "-v", 
        "--tb=short", "-x"  # Stop on first failure
    ])
    
    if result.returncode == 0:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed!")
        sys.exit(result.returncode)




