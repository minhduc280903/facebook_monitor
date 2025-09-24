#!/usr/bin/env python3
"""
Comprehensive tests for FastAPI WebSocket Server (api/main.py)
Tests REST endpoints, WebSocket functionality, and integration components
"""

import pytest
import json
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any, List
from datetime import datetime, timezone

# Import FastAPI test dependencies
from fastapi.testclient import TestClient
from fastapi import HTTPException
import redis.asyncio as aioredis

# Setup path for imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import the application
from api.main import app, ConnectionManager, get_db, get_redis, manager
from core.database_manager import DatabaseManager
from multi_queue_config import MultiQueueConfig


@pytest.mark.unit
class TestConnectionManager:
    """Test cases for WebSocket ConnectionManager"""
    
    def test_init_connection_manager(self):
        """Test ConnectionManager initialization"""
        conn_manager = ConnectionManager()
        
        assert isinstance(conn_manager.active_connections, dict)
        assert isinstance(conn_manager.post_subscribers, dict)
        assert len(conn_manager.active_connections) == 0
        assert len(conn_manager.post_subscribers) == 0
    
    @pytest.mark.asyncio
    async def test_connect_websocket(self):
        """Test WebSocket connection acceptance"""
        conn_manager = ConnectionManager()
        mock_websocket = AsyncMock()
        client_id = "test_client_123"
        
        await conn_manager.connect(mock_websocket, client_id)
        
        # Verify websocket.accept() was called
        mock_websocket.accept.assert_called_once()
        
        # Verify client is tracked
        assert client_id in conn_manager.active_connections
        assert mock_websocket in conn_manager.active_connections[client_id]
    
    @pytest.mark.asyncio
    async def test_connect_multiple_connections_same_client(self):
        """Test multiple connections for same client"""
        conn_manager = ConnectionManager()
        mock_websocket1 = AsyncMock()
        mock_websocket2 = AsyncMock()
        client_id = "test_client_123"
        
        await conn_manager.connect(mock_websocket1, client_id)
        await conn_manager.connect(mock_websocket2, client_id)
        
        # Verify both connections tracked
        assert len(conn_manager.active_connections[client_id]) == 2
        assert mock_websocket1 in conn_manager.active_connections[client_id]
        assert mock_websocket2 in conn_manager.active_connections[client_id]
    
    def test_disconnect_websocket(self):
        """Test WebSocket disconnection"""
        conn_manager = ConnectionManager()
        mock_websocket = Mock()
        client_id = "test_client_123"
        
        # Setup initial connection
        conn_manager.active_connections[client_id] = [mock_websocket]
        conn_manager.post_subscribers["post_123"] = [mock_websocket]
        
        conn_manager.disconnect(mock_websocket, client_id)
        
        # Verify client removed
        assert client_id not in conn_manager.active_connections
        assert len(conn_manager.post_subscribers["post_123"]) == 0
    
    def test_disconnect_nonexistent_websocket(self):
        """Test disconnecting non-existent WebSocket"""
        conn_manager = ConnectionManager()
        mock_websocket = Mock()
        client_id = "nonexistent_client"
        
        # Should not raise exception
        conn_manager.disconnect(mock_websocket, client_id)
    
    @pytest.mark.asyncio
    async def test_subscribe_to_post(self):
        """Test subscribing WebSocket to specific post"""
        conn_manager = ConnectionManager()
        mock_websocket = AsyncMock()
        post_signature = "test_post_signature"
        
        await conn_manager.subscribe_to_post(mock_websocket, post_signature)
        
        # Verify subscription tracking
        assert post_signature in conn_manager.post_subscribers
        assert mock_websocket in conn_manager.post_subscribers[post_signature]
    
    @pytest.mark.asyncio
    async def test_send_to_post_subscribers(self):
        """Test broadcasting to post subscribers"""
        conn_manager = ConnectionManager()
        mock_websocket1 = AsyncMock()
        mock_websocket2 = AsyncMock()
        post_signature = "test_post_signature"
        message = {"type": "update", "data": "test"}
        
        # Setup subscribers
        conn_manager.post_subscribers[post_signature] = [mock_websocket1, mock_websocket2]
        
        await conn_manager.send_to_post_subscribers(post_signature, message)
        
        # Verify message sent to both subscribers
        mock_websocket1.send_text.assert_called_once_with(json.dumps(message))
        mock_websocket2.send_text.assert_called_once_with(json.dumps(message))
    
    @pytest.mark.asyncio
    async def test_send_to_post_subscribers_with_error(self):
        """Test broadcasting with WebSocket errors"""
        conn_manager = ConnectionManager()
        mock_websocket_good = AsyncMock()
        mock_websocket_bad = AsyncMock()
        mock_websocket_bad.send_text.side_effect = Exception("Connection closed")
        
        post_signature = "test_post_signature"
        message = {"type": "update", "data": "test"}
        
        # Setup subscribers
        conn_manager.post_subscribers[post_signature] = [mock_websocket_good, mock_websocket_bad]
        
        await conn_manager.send_to_post_subscribers(post_signature, message)
        
        # Verify good websocket received message
        mock_websocket_good.send_text.assert_called_once()
        # Bad websocket should be removed from subscribers
        assert mock_websocket_bad not in conn_manager.post_subscribers[post_signature]


@pytest.mark.unit
class TestRESTEndpoints:
    """Test cases for REST API endpoints"""
    
    @pytest.fixture
    def client(self):
        """Test client fixture"""
        return TestClient(app)
    
    @pytest.fixture
    def mock_db(self):
        """Mock DatabaseManager fixture"""
        return Mock(spec=DatabaseManager)
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client fixture"""
        return AsyncMock(spec=aioredis.Redis)
    
    def test_health_check_healthy(self, client, monkeypatch):
        """Test health check endpoint when all services healthy"""
        # Mock global variables
        mock_db = Mock()
        mock_redis = Mock()
        
        monkeypatch.setattr("api.main.db_manager", mock_db)
        monkeypatch.setattr("api.main.redis_client", mock_redis)
        
        response = client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "healthy"
        assert data["services"]["database"] is True
        assert data["services"]["redis"] is True
        assert "timestamp" in data
    
    def test_health_check_degraded(self, client, monkeypatch):
        """Test health check endpoint when services unavailable"""
        # Mock global variables as None
        monkeypatch.setattr("api.main.db_manager", None)
        monkeypatch.setattr("api.main.redis_client", None)
        
        response = client.get("/api/health")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "degraded"
        assert data["services"]["database"] is False
        assert data["services"]["redis"] is False
    
    def test_get_posts_success(self, client, mock_db):
        """Test getting posts endpoint success"""
        # Mock data
        mock_posts = [
            {"id": 1, "signature": "post_1", "url": "https://facebook.com/post1"},
            {"id": 2, "signature": "post_2", "url": "https://facebook.com/post2"}
        ]
        mock_db.get_active_tracking_posts.return_value = mock_posts
        
        # Mock dependency
        app.dependency_overrides[get_db] = lambda: mock_db
        
        try:
            response = client.get("/api/posts")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "posts" in data
            assert len(data["posts"]) == 2
            assert data["posts"][0]["signature"] == "post_1"
            
            # Verify database method called
            mock_db.get_active_tracking_posts.assert_called_once()
            
        finally:
            app.dependency_overrides.clear()
    
    def test_get_posts_with_limit(self, client, mock_db):
        """Test getting posts with limit parameter"""
        # Mock large dataset
        mock_posts = [{"id": i, "signature": f"post_{i}"} for i in range(100)]
        mock_db.get_active_tracking_posts.return_value = mock_posts
        
        app.dependency_overrides[get_db] = lambda: mock_db
        
        try:
            response = client.get("/api/posts?limit=5")
            
            assert response.status_code == 200
            data = response.json()
            
            # Should only return 5 posts
            assert len(data["posts"]) == 5
            
        finally:
            app.dependency_overrides.clear()
    
    def test_get_posts_database_error(self, client, mock_db):
        """Test getting posts with database error"""
        mock_db.get_active_tracking_posts.side_effect = Exception("Database error")
        
        app.dependency_overrides[get_db] = lambda: mock_db
        
        try:
            response = client.get("/api/posts")
            
            assert response.status_code == 500
            data = response.json()
            assert "Database error" in data["detail"]
            
        finally:
            app.dependency_overrides.clear()
    
    def test_get_post_interactions_success(self, client, mock_db):
        """Test getting post interactions endpoint success"""
        post_signature = "test_post_signature"
        mock_interactions = [
            {"timestamp": "2024-01-01T12:00:00Z", "likes": 10, "shares": 5},
            {"timestamp": "2024-01-01T13:00:00Z", "likes": 15, "shares": 7}
        ]
        mock_db.get_interaction_history.return_value = mock_interactions
        
        app.dependency_overrides[get_db] = lambda: mock_db
        
        try:
            response = client.get(f"/api/posts/{post_signature}/interactions")
            
            assert response.status_code == 200
            data = response.json()
            
            assert "interactions" in data
            assert len(data["interactions"]) == 2
            assert data["interactions"][0]["likes"] == 10
            
            # Verify correct parameters passed
            mock_db.get_interaction_history.assert_called_once_with(post_signature, limit=100)
            
        finally:
            app.dependency_overrides.clear()
    
    def test_get_post_interactions_with_limit(self, client, mock_db):
        """Test getting post interactions with custom limit"""
        post_signature = "test_post_signature"
        mock_interactions = [{"id": i} for i in range(50)]
        mock_db.get_interaction_history.return_value = mock_interactions
        
        app.dependency_overrides[get_db] = lambda: mock_db
        
        try:
            response = client.get(f"/api/posts/{post_signature}/interactions?limit=25")
            
            assert response.status_code == 200
            
            # Verify limit parameter passed correctly
            mock_db.get_interaction_history.assert_called_once_with(post_signature, limit=25)
            
        finally:
            app.dependency_overrides.clear()
    
    @pytest.mark.asyncio
    async def test_get_system_stats_success(self, client, mock_db, mock_redis):
        """Test getting system stats endpoint success"""
        # Mock database stats
        mock_stats = {
            "total_posts": 100,
            "active_posts": 50,
            "total_interactions": 5000
        }
        mock_db.get_stats.return_value = mock_stats
        
        # Mock Redis queue lengths
        mock_redis.llen.return_value = 10
        
        # Mock MultiQueueConfig
        mock_queue_enum = Mock()
        mock_queue_enum.value = "test_queue"
        mock_queue_enum.name = "TEST"
        
        app.dependency_overrides[get_db] = lambda: mock_db
        app.dependency_overrides[get_redis] = lambda: mock_redis
        
        with patch.object(MultiQueueConfig, 'get_all_queues', return_value=[mock_queue_enum]):
            try:
                response = client.get("/api/stats")
                
                assert response.status_code == 200
                data = response.json()
                
                assert data["total_posts"] == 100
                assert data["active_posts"] == 50
                assert data["total_interactions"] == 5000
                assert "test_queue_length" in data
                
            finally:
                app.dependency_overrides.clear()


@pytest.mark.integration
class TestWebSocketIntegration:
    """Integration tests for WebSocket functionality"""
    
    @pytest.fixture
    def mock_app_dependencies(self, monkeypatch):
        """Mock app-level dependencies"""
        mock_db = Mock(spec=DatabaseManager)
        mock_redis = AsyncMock(spec=aioredis.Redis)
        
        monkeypatch.setattr("api.main.db_manager", mock_db)
        monkeypatch.setattr("api.main.redis_client", mock_redis)
        
        return mock_db, mock_redis
    
    def test_websocket_connection(self, mock_app_dependencies):
        """Test WebSocket connection establishment"""
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test_client") as websocket:
            # Connection should be established
            assert websocket is not None
    
    def test_websocket_subscribe_post_command(self, mock_app_dependencies):
        """Test WebSocket subscribe_post command"""
        mock_db, mock_redis = mock_app_dependencies
        
        # Mock database responses
        mock_post_data = {"id": 1, "signature": "test_post", "url": "https://facebook.com/post"}
        mock_interactions = [{"timestamp": "2024-01-01T12:00:00Z", "likes": 10}]
        
        mock_db.get_post_by_signature.return_value = mock_post_data
        mock_db.get_interaction_history.return_value = mock_interactions
        
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test_client") as websocket:
            # Send subscribe command
            command = {
                "command": "subscribe_post",
                "post_signature": "test_post"
            }
            websocket.send_text(json.dumps(command))
            
            # Receive response
            response = websocket.receive_text()
            data = json.loads(response)
            
            assert data["type"] == "post_data"
            assert data["post_signature"] == "test_post"
            assert data["post_info"] == mock_post_data
            assert data["interactions"] == mock_interactions
    
    def test_websocket_get_system_stats_command(self, mock_app_dependencies):
        """Test WebSocket get_system_stats command"""
        mock_db, mock_redis = mock_app_dependencies
        
        # Mock database stats
        mock_stats = {"total_posts": 100, "active_posts": 50}
        mock_db.get_stats.return_value = mock_stats
        
        # Mock Redis queue length
        mock_redis.llen.return_value = 5
        
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test_client") as websocket:
            # Send stats command
            command = {"command": "get_system_stats"}
            websocket.send_text(json.dumps(command))
            
            # Receive response
            response = websocket.receive_text()
            data = json.loads(response)
            
            assert data["type"] == "system_stats"
            assert data["data"]["total_posts"] == 100
            assert data["data"]["active_posts"] == 50
    
    def test_websocket_invalid_json(self, mock_app_dependencies):
        """Test WebSocket with invalid JSON"""
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test_client") as websocket:
            # Send invalid JSON
            websocket.send_text("invalid json")
            
            # Connection should remain open despite error
            # Try sending valid command to verify
            command = {"command": "get_system_stats"}
            websocket.send_text(json.dumps(command))
    
    def test_websocket_unknown_command(self, mock_app_dependencies):
        """Test WebSocket with unknown command"""
        client = TestClient(app)
        
        with client.websocket_connect("/ws/test_client") as websocket:
            # Send unknown command
            command = {"command": "unknown_command"}
            websocket.send_text(json.dumps(command))
            
            # Connection should remain open
            # Try sending valid command to verify
            valid_command = {"command": "get_system_stats"}
            websocket.send_text(json.dumps(valid_command))


@pytest.mark.unit
class TestDependencyFunctions:
    """Test dependency injection functions"""
    
    def test_get_db_with_manager(self, monkeypatch):
        """Test get_db dependency when manager available"""
        mock_db = Mock(spec=DatabaseManager)
        monkeypatch.setattr("api.main.db_manager", mock_db)
        
        result = get_db()
        assert result is mock_db
    
    def test_get_db_without_manager(self, monkeypatch):
        """Test get_db dependency when manager unavailable"""
        monkeypatch.setattr("api.main.db_manager", None)
        
        with pytest.raises(HTTPException) as exc_info:
            get_db()
        
        assert exc_info.value.status_code == 503
        assert "Database unavailable" in exc_info.value.detail
    
    def test_get_redis_with_client(self, monkeypatch):
        """Test get_redis dependency when client available"""
        mock_redis = Mock(spec=aioredis.Redis)
        monkeypatch.setattr("api.main.redis_client", mock_redis)
        
        result = get_redis()
        assert result is mock_redis
    
    def test_get_redis_without_client(self, monkeypatch):
        """Test get_redis dependency when client unavailable"""
        monkeypatch.setattr("api.main.redis_client", None)
        
        with pytest.raises(HTTPException) as exc_info:
            get_redis()
        
        assert exc_info.value.status_code == 503
        assert "Redis unavailable" in exc_info.value.detail


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
