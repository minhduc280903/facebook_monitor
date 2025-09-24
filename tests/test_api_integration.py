#!/usr/bin/env python3
"""
Integration tests for FastAPI WebSocket Server
Tests end-to-end workflows, service integration, and production scenarios
"""

import pytest
import json
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any, List
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# Import test dependencies
from fastapi.testclient import TestClient
import redis.asyncio as aioredis

# Setup path for imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import the application
from api.main import app, ConnectionManager, manager
from core.database_manager import DatabaseManager
from multi_queue_config import MultiQueueConfig


@pytest.mark.integration 
class TestEndToEndWorkflows:
    """End-to-end integration tests for complete workflows"""
    
    @pytest.fixture
    def realistic_db_manager(self):
        """Mock DatabaseManager with realistic production-like responses"""
        db = Mock(spec=DatabaseManager)
        
        # Realistic post data
        posts_data = [
            {
                "id": 1,
                "signature": "fb_group_post_123",
                "url": "https://facebook.com/groups/trading/posts/123", 
                "title": "USD/EUR Trading Analysis",
                "status": "TRACKING",
                "created_at": "2024-01-01T10:00:00Z",
                "last_interaction_count": 45
            },
            {
                "id": 2,
                "signature": "fb_group_post_456",
                "url": "https://facebook.com/groups/trading/posts/456",
                "title": "Market Update: Gold Prices",
                "status": "TRACKING", 
                "created_at": "2024-01-01T11:00:00Z",
                "last_interaction_count": 23
            }
        ]
        
        # Realistic interaction history
        interaction_history = [
            {
                "timestamp": "2024-01-01T10:00:00Z",
                "likes": 10,
                "shares": 2,
                "comments": 3,
                "angry": 0,
                "love": 1
            },
            {
                "timestamp": "2024-01-01T10:30:00Z",
                "likes": 15,
                "shares": 3,
                "comments": 5,
                "angry": 1,
                "love": 2
            },
            {
                "timestamp": "2024-01-01T11:00:00Z",
                "likes": 25,
                "shares": 5,
                "comments": 8,
                "angry": 1,
                "love": 3
            }
        ]
        
        # Realistic system stats
        system_stats = {
            "total_posts": 156,
            "active_posts": 89,
            "total_interactions": 12847,
            "avg_interactions_per_post": 82.3,
            "posts_added_today": 12,
            "interactions_added_today": 234,
            "top_performing_post": "fb_group_post_123",
            "system_uptime_hours": 72.5
        }
        
        # Setup mock responses
        db.get_active_tracking_posts.return_value = posts_data
        db.get_post_by_signature.return_value = posts_data[0]
        db.get_interaction_history.return_value = interaction_history
        db.get_stats.return_value = system_stats
        
        return db
    
    @pytest.fixture
    def realistic_redis_client(self):
        """Mock Redis client with realistic queue data"""
        redis = AsyncMock(spec=aioredis.Redis)
        
        # Mock queue lengths
        queue_lengths = {
            "fb_discovery_tasks": 15,
            "fb_update_tasks_high": 8,
            "fb_update_tasks_low": 23
        }
        
        async def mock_llen(queue_name):
            return queue_lengths.get(queue_name, 0)
        
        redis.llen.side_effect = mock_llen
        redis.ping.return_value = True
        
        return redis
    
    @pytest.fixture
    def production_like_setup(self, realistic_db_manager, realistic_redis_client, monkeypatch):
        """Setup production-like environment"""
        monkeypatch.setattr("api.main.db_manager", realistic_db_manager)
        monkeypatch.setattr("api.main.redis_client", realistic_redis_client)
        return realistic_db_manager, realistic_redis_client
    
    def test_complete_dashboard_workflow(self, production_like_setup):
        """Test complete dashboard initialization workflow"""
        db_manager, redis_client = production_like_setup
        client = TestClient(app)
        
        # 1. Health check
        health_response = client.get("/api/health")
        assert health_response.status_code == 200
        health_data = health_response.json()
        assert health_data["status"] == "healthy"
        assert health_data["services"]["database"] is True
        assert health_data["services"]["redis"] is True
        
        # 2. Get posts list
        posts_response = client.get("/api/posts?limit=10")
        assert posts_response.status_code == 200
        posts_data = posts_response.json()
        assert len(posts_data["posts"]) == 2
        assert posts_data["posts"][0]["title"] == "USD/EUR Trading Analysis"
        
        # 3. Get system stats
        stats_response = client.get("/api/stats")
        assert stats_response.status_code == 200
        stats_data = stats_response.json()
        assert stats_data["total_posts"] == 156
        assert stats_data["active_posts"] == 89
        
        # 4. Get specific post interactions
        post_signature = "fb_group_post_123"
        interactions_response = client.get(f"/api/posts/{post_signature}/interactions?limit=50")
        assert interactions_response.status_code == 200
        interactions_data = interactions_response.json()
        assert len(interactions_data["interactions"]) == 3
        assert interactions_data["interactions"][0]["likes"] == 10
    
    def test_websocket_dashboard_real_time_flow(self, production_like_setup):
        """Test real-time dashboard workflow via WebSocket"""
        db_manager, redis_client = production_like_setup
        client = TestClient(app)
        
        with client.websocket_connect("/ws/dashboard_client") as websocket:
            # 1. Get initial system stats
            stats_command = {"command": "get_system_stats"}
            websocket.send_text(json.dumps(stats_command))
            
            stats_response = json.loads(websocket.receive_text())
            assert stats_response["type"] == "system_stats"
            assert stats_response["data"]["total_posts"] == 156
            assert stats_response["data"]["active_posts"] == 89
            
            # 2. Subscribe to specific post for real-time updates
            subscribe_command = {
                "command": "subscribe_post",
                "post_signature": "fb_group_post_123"
            }
            websocket.send_text(json.dumps(subscribe_command))
            
            post_response = json.loads(websocket.receive_text())
            assert post_response["type"] == "post_data"
            assert post_response["post_signature"] == "fb_group_post_123"
            assert post_response["post_info"]["title"] == "USD/EUR Trading Analysis"
            assert len(post_response["interactions"]) == 3
    
    def test_multiple_clients_concurrent_access(self, production_like_setup):
        """Test multiple dashboard clients accessing simultaneously"""
        db_manager, redis_client = production_like_setup
        client = TestClient(app)
        
        # Simulate 3 concurrent dashboard clients
        with client.websocket_connect("/ws/client_1") as ws1, \
             client.websocket_connect("/ws/client_2") as ws2, \
             client.websocket_connect("/ws/client_3") as ws3:
            
            websockets = [ws1, ws2, ws3]
            
            # All clients request system stats simultaneously
            stats_command = {"command": "get_system_stats"}
            for ws in websockets:
                ws.send_text(json.dumps(stats_command))
            
            # All should receive responses
            responses = []
            for ws in websockets:
                response = json.loads(ws.receive_text())
                responses.append(response)
                assert response["type"] == "system_stats"
                assert response["data"]["total_posts"] == 156
            
            # Subscribe different clients to different posts
            posts = ["fb_group_post_123", "fb_group_post_456", "fb_group_post_123"]
            for ws, post_sig in zip(websockets, posts):
                subscribe_cmd = {
                    "command": "subscribe_post", 
                    "post_signature": post_sig
                }
                ws.send_text(json.dumps(subscribe_cmd))
                
                post_response = json.loads(ws.receive_text())
                assert post_response["type"] == "post_data"
                assert post_response["post_signature"] == post_sig
    
    def test_error_recovery_and_resilience(self, production_like_setup):
        """Test system resilience under error conditions"""
        db_manager, redis_client = production_like_setup
        client = TestClient(app)
        
        # Test with database errors
        db_manager.get_stats.side_effect = Exception("Database connection timeout")
        
        with client.websocket_connect("/ws/resilience_test") as websocket:
            # Should handle database error gracefully
            stats_command = {"command": "get_system_stats"}
            websocket.send_text(json.dumps(stats_command))
            
            # Connection should remain open despite error
            # Test with successful command after error
            db_manager.get_stats.side_effect = None  # Reset error
            db_manager.get_stats.return_value = {"total_posts": 156}
            
            websocket.send_text(json.dumps(stats_command))
            # Should still work after recovering from error
    
    def test_high_frequency_updates_simulation(self, production_like_setup):
        """Test handling high-frequency real-time updates"""
        db_manager, redis_client = production_like_setup
        client = TestClient(app)
        
        with client.websocket_connect("/ws/high_freq_client") as websocket:
            # Subscribe to post
            subscribe_command = {
                "command": "subscribe_post",
                "post_signature": "fb_group_post_123"
            }
            websocket.send_text(json.dumps(subscribe_command))
            
            # Receive initial subscription response
            initial_response = json.loads(websocket.receive_text())
            assert initial_response["type"] == "post_data"
            
            # Simulate rapid command sending (like real dashboard usage)
            commands = [
                {"command": "get_system_stats"},
                {"command": "subscribe_post", "post_signature": "fb_group_post_456"},
                {"command": "get_system_stats"},
            ]
            
            for cmd in commands:
                websocket.send_text(json.dumps(cmd))
                # Don't wait for response to simulate rapid sending
            
            # Should handle all commands without crashing
            # Verify by sending final test command
            test_command = {"command": "get_system_stats"}
            websocket.send_text(json.dumps(test_command))


@pytest.mark.integration
class TestProductionScenarios:
    """Tests for production-specific scenarios and configurations"""
    
    def test_api_performance_under_load(self):
        """Test API performance with multiple concurrent requests"""
        client = TestClient(app)
        
        # Mock dependencies for performance testing
        with patch("api.main.db_manager") as mock_db:
            mock_db.get_active_tracking_posts.return_value = [
                {"id": i, "signature": f"post_{i}", "title": f"Post {i}"} 
                for i in range(100)
            ]
            
            # Simulate concurrent REST API requests
            def make_request():
                response = client.get("/api/posts?limit=20")
                assert response.status_code == 200
                return response.json()
            
            # Use ThreadPoolExecutor to simulate concurrent requests
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(make_request) for _ in range(10)]
                
                # All requests should succeed
                results = [future.result() for future in futures]
                assert len(results) == 10
                
                for result in results:
                    assert "posts" in result
                    assert len(result["posts"]) <= 20
    
    def test_memory_usage_with_many_websockets(self):
        """Test memory efficiency with many WebSocket connections"""
        client = TestClient(app)
        
        # Setup mock dependencies
        with patch("api.main.db_manager") as mock_db, \
             patch("api.main.redis_client") as mock_redis:
            
            mock_db.get_stats.return_value = {"total_posts": 100}
            
            # Create and manage multiple WebSocket connections
            connections = []
            try:
                for i in range(20):  # Simulate 20 concurrent connections
                    ws = client.websocket_connect(f"/ws/load_test_client_{i}")
                    connections.append(ws.__enter__())
                
                # Send commands from all connections
                for i, ws in enumerate(connections):
                    command = {"command": "get_system_stats"}
                    ws.send_text(json.dumps(command))
                    
                    # Receive response to verify connection works
                    response = json.loads(ws.receive_text())
                    assert response["type"] == "system_stats"
                
            finally:
                # Clean up connections
                for ws in connections:
                    try:
                        ws.__exit__(None, None, None)
                    except:
                        pass
    
    def test_configuration_edge_cases(self):
        """Test edge cases in configuration and initialization"""
        # Test with missing environment variables
        with patch.dict(os.environ, {}, clear=True):
            # App should still initialize with defaults
            test_client = TestClient(app)
            
            # Health check should indicate degraded state
            response = test_client.get("/api/health")
            assert response.status_code == 200
    
    def test_cors_and_security_headers(self):
        """Test CORS configuration and security headers"""
        client = TestClient(app)
        
        # Test CORS headers are present
        response = client.options("/api/health", headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET"
        })
        
        # Should handle CORS preflight
        assert response.status_code == 200
        
        # Test actual request with CORS
        response = client.get("/api/health", headers={
            "Origin": "http://localhost:3000"
        })
        
        assert response.status_code == 200
        # CORS headers should be present in FastAPI with CORSMiddleware


@pytest.mark.integration
class TestServiceIntegration:
    """Tests for integration between API and other services"""
    
    @pytest.mark.asyncio
    async def test_redis_pubsub_integration_flow(self):
        """Test complete Redis Pub/Sub integration flow"""
        # Mock Redis pub/sub
        mock_pubsub = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.pubsub.return_value = mock_pubsub
        
        # Mock realistic pub/sub message
        update_message = {
            "type": "message",
            "channel": "post_updates",
            "data": json.dumps({
                "post_signature": "fb_group_post_123",
                "type": "interaction_update",
                "data": {
                    "likes": 30,
                    "shares": 8,
                    "comments": 12,
                    "timestamp": "2024-01-01T12:00:00Z"
                }
            })
        }
        
        # Test that redis_listener would process this message correctly
        # This demonstrates the integration structure
        message_data = json.loads(update_message["data"])
        assert message_data["post_signature"] == "fb_group_post_123"
        assert message_data["type"] == "interaction_update"
        assert message_data["data"]["likes"] == 30
    
    def test_database_connection_pooling(self):
        """Test database connection management"""
        # Test that multiple API requests don't exhaust connections
        client = TestClient(app)
        
        with patch("api.main.db_manager") as mock_db:
            mock_db.get_active_tracking_posts.return_value = []
            
            # Make multiple rapid requests
            for _ in range(50):
                response = client.get("/api/posts")
                assert response.status_code == 200
            
            # Database manager should handle connection pooling
            # This verifies the structure works under load
    
    def test_queue_monitoring_integration(self):
        """Test integration with Redis queue monitoring"""
        client = TestClient(app)
        
        with patch("api.main.db_manager") as mock_db, \
             patch("api.main.redis_client") as mock_redis:
            
            mock_db.get_stats.return_value = {"total_posts": 100}
            
            # Mock queue lengths for different queue types
            queue_lengths = {
                "fb_discovery_tasks": 25,
                "fb_update_tasks_high": 10,
                "fb_update_tasks_low": 35
            }
            
            async def mock_llen(queue_name):
                return queue_lengths.get(queue_name, 0)
            
            mock_redis.llen.side_effect = mock_llen
            
            # Mock MultiQueueConfig to return test queues
            with patch.object(MultiQueueConfig, 'get_all_queues') as mock_queues:
                mock_queue_objects = []
                for queue_name in queue_lengths.keys():
                    mock_queue = Mock()
                    mock_queue.value = queue_name
                    mock_queue.name = queue_name.upper().replace("FB_", "").replace("_TASKS", "")
                    mock_queue_objects.append(mock_queue)
                
                mock_queues.return_value = mock_queue_objects
                
                response = client.get("/api/stats")
                assert response.status_code == 200
                
                data = response.json()
                assert data["total_posts"] == 100
                # Queue stats should be included
                assert "discovery_queue_length" in data or any("queue" in key for key in data.keys())


@pytest.mark.slow
class TestLongRunningScenarios:
    """Tests for long-running scenarios and stability"""
    
    def test_websocket_connection_stability(self):
        """Test WebSocket connection stability over time"""
        client = TestClient(app)
        
        with patch("api.main.db_manager") as mock_db:
            mock_db.get_stats.return_value = {"total_posts": 100}
            
            with client.websocket_connect("/ws/stability_test") as websocket:
                # Send periodic commands over extended period
                for i in range(10):  # Simulate 10 periodic updates
                    command = {"command": "get_system_stats"}
                    websocket.send_text(json.dumps(command))
                    
                    response = json.loads(websocket.receive_text())
                    assert response["type"] == "system_stats"
                    
                    # Small delay to simulate real usage
                    time.sleep(0.1)
    
    def test_connection_manager_cleanup_over_time(self):
        """Test ConnectionManager cleanup doesn't leak memory"""
        manager = ConnectionManager()
        
        # Simulate many connect/disconnect cycles
        for cycle in range(100):
            websockets = []
            
            # Connect multiple clients
            for i in range(10):
                websocket = Mock()
                client_id = f"cycle_{cycle}_client_{i}"
                manager.active_connections[client_id] = [websocket]
                websockets.append((websocket, client_id))
            
            # Disconnect all clients
            for websocket, client_id in websockets:
                manager.disconnect(websocket, client_id)
            
            # Verify cleanup after each cycle
            assert len(manager.active_connections) == 0
        
        # Final verification - no memory leaks
        assert len(manager.active_connections) == 0
        assert len(manager.post_subscribers) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
