#!/usr/bin/env python3
"""
FastAPI WebSocket Server for Real-time Facebook Post Monitor
Cung cấp WebSocket endpoints cho real-time dashboard updates

Vai trò:
- WebSocket server cho real-time data streaming
- RESTful API endpoints cho historical data
- Integration với Redis Pub/Sub cho event notifications
- Tái sử dụng DatabaseManager cho data access
"""

import asyncio
import json
import logging
import redis.asyncio as redis
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

# Import database và business logic
import sys
import os
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# Import after sys.path modification
from logging_config import get_logger, setup_application_logging
from core.database_manager import DatabaseManager
# MIGRATION: Removed multi_queue_config dependency - now using Celery
from config import settings  # <--- IMPORT SETTINGS

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
)
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Initialize centralized logging for API
setup_application_logging()
logger = get_logger(__name__)

# Global variables
redis_client: Optional[redis.Redis] = None
db_manager: Optional[DatabaseManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager cho FastAPI app"""
    global redis_client, db_manager
    
    # Startup
    logger.info("🚀 Starting FastAPI WebSocket server...")
    
    # Initialize Redis connection from settings
    try:
        redis_url = f"redis://{settings.redis.host}:{settings.redis.port}"
        logger.info(f"Connecting to Redis at {redis_url}")
        redis_client = redis.from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        logger.info("✅ Redis connection established")
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        redis_client = None
    
    # Initialize Database Manager
    try:
        db_manager = DatabaseManager()
        logger.info("✅ Database Manager initialized")
    except Exception as e:
        logger.error(f"❌ Database Manager initialization failed: {e}")
        db_manager = None
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down FastAPI server...")
    if redis_client:
        await redis_client.close()
    if db_manager:
        db_manager.close()


# Initialize FastAPI app với lifespan
app = FastAPI(
    title="Facebook Post Monitor API",
    description="Real-time WebSocket API for Facebook Post Monitor Dashboard",
    version="3.1.0",
    lifespan=lifespan
)

# CORS middleware để frontend có thể connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Trong production nên restrict specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connection manager
class ConnectionManager:
    """Quản lý WebSocket connections"""
    
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.post_subscribers: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        """Accept connection và track client"""
        await websocket.accept()
        
        if client_id not in self.active_connections:
            self.active_connections[client_id] = []
        
        self.active_connections[client_id].append(websocket)
        logger.info(f"🔌 Client {client_id} connected")
    
    def disconnect(self, websocket: WebSocket, client_id: str):
        """Remove connection khi client disconnect"""
        if client_id in self.active_connections:
            try:
                self.active_connections[client_id].remove(websocket)
                if not self.active_connections[client_id]:
                    del self.active_connections[client_id]
            except ValueError:
                pass
        
        # Remove từ post subscribers
        for post_sig, subscribers in self.post_subscribers.items():
            try:
                subscribers.remove(websocket)
            except ValueError:
                pass
        
        logger.info(f"🔌 Client {client_id} disconnected")
    
    async def subscribe_to_post(self, websocket: WebSocket, post_signature: str):
        """Subscribe client đến updates của specific post"""
        if post_signature not in self.post_subscribers:
            self.post_subscribers[post_signature] = []
        
        if websocket not in self.post_subscribers[post_signature]:
            self.post_subscribers[post_signature].append(websocket)
        
        logger.info(f"📊 Client subscribed to post: {post_signature[:20]}...")
    
    async def broadcast_to_post_subscribers(self, post_signature: str, data: Dict[str, Any]):
        """Broadcast data đến tất cả subscribers của một post"""
        if post_signature not in self.post_subscribers:
            return
        
        message = json.dumps({
            "type": "post_update",
            "post_signature": post_signature,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        disconnected = []
        for websocket in self.post_subscribers[post_signature]:
            try:
                await websocket.send_text(message)
            except Exception as e:
                logger.warning(f"⚠️ Failed to send to subscriber: {e}")
                disconnected.append(websocket)
        
        # Remove disconnected clients
        for ws in disconnected:
            try:
                self.post_subscribers[post_signature].remove(ws)
            except ValueError:
                pass
        
        if disconnected:
            logger.info(f"🧹 Removed {len(disconnected)} disconnected subscribers")
    
    async def broadcast_system_stats(self, stats: Dict[str, Any]):
        """Broadcast system statistics đến tất cả clients"""
        message = json.dumps({
            "type": "system_stats",
            "data": stats,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        disconnected = []
        for client_id, connections in self.active_connections.items():
            for websocket in connections:
                try:
                    await websocket.send_text(message)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to send stats to {client_id}: {e}")
                    disconnected.append((client_id, websocket))
        
        # Remove disconnected clients
        for client_id, ws in disconnected:
            self.disconnect(ws, client_id)


# Global connection manager
manager = ConnectionManager()


# Dependency để get database manager
def get_db() -> DatabaseManager:
    """Dependency injection cho database manager"""
    if db_manager is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return db_manager


def get_redis() -> redis.Redis:
    """Dependency injection cho Redis client"""
    if redis_client is None:
        raise HTTPException(status_code=503, detail="Redis not available")
    return redis_client


# WebSocket endpoints
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    Main WebSocket endpoint cho real-time updates
    
    Client có thể send commands để subscribe posts hoặc request data
    """
    await manager.connect(websocket, client_id)
    
    try:
        while True:
            # Receive message từ client
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                command = message.get("command")
                
                if command == "subscribe_post":
                    # Client muốn subscribe đến specific post
                    post_signature = message.get("post_signature")
                    if post_signature:
                        await manager.subscribe_to_post(websocket, post_signature)
                        
                        # Send current data cho post đó
                        if db_manager:
                            try:
                                post_data = db_manager.get_post_by_signature(post_signature)
                                interaction_history = db_manager.get_interaction_history(post_signature, limit=50)
                                
                                response = {
                                    "type": "post_data",
                                    "post_signature": post_signature,
                                    "post_info": post_data,
                                    "interactions": interaction_history,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                }
                                
                                await websocket.send_text(json.dumps(response))
                                
                            except Exception as e:
                                logger.error(f"❌ Error getting post data: {e}")
                
                elif command == "get_system_stats":
                    # Client request system statistics
                    if db_manager:
                        try:
                            stats = db_manager.get_stats()
                            
                            # Add Celery queue stats if Redis available
                            if redis_client:
                                try:
                                    # MIGRATION: Updated to use Celery queue names
                                    celery_queues = ["scan_high", "scan_normal", "discovery", "maintenance"]
                                    for queue_name in celery_queues:
                                        queue_length = await redis_client.llen(queue_name)
                                        stats[f"{queue_name}_queue_length"] = queue_length
                                except Exception as e:
                                    logger.warning(f"⚠️ Could not get queue stats: {e}")
                            
                            response = {
                                "type": "system_stats",
                                "data": stats,
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }
                            
                            await websocket.send_text(json.dumps(response))
                            
                        except Exception as e:
                            logger.error(f"❌ Error getting system stats: {e}")
                
                else:
                    logger.warning(f"⚠️ Unknown command: {command}")
                    
            except json.JSONDecodeError:
                logger.warning(f"⚠️ Invalid JSON from client {client_id}")
            except Exception as e:
                logger.error(f"❌ Error processing message from {client_id}: {e}")
                
    except WebSocketDisconnect:
        logger.info(f"🔌 Client {client_id} disconnected normally")
    except Exception as e:
        logger.error(f"❌ WebSocket error for {client_id}: {e}")
    finally:
        manager.disconnect(websocket, client_id)


# REST API endpoints
@app.get("/api/posts")
async def get_posts(
    limit: int = 50,
    status: str = "TRACKING",
    db: DatabaseManager = Depends(get_db)
):
    """Get danh sách posts"""
    try:
        if status == "TRACKING":
            posts = db.get_active_tracking_posts()
        else:
            # Có thể extend để support other status
            posts = db.get_active_tracking_posts()
        
        return {"posts": posts[:limit]}
        
    except Exception as e:
        logger.error(f"❌ Error getting posts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/posts/{post_signature}/interactions")
async def get_post_interactions(
    post_signature: str,
    limit: int = 100,
    db: DatabaseManager = Depends(get_db)
):
    """Get interaction history cho specific post"""
    try:
        interactions = db.get_interaction_history(post_signature, limit=limit)
        post_info = db.get_post_by_signature(post_signature)
        
        return {
            "post_signature": post_signature,
            "post_info": post_info,
            "interactions": interactions,
            "count": len(interactions)
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting interactions for {post_signature}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_system_stats(
    db: DatabaseManager = Depends(get_db),
    redis: redis.Redis = Depends(get_redis)
):
    """Get system statistics"""
    try:
        stats = db.get_stats()
        
        # Add Celery queue stats
        # MIGRATION: Updated to use Celery queue names
        celery_queues = ["scan_high", "scan_normal", "discovery", "maintenance"]
        for queue_name in celery_queues:
            try:
                queue_length = await redis.llen(queue_name)
                stats[f"{queue_name}_queue_length"] = queue_length
            except Exception:
                stats[f"{queue_name}_queue_length"] = 0
        
        return {"stats": stats}
        
    except Exception as e:
        logger.error(f"❌ Error getting system stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    health = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "database": db_manager is not None,
            "redis": redis_client is not None
        }
    }
    
    if not db_manager or not redis_client:
        health["status"] = "degraded"
    
    return health


@app.get("/health")
async def simple_health_check():
    """Simple health check endpoint for Docker/load balancers"""
    return {"status": "ok"}


# Background task để listen Redis Pub/Sub và broadcast
async def redis_listener():
    """
    Background task lắng nghe Redis Pub/Sub cho real-time updates
    """
    if not redis_client:
        logger.warning("⚠️ Redis not available, skipping Redis listener")
        return
    
    logger.info("👂 Starting Redis Pub/Sub listener...")
    
    try:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("post_updates", "system_stats")
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    channel = message["channel"]
                    data = json.loads(message["data"])
                    
                    if channel == "post_updates":
                        # Broadcast post update đến subscribers
                        post_signature = data.get("post_signature")
                        if post_signature:
                            await manager.broadcast_to_post_subscribers(post_signature, data)
                    
                    elif channel == "system_stats":
                        # Broadcast system stats đến tất cả clients
                        await manager.broadcast_system_stats(data)
                        
                except Exception as e:
                    logger.error(f"❌ Error processing Redis message: {e}")
                    
    except Exception as e:
        logger.error(f"❌ Redis listener error: {e}")
    finally:
        if 'pubsub' in locals():
            await pubsub.close()


# Start Redis listener khi app startup
@app.on_event("startup")
async def startup_event():
    """Start background tasks"""
    if redis_client:
        # Start Redis listener trong background
        asyncio.create_task(redis_listener())


# Development server
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )




