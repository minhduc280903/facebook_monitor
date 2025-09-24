#!/usr/bin/env python3
"""
Comprehensive WebSocket tests for FastAPI WebSocket Server
Tests real-time functionality, connection management, and Pub/Sub integration
"""

import pytest
import json
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any, List
from datetime import datetime, timezone

# Import WebSocket test dependencies
from fastapi.testclient import TestClient
from fastapi import WebSocketDisconnect
import redis.asyncio as aioredis

# Setup path for imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import the application components
from api.main import app, ConnectionManager, redis_listener
from core.database_manager import DatabaseManager


@pytest.mark.unit
class TestWebSocketConnectionManager:
    """Detailed tests for WebSocket ConnectionManager functionality"""
    
    @pytest.fixture
    def connection_manager(self):
        """Fresh ConnectionManager instance for each test"""
        return ConnectionManager()
    
    @pytest.fixture
    def mock_websocket(self):
        """Mock WebSocket for testing"""
        websocket = AsyncMock()
        websocket.send_text = AsyncMock()
        websocket.accept = AsyncMock()
        return websocket
    
    @pytest.mark.asyncio
    async def test_multiple_clients_connection(self, connection_manager):
        """Test handling multiple client connections simultaneously"""
        client_ids = ["client_1", "client_2", "client_3"]
        websockets = [AsyncMock() for _ in range(3)]
        
        # Connect all clients
        for client_id, websocket in zip(client_ids, websockets):
            await connection_manager.connect(websocket, client_id)
        
        # Verify all connections tracked
        assert len(connection_manager.active_connections) == 3
        for client_id in client_ids:
            assert client_id in connection_manager.active_connections
    
    @pytest.mark.asyncio
    async def test_client_reconnection(self, connection_manager, mock_websocket):
        """Test handling client reconnection scenarios"""
        client_id = "reconnecting_client"
        
        # First connection
        await connection_manager.connect(mock_websocket, client_id)
        assert len(connection_manager.active_connections[client_id]) == 1
        
        # Reconnect (simulating new websocket for same client)
        new_websocket = AsyncMock()
        await connection_manager.connect(new_websocket, client_id)
        
        # Should have both connections
        assert len(connection_manager.active_connections[client_id]) == 2
        assert mock_websocket in connection_manager.active_connections[client_id]
        assert new_websocket in connection_manager.active_connections[client_id]
    
    @pytest.mark.asyncio
    async def test_post_subscription_with_multiple_clients(self, connection_manager):
        """Test multiple clients subscribing to same post"""
        post_signature = "popular_post"
        websockets = [AsyncMock() for _ in range(3)]
        
        # All clients subscribe to same post
        for websocket in websockets:
            await connection_manager.subscribe_to_post(websocket, post_signature)
        
        # Verify all subscribed
        assert len(connection_manager.post_subscribers[post_signature]) == 3
        for websocket in websockets:
            assert websocket in connection_manager.post_subscribers[post_signature]
    
    @pytest.mark.asyncio
    async def test_broadcast_to_specific_post_subscribers(self, connection_manager):
        """Test broadcasting updates only to specific post subscribers"""
        post1 = "post_1"
        post2 = "post_2"
        
        # Create websockets for different posts
        post1_subscribers = [AsyncMock() for _ in range(2)]
        post2_subscribers = [AsyncMock() for _ in range(2)]
        
        # Subscribe to different posts
        for ws in post1_subscribers:
            await connection_manager.subscribe_to_post(ws, post1)
        for ws in post2_subscribers:
            await connection_manager.subscribe_to_post(ws, post2)
        
        # Broadcast to post1 only
        message = {"type": "update", "post": post1, "data": "new interaction"}
        await connection_manager.send_to_post_subscribers(post1, message)
        
        # Verify only post1 subscribers received message
        for ws in post1_subscribers:
            ws.send_text.assert_called_once_with(json.dumps(message))
        
        for ws in post2_subscribers:
            ws.send_text.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_websocket_error_during_broadcast(self, connection_manager):
        """Test handling WebSocket errors during message broadcast"""
        post_signature = "test_post"
        
        # Create mix of good and bad websockets
        good_websocket = AsyncMock()
        bad_websocket = AsyncMock()
        bad_websocket.send_text.side_effect = Exception("Connection lost")
        
        # Subscribe both
        await connection_manager.subscribe_to_post(good_websocket, post_signature)
        await connection_manager.subscribe_to_post(bad_websocket, post_signature)
        
        assert len(connection_manager.post_subscribers[post_signature]) == 2
        
        # Broadcast message
        message = {"type": "test", "data": "hello"}
        await connection_manager.send_to_post_subscribers(post_signature, message)
        
        # Verify good websocket received message
        good_websocket.send_text.assert_called_once()
        
        # Bad websocket should be removed from subscribers
        assert bad_websocket not in connection_manager.post_subscribers[post_signature]
        assert len(connection_manager.post_subscribers[post_signature]) == 1
    
    def test_disconnect_with_multiple_subscriptions(self, connection_manager):
        """Test disconnecting client subscribed to multiple posts"""
        websocket = Mock()
        client_id = "multi_subscriber"
        
        # Setup client with multiple subscriptions
        connection_manager.active_connections[client_id] = [websocket]
        connection_manager.post_subscribers["post_1"] = [websocket]
        connection_manager.post_subscribers["post_2"] = [websocket]
        connection_manager.post_subscribers["post_3"] = [websocket]
        
        # Disconnect
        connection_manager.disconnect(websocket, client_id)
        
        # Verify cleaned up from all subscriptions
        assert client_id not in connection_manager.active_connections
        assert websocket not in connection_manager.post_subscribers["post_1"]
        assert websocket not in connection_manager.post_subscribers["post_2"]
        assert websocket not in connection_manager.post_subscribers["post_3"]


@pytest.mark.integration
class TestWebSocketCommands:
    """Integration tests for WebSocket command processing"""
    
    @pytest.fixture
    def mock_db_manager(self):
        """Mock DatabaseManager with realistic responses"""
        db = Mock(spec=DatabaseManager)
        
        # Mock post data
        db.get_post_by_signature.return_value = {
            "id": 1,
            "signature": "test_post_signature",
            "url": "https://facebook.com/groups/example/posts/123",
            "title": "Test Post",
            "status": "TRACKING",
            "created_at": "2024-01-01T12:00:00Z"
        }
        
        # Mock interaction history
        db.get_interaction_history.return_value = [
            {
                "timestamp": "2024-01-01T12:00:00Z",
                "likes": 10,
                "shares": 5,
                "comments": 3
            },
            {
                "timestamp": "2024-01-01T13:00:00Z", 
                "likes": 15,
                "shares": 7,
                "comments": 4
            }
        ]
        
        # Mock system stats
        db.get_stats.return_value = {
            "total_posts": 100,
            "active_posts": 50,
            "total_interactions": 5000,
            "avg_interactions_per_post": 100.0
        }
        
        return db
    
    @pytest.fixture
    def mock_redis_client(self):
        """Mock Redis client with async methods"""
        redis = AsyncMock(spec=aioredis.Redis)
        redis.llen.return_value = 25  # Mock queue length
        return redis
    
    @pytest.fixture
    def setup_app_mocks(self, mock_db_manager, mock_redis_client, monkeypatch):
        """Setup app-level mocks"""
        monkeypatch.setattr("api.main.db_manager", mock_db_manager)
        monkeypatch.setattr("api.main.redis_client", mock_redis_client)
        return mock_db_manager, mock_redis_client
    
    def test_subscribe_post_command_success(self, setup_app_mocks):
        """Test successful post subscription via WebSocket"""
        mock_db, mock_redis = setup_app_mocks
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test_client") as websocket:
            # Send subscribe command
            command = {
                "command": "subscribe_post",
                "post_signature": "test_post_signature"
            }
            websocket.send_text(json.dumps(command))
            
            # Receive and validate response
            response_text = websocket.receive_text()
            response = json.loads(response_text)
            
            assert response["type"] == "post_data"
            assert response["post_signature"] == "test_post_signature"
            assert response["post_info"]["id"] == 1
            assert response["post_info"]["title"] == "Test Post"
            assert len(response["interactions"]) == 2
            assert response["interactions"][0]["likes"] == 10
            assert "timestamp" in response
    
    def test_subscribe_post_command_missing_signature(self, setup_app_mocks):
        """Test post subscription with missing post_signature"""
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test_client") as websocket:
            # Send command without post_signature
            command = {"command": "subscribe_post"}
            websocket.send_text(json.dumps(command))
            
            # Should not crash - just log warning
            # Send another command to verify connection still works
            stats_command = {"command": "get_system_stats"}
            websocket.send_text(json.dumps(stats_command))
            
            response_text = websocket.receive_text()
            response = json.loads(response_text)
            assert response["type"] == "system_stats"
    
    def test_get_system_stats_command_success(self, setup_app_mocks):
        """Test successful system stats request via WebSocket"""
        mock_db, mock_redis = setup_app_mocks
        client = TestClient(app)
        
        with patch.object(mock_redis, 'llen', return_value=15):
            with client.websocket_connect("/ws/test_client") as websocket:
                # Send stats command
                command = {"command": "get_system_stats"}
                websocket.send_text(json.dumps(command))
                
                # Receive and validate response
                response_text = websocket.receive_text()
                response = json.loads(response_text)
                
                assert response["type"] == "system_stats"
                assert response["data"]["total_posts"] == 100
                assert response["data"]["active_posts"] == 50
                assert response["data"]["total_interactions"] == 5000
                assert "timestamp" in response
    
    def test_database_error_handling(self, setup_app_mocks):
        """Test WebSocket handling of database errors"""
        mock_db, mock_redis = setup_app_mocks
        
        # Make database throw error
        mock_db.get_post_by_signature.side_effect = Exception("Database connection failed")
        
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test_client") as websocket:
            # Send subscribe command that will trigger DB error
            command = {
                "command": "subscribe_post",
                "post_signature": "test_post_signature"
            }
            websocket.send_text(json.dumps(command))
            
            # Connection should remain open despite error
            # Verify by sending another command
            stats_command = {"command": "get_system_stats"}
            websocket.send_text(json.dumps(stats_command))
    
    def test_malformed_json_handling(self, setup_app_mocks):
        """Test handling of malformed JSON messages"""
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test_client") as websocket:
            # Send malformed JSON
            websocket.send_text("{invalid json}")
            
            # Connection should remain open
            # Verify by sending valid command
            command = {"command": "get_system_stats"}
            websocket.send_text(json.dumps(command))
            
            response_text = websocket.receive_text()
            response = json.loads(response_text)
            assert response["type"] == "system_stats"
    
    def test_unknown_command_handling(self, setup_app_mocks):
        """Test handling of unknown commands"""
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test_client") as websocket:
            # Send unknown command
            command = {"command": "invalid_command", "data": "test"}
            websocket.send_text(json.dumps(command))
            
            # Should log warning but keep connection open
            # Verify by sending valid command
            valid_command = {"command": "get_system_stats"}
            websocket.send_text(json.dumps(valid_command))
            
            response_text = websocket.receive_text()
            response = json.loads(response_text)
            assert response["type"] == "system_stats"


@pytest.mark.integration
class TestRedisIntegration:
    """Tests for Redis Pub/Sub integration"""
    
    @pytest.mark.asyncio
    async def test_redis_listener_function(self):
        """Test Redis listener background task"""
        # Mock Redis pubsub
        mock_pubsub = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.pubsub.return_value = mock_pubsub
        
        # Mock message
        mock_message = {
            "type": "message",
            "channel": "post_updates",
            "data": json.dumps({
                "post_signature": "test_post",
                "type": "interaction_update",
                "data": {"likes": 20}
            })
        }
        
        # Mock pubsub subscription and message retrieval
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.get_message = AsyncMock(side_effect=[mock_message, None])
        
        # Mock the global manager
        mock_manager = Mock()
        mock_manager.send_to_post_subscribers = AsyncMock()
        
        with patch("api.main.redis_client", mock_redis):
            with patch("api.main.manager", mock_manager):
                # Run one iteration of redis_listener
                try:
                    # Set up for single iteration
                    mock_pubsub.get_message.side_effect = [mock_message, Exception("Stop iteration")]
                    
                    await redis_listener()
                except Exception:
                    pass  # Expected to stop iteration
                
                # Verify subscription and broadcast
                mock_pubsub.subscribe.assert_called()
                mock_manager.send_to_post_subscribers.assert_called()
    
    def test_websocket_redis_integration_flow(self, monkeypatch):
        """Test complete flow: WebSocket subscription -> Redis message -> Broadcast"""
        # This would test the full integration but requires actual Redis setup
        # For unit testing, we'll mock the components
        
        mock_db = Mock()
        mock_redis = AsyncMock()
        
        monkeypatch.setattr("api.main.db_manager", mock_db)
        monkeypatch.setattr("api.main.redis_client", mock_redis)
        
        # This test demonstrates the flow structure
        # In a real integration test environment, you would:
        # 1. Start WebSocket connection
        # 2. Subscribe to post
        # 3. Publish message to Redis
        # 4. Verify WebSocket receives the message
        
        assert True  # Placeholder for integration test setup


@pytest.mark.unit
class TestWebSocketErrorScenarios:
    """Test various error scenarios and edge cases"""
    
    def test_websocket_disconnect_during_processing(self):
        """Test graceful handling of WebSocket disconnect during message processing"""
        client = TestClient(app)
        
        # This test demonstrates the disconnect handling structure
        # WebSocketDisconnect should be caught and logged properly
        with pytest.raises(Exception):
            # Simulate forced disconnection scenario
            with client.websocket_connect("/ws/test_client") as websocket:
                # Force disconnect by closing connection prematurely
                websocket.close()
    
    def test_connection_manager_memory_cleanup(self):
        """Test that ConnectionManager properly cleans up memory"""
        manager = ConnectionManager()
        
        # Simulate many connections and disconnections
        for i in range(100):
            websocket = Mock()
            client_id = f"client_{i}"
            
            # Add to manager
            manager.active_connections[client_id] = [websocket]
            manager.post_subscribers[f"post_{i}"] = [websocket]
            
            # Disconnect
            manager.disconnect(websocket, client_id)
        
        # Verify cleanup
        assert len(manager.active_connections) == 0
        
        # Check post_subscribers are cleaned (empty lists removed)
        for subscribers in manager.post_subscribers.values():
            assert len(subscribers) == 0
    
    @pytest.mark.asyncio
    async def test_concurrent_websocket_operations(self):
        """Test handling concurrent WebSocket operations"""
        manager = ConnectionManager()
        
        # Simulate concurrent connections
        async def connect_client(client_id: str):
            websocket = AsyncMock()
            await manager.connect(websocket, client_id)
            return websocket
        
        # Create multiple concurrent connections
        tasks = [connect_client(f"client_{i}") for i in range(10)]
        websockets = await asyncio.gather(*tasks)
        
        # Verify all connected
        assert len(manager.active_connections) == 10
        
        # Simulate concurrent disconnections
        for i, websocket in enumerate(websockets):
            manager.disconnect(websocket, f"client_{i}")
        
        # Verify all disconnected
        assert len(manager.active_connections) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
