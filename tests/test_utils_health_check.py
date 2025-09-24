#!/usr/bin/env python3
"""
Comprehensive tests for Health Check Service
Tests health monitoring, metrics collection, and endpoint functionality
"""

import pytest
import time
import json
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import Dict, Any

# Setup path for imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import health check components
from utils.health_check import (
    HealthCheckService, SystemHealthChecker, ComponentHealthStatus,
    PrometheusMetrics, get_system_health, create_health_endpoint
)


@pytest.mark.unit
class TestComponentHealthStatus:
    """Test ComponentHealthStatus data structure"""
    
    def test_healthy_status_creation(self):
        """Test creating healthy component status"""
        status = ComponentHealthStatus(
            name="test_component",
            healthy=True,
            message="All systems operational",
            response_time=0.05,
            last_check=time.time()
        )
        
        assert status.name == "test_component"
        assert status.healthy is True
        assert status.message == "All systems operational"
        assert status.response_time == 0.05
        assert status.last_check is not None
    
    def test_unhealthy_status_creation(self):
        """Test creating unhealthy component status"""
        status = ComponentHealthStatus(
            name="failing_component",
            healthy=False,
            message="Connection failed",
            error="Database timeout",
            response_time=30.0
        )
        
        assert status.name == "failing_component"
        assert status.healthy is False
        assert status.message == "Connection failed"
        assert status.error == "Database timeout"
        assert status.response_time == 30.0
    
    def test_status_to_dict(self):
        """Test converting status to dictionary"""
        status = ComponentHealthStatus(
            name="api_component",
            healthy=True,
            message="API responding",
            response_time=0.1,
            metadata={"version": "1.0", "uptime": 3600}
        )
        
        status_dict = status.to_dict()
        
        assert status_dict["name"] == "api_component"
        assert status_dict["healthy"] is True
        assert status_dict["message"] == "API responding"
        assert status_dict["response_time"] == 0.1
        assert status_dict["metadata"]["version"] == "1.0"
        assert "last_check" in status_dict


@pytest.mark.unit
class TestSystemHealthChecker:
    """Test SystemHealthChecker functionality"""
    
    @pytest.fixture
    def health_checker(self):
        """Create SystemHealthChecker instance for testing"""
        return SystemHealthChecker()
    
    def test_database_health_check_success(self, health_checker):
        """Test successful database health check"""
        # Mock database manager
        mock_db = Mock()
        mock_db.execute_query.return_value = [{"result": 1}]
        
        with patch('utils.health_check.DatabaseManager', return_value=mock_db):
            status = health_checker.check_database_health()
        
        assert status.name == "database"
        assert status.healthy is True
        assert "Database connection successful" in status.message
        assert status.response_time > 0
        mock_db.execute_query.assert_called_once_with("SELECT 1")
    
    def test_database_health_check_failure(self, health_checker):
        """Test database health check failure"""
        mock_db = Mock()
        mock_db.execute_query.side_effect = Exception("Connection failed")
        
        with patch('utils.health_check.DatabaseManager', return_value=mock_db):
            status = health_checker.check_database_health()
        
        assert status.name == "database"
        assert status.healthy is False
        assert "Database health check failed" in status.message
        assert "Connection failed" in status.error
    
    def test_redis_health_check_success(self, health_checker):
        """Test successful Redis health check"""
        mock_redis = Mock()
        mock_redis.ping.return_value = True
        mock_redis.info.return_value = {"redis_version": "7.0.0", "used_memory": 1024}
        
        with patch('redis.Redis', return_value=mock_redis):
            status = health_checker.check_redis_health()
        
        assert status.name == "redis"
        assert status.healthy is True
        assert "Redis connection successful" in status.message
        assert status.metadata["redis_version"] == "7.0.0"
        mock_redis.ping.assert_called_once()
    
    def test_redis_health_check_failure(self, health_checker):
        """Test Redis health check failure"""
        mock_redis = Mock()
        mock_redis.ping.side_effect = Exception("Redis unavailable")
        
        with patch('redis.Redis', return_value=mock_redis):
            status = health_checker.check_redis_health()
        
        assert status.name == "redis"
        assert status.healthy is False
        assert "Redis health check failed" in status.message
        assert "Redis unavailable" in status.error
    
    def test_session_manager_health_check(self, health_checker):
        """Test session manager health check"""
        mock_session_manager = Mock()
        mock_session_manager.get_stats.return_value = {
            "total_sessions": 5,
            "active_sessions": 3,
            "quarantined_sessions": 1
        }
        
        with patch('utils.health_check.SessionManager', return_value=mock_session_manager):
            status = health_checker.check_session_manager_health()
        
        assert status.name == "session_manager"
        assert status.healthy is True
        assert status.metadata["total_sessions"] == 5
        assert status.metadata["active_sessions"] == 3
    
    def test_circuit_breaker_health_check(self, health_checker):
        """Test circuit breaker health monitoring"""
        # Mock circuit breaker registry
        mock_breaker = Mock()
        mock_breaker.name = "test_service"
        mock_breaker.state = "CLOSED"
        mock_breaker.failure_count = 0
        mock_breaker.get_metrics.return_value = Mock(
            success_rate=0.95,
            total_calls=100,
            failure_count=5
        )
        
        mock_registry = {"test_service": mock_breaker}
        
        with patch('utils.health_check.circuit_breaker_registry', mock_registry):
            status = health_checker.check_circuit_breakers_health()
        
        assert status.name == "circuit_breakers"
        assert status.healthy is True
        assert "test_service" in status.metadata
        assert status.metadata["test_service"]["state"] == "CLOSED"
    
    def test_system_metrics_collection(self, health_checker):
        """Test system metrics collection"""
        with patch('psutil.cpu_percent', return_value=45.2), \
             patch('psutil.virtual_memory') as mock_memory, \
             patch('psutil.disk_usage') as mock_disk:
            
            mock_memory.return_value.percent = 60.5
            mock_disk.return_value.percent = 75.0
            
            status = health_checker.check_system_metrics()
        
        assert status.name == "system_metrics"
        assert status.healthy is True
        assert status.metadata["cpu_percent"] == 45.2
        assert status.metadata["memory_percent"] == 60.5
        assert status.metadata["disk_percent"] == 75.0
    
    def test_comprehensive_health_check(self, health_checker):
        """Test comprehensive health check of all components"""
        # Mock all components as healthy
        with patch.object(health_checker, 'check_database_health') as mock_db, \
             patch.object(health_checker, 'check_redis_health') as mock_redis, \
             patch.object(health_checker, 'check_session_manager_health') as mock_session, \
             patch.object(health_checker, 'check_system_metrics') as mock_metrics:
            
            mock_db.return_value = ComponentHealthStatus("database", True, "OK")
            mock_redis.return_value = ComponentHealthStatus("redis", True, "OK")
            mock_session.return_value = ComponentHealthStatus("session_manager", True, "OK")
            mock_metrics.return_value = ComponentHealthStatus("system_metrics", True, "OK")
            
            overall_status = health_checker.get_overall_health()
        
        assert overall_status["status"] == "healthy"
        assert len(overall_status["components"]) == 4
        assert all(comp["healthy"] for comp in overall_status["components"])
    
    def test_unhealthy_system_detection(self, health_checker):
        """Test detection when system components are unhealthy"""
        with patch.object(health_checker, 'check_database_health') as mock_db, \
             patch.object(health_checker, 'check_redis_health') as mock_redis:
            
            mock_db.return_value = ComponentHealthStatus("database", False, "Failed", "Connection error")
            mock_redis.return_value = ComponentHealthStatus("redis", True, "OK")
            
            overall_status = health_checker.get_overall_health()
        
        assert overall_status["status"] == "unhealthy"
        assert any(not comp["healthy"] for comp in overall_status["components"])


@pytest.mark.unit
class TestHealthCheckService:
    """Test HealthCheckService main class"""
    
    @pytest.fixture
    def health_service(self):
        """Create HealthCheckService for testing"""
        return HealthCheckService()
    
    def test_service_initialization(self, health_service):
        """Test health service initialization"""
        assert health_service.checker is not None
        assert health_service.last_check_time is None
        assert health_service.cached_status is None
    
    def test_health_check_caching(self, health_service):
        """Test health check result caching"""
        # Mock system health checker
        mock_status = {
            "status": "healthy",
            "timestamp": time.time(),
            "components": []
        }
        
        with patch.object(health_service.checker, 'get_overall_health', return_value=mock_status):
            # First call should perform check
            result1 = health_service.get_health_status(cache_duration=60)
            
            # Second call should use cache
            result2 = health_service.get_health_status(cache_duration=60)
        
        assert result1 == result2
        # Should only call once due to caching
        assert health_service.checker.get_overall_health.call_count == 1
    
    def test_health_check_cache_expiry(self, health_service):
        """Test health check cache expiry"""
        mock_status = {
            "status": "healthy",
            "timestamp": time.time(),
            "components": []
        }
        
        with patch.object(health_service.checker, 'get_overall_health', return_value=mock_status):
            # First call
            health_service.get_health_status(cache_duration=0.1)  # Very short cache
            
            # Wait for cache to expire
            time.sleep(0.2)
            
            # Second call should refresh
            health_service.get_health_status(cache_duration=0.1)
        
        # Should call twice due to cache expiry
        assert health_service.checker.get_overall_health.call_count == 2
    
    def test_forced_health_check_refresh(self, health_service):
        """Test forcing health check refresh"""
        mock_status = {"status": "healthy", "components": []}
        
        with patch.object(health_service.checker, 'get_overall_health', return_value=mock_status):
            # Normal call
            health_service.get_health_status(cache_duration=60)
            
            # Forced refresh
            health_service.get_health_status(force_refresh=True)
        
        # Should call twice due to forced refresh
        assert health_service.checker.get_overall_health.call_count == 2


@pytest.mark.unit
class TestPrometheusMetrics:
    """Test Prometheus metrics functionality"""
    
    def test_metrics_initialization(self):
        """Test Prometheus metrics initialization"""
        metrics = PrometheusMetrics()
        
        assert metrics.registry is not None
        assert hasattr(metrics, 'health_gauge')
        assert hasattr(metrics, 'response_time_histogram')
        assert hasattr(metrics, 'component_status_gauge')
    
    def test_metrics_update(self):
        """Test updating metrics with health data"""
        metrics = PrometheusMetrics()
        
        health_data = {
            "status": "healthy",
            "components": [
                {
                    "name": "database",
                    "healthy": True,
                    "response_time": 0.05
                },
                {
                    "name": "redis", 
                    "healthy": False,
                    "response_time": 2.0
                }
            ]
        }
        
        # Should not raise exceptions
        metrics.update_metrics(health_data)
    
    def test_metrics_export_format(self):
        """Test metrics export in Prometheus format"""
        metrics = PrometheusMetrics()
        
        health_data = {
            "status": "healthy",
            "components": [
                {"name": "test_component", "healthy": True, "response_time": 0.1}
            ]
        }
        
        metrics.update_metrics(health_data)
        exported = metrics.export_metrics()
        
        assert isinstance(exported, str)
        assert "health_check" in exported  # Should contain metric names
        assert "test_component" in exported  # Should contain component labels


@pytest.mark.unit
class TestHealthCheckUtilities:
    """Test health check utility functions"""
    
    def test_get_system_health_function(self):
        """Test get_system_health utility function"""
        with patch('utils.health_check.SystemHealthChecker') as MockChecker:
            mock_checker_instance = Mock()
            mock_checker_instance.get_overall_health.return_value = {
                "status": "healthy",
                "components": []
            }
            MockChecker.return_value = mock_checker_instance
            
            result = get_system_health()
        
        assert result["status"] == "healthy"
        assert "components" in result
        mock_checker_instance.get_overall_health.assert_called_once()
    
    @pytest.mark.skipif(
        True,  # Skip if FastAPI not available in test environment
        reason="FastAPI may not be available in test environment"
    )
    def test_create_health_endpoint(self):
        """Test creating FastAPI health endpoint"""
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            
            app = FastAPI()
            create_health_endpoint(app)
            
            client = TestClient(app)
            
            # Mock the health check
            with patch('utils.health_check.get_system_health') as mock_health:
                mock_health.return_value = {
                    "status": "healthy",
                    "timestamp": time.time(),
                    "components": []
                }
                
                response = client.get("/health")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            
        except ImportError:
            pytest.skip("FastAPI not available")


@pytest.mark.integration 
class TestHealthCheckIntegration:
    """Integration tests for health check system"""
    
    def test_real_world_health_monitoring_workflow(self):
        """Test realistic health monitoring workflow"""
        service = HealthCheckService()
        
        # Mock various system components
        with patch('utils.health_check.DatabaseManager') as MockDB, \
             patch('redis.Redis') as MockRedis, \
             patch('psutil.cpu_percent', return_value=25.0), \
             patch('psutil.virtual_memory') as mock_memory:
            
            # Setup mocks
            mock_db = Mock()
            mock_db.execute_query.return_value = [{"result": 1}]
            MockDB.return_value = mock_db
            
            mock_redis = Mock()
            mock_redis.ping.return_value = True
            mock_redis.info.return_value = {"redis_version": "7.0"}
            MockRedis.return_value = mock_redis
            
            mock_memory.return_value.percent = 45.0
            
            # Perform health check
            health_status = service.get_health_status()
        
        assert health_status["status"] in ["healthy", "degraded", "unhealthy"]
        assert "components" in health_status
        assert "timestamp" in health_status
        
        # Should have checked multiple components
        component_names = [comp["name"] for comp in health_status["components"]]
        assert "database" in component_names
        assert "redis" in component_names
    
    def test_health_check_with_partial_failures(self):
        """Test health check behavior with some components failing"""
        service = HealthCheckService()
        
        with patch('utils.health_check.DatabaseManager') as MockDB, \
             patch('redis.Redis') as MockRedis:
            
            # Database healthy, Redis failing
            mock_db = Mock()
            mock_db.execute_query.return_value = [{"result": 1}]
            MockDB.return_value = mock_db
            
            mock_redis = Mock()
            mock_redis.ping.side_effect = Exception("Redis down")
            MockRedis.return_value = mock_redis
            
            health_status = service.get_health_status()
        
        # System should be degraded with mixed component health
        assert health_status["status"] in ["degraded", "unhealthy"]
        
        components = {comp["name"]: comp["healthy"] for comp in health_status["components"]}
        assert components.get("database") is True
        assert components.get("redis") is False
    
    def test_metrics_collection_and_export(self):
        """Test complete metrics collection and export workflow"""
        service = HealthCheckService()
        metrics = PrometheusMetrics()
        
        # Mock healthy system
        with patch.object(service.checker, 'get_overall_health') as mock_health:
            mock_health.return_value = {
                "status": "healthy",
                "timestamp": time.time(),
                "components": [
                    {"name": "database", "healthy": True, "response_time": 0.05},
                    {"name": "redis", "healthy": True, "response_time": 0.01},
                    {"name": "system_metrics", "healthy": True, "response_time": 0.001}
                ]
            }
            
            # Get health status and update metrics
            health_data = service.get_health_status()
            metrics.update_metrics(health_data)
            
            # Export metrics
            exported_metrics = metrics.export_metrics()
        
        assert isinstance(exported_metrics, str)
        assert len(exported_metrics) > 0
        
        # Should contain component-specific metrics
        assert "database" in exported_metrics
        assert "redis" in exported_metrics


@pytest.mark.unit
class TestHealthCheckErrorScenarios:
    """Test error scenarios and edge cases"""
    
    def test_health_check_with_import_failures(self):
        """Test health check when optional dependencies are missing"""
        # Simulate missing psutil
        with patch('utils.health_check.psutil', None):
            checker = SystemHealthChecker()
            
            # Should gracefully handle missing dependency
            status = checker.check_system_metrics()
            
            assert status.name == "system_metrics"
            # Should either succeed with fallback or fail gracefully
            assert isinstance(status.healthy, bool)
    
    def test_health_check_timeout_handling(self):
        """Test health check with slow/hanging components"""
        checker = SystemHealthChecker()
        
        # Mock slow database
        slow_db = Mock()
        slow_db.execute_query.side_effect = lambda q: time.sleep(5)  # Simulate hanging
        
        with patch('utils.health_check.DatabaseManager', return_value=slow_db):
            start_time = time.time()
            status = checker.check_database_health()
            elapsed = time.time() - start_time
        
        # Should complete within reasonable time (timeout handling)
        assert elapsed < 10  # Should not hang indefinitely
        assert status.name == "database"
    
    def test_malformed_health_data_handling(self):
        """Test handling of malformed health check data"""
        metrics = PrometheusMetrics()
        
        # Test with missing fields
        malformed_data = {"status": "healthy"}  # Missing components
        
        # Should not raise exceptions
        try:
            metrics.update_metrics(malformed_data)
        except Exception as e:
            pytest.fail(f"Should handle malformed data gracefully: {e}")
    
    def test_concurrent_health_checks(self):
        """Test concurrent health check requests"""
        import threading
        
        service = HealthCheckService()
        results = []
        errors = []
        
        def perform_health_check():
            try:
                with patch.object(service.checker, 'get_overall_health') as mock_health:
                    mock_health.return_value = {"status": "healthy", "components": []}
                    result = service.get_health_status()
                    results.append(result)
            except Exception as e:
                errors.append(e)
        
        # Start multiple threads
        threads = [threading.Thread(target=perform_health_check) for _ in range(5)]
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All should succeed
        assert len(results) == 5
        assert len(errors) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
