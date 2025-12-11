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

# 🚀 PHASE 2: Dependency Injection - Use DI container instead of globals
from dependency_injection import container, ServiceManager

# Initialize service manager
service_manager = ServiceManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager cho FastAPI app with Dependency Injection"""
    
    # Startup
    logger.info("🚀 Starting FastAPI WebSocket server with DI...")
    
    try:
        # Initialize Redis connection from settings
        redis_url = f"redis://{settings.redis.host}:{settings.redis.port}"
        logger.info(f"Connecting to Redis at {redis_url}")
        redis_instance = redis.from_url(redis_url, decode_responses=True)
        await redis_instance.ping()
        
        # Register Redis in DI container
        container.register_singleton('redis_client', redis_instance)
        logger.info("✅ Redis registered in DI container")
        
        # Start application with DI (this initializes all services including DatabaseManager)
        services = await service_manager.start_application()
        logger.info("✅ All services initialized via DI")
        
    except Exception as e:
        logger.error(f"❌ Service initialization failed: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down FastAPI server...")
    await service_manager.shutdown_application()


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


# Dependency functions using DI container
def get_db() -> DatabaseManager:
    """Get database manager from DI container"""
    try:
        return container.get('database_manager')
    except Exception as e:
        logger.error(f"Failed to get database_manager from DI: {e}")
        raise HTTPException(status_code=503, detail="Database not available")


def get_redis() -> redis.Redis:
    """Get Redis client from DI container"""
    try:
        return container.get('redis_client')
    except Exception as e:
        logger.error(f"Failed to get redis_client from DI: {e}")
        raise HTTPException(status_code=503, detail="Redis not available")


# WebSocket endpoints

@app.websocket("/ws/post/{post_signature}")
async def websocket_post_monitor(websocket: WebSocket, post_signature: str):
    """
    WebSocket endpoint for REAL-TIME post monitoring
    Perfect for TradingView Lightweight Charts with series.update()
    
    Polls database every 5 seconds and sends ONLY new data points
    """
    await websocket.accept()
    logger.info(f"📊 Real-time monitor connected for post: {post_signature[:20]}...")
    
    try:
        db = get_db()
        
        # Send initial data
        post_info = db.get_post_by_signature(post_signature)
        interactions = db.get_interaction_history(post_signature, limit=100)
        
        initial_message = {
            "type": "initial_data",
            "post_signature": post_signature,
            "post_info": post_info,
            "interactions": interactions,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await websocket.send_text(json.dumps(initial_message))
        
        # Track last known interaction
        last_interaction_timestamp = None
        if interactions:
            last_interaction_timestamp = interactions[0].get('log_timestamp_utc')
        
        # Real-time polling loop
        while True:
            await asyncio.sleep(5)  # Poll every 5 seconds
            
            # Get latest interaction
            latest_interactions = db.get_interaction_history(post_signature, limit=1)
            
            if latest_interactions:
                latest = latest_interactions[0]
                current_timestamp = latest.get('log_timestamp_utc')
                
                # Check if this is NEW data
                if current_timestamp != last_interaction_timestamp:
                    # Parse timestamp for TradingView
                    try:
                        timestamp_str = current_timestamp
                        if 'Z' in timestamp_str:
                            timestamp_str = timestamp_str.replace('Z', '')
                        if '+' in timestamp_str:
                            timestamp_str = timestamp_str.split('+')[0]
                        dt = datetime.fromisoformat(timestamp_str)
                        unix_timestamp = int(dt.timestamp())
                    except Exception as e:
                        logger.warning(f"Timestamp parse error: {e}")
                        unix_timestamp = int(datetime.now(timezone.utc).timestamp())
                    
                    # Send ONLY the new data point
                    update_message = {
                        "type": "new_data_point",
                        "post_signature": post_signature,
                        "time": unix_timestamp,
                        "likes": latest.get('like_count', 0) or 0,
                        "comments": latest.get('comment_count', 0) or 0,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    
                    await websocket.send_text(json.dumps(update_message))
                    logger.info(f"📈 Sent new data point: {latest.get('like_count')} likes, {latest.get('comment_count')} comments")
                    
                    # Update last known timestamp
                    last_interaction_timestamp = current_timestamp
                
    except WebSocketDisconnect:
        logger.info(f"🔌 Real-time monitor disconnected for post: {post_signature[:20]}...")
    except Exception as e:
        logger.error(f"❌ WebSocket error for post {post_signature[:20]}: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass


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
                        try:
                            db = get_db()
                            post_data = db.get_post_by_signature(post_signature)
                            interaction_history = db.get_interaction_history(post_signature, limit=50)
                            
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
                    try:
                        db = get_db()
                        stats = db.get_stats()
                        
                        # Add Celery queue stats if Redis available
                        try:
                            redis = get_redis()
                            # MIGRATION: Updated to use Celery queue names
                            celery_queues = ["scan_high", "scan_normal", "discovery", "maintenance"]
                            for queue_name in celery_queues:
                                queue_length = await redis.llen(queue_name)
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


@app.get("/api/posts/{post_signature}/latest")
async def get_post_latest_interaction(
    post_signature: str,
    db: DatabaseManager = Depends(get_db)
):
    """
    Get ONLY the latest interaction data point for a post
    Perfect for incremental chart updates with series.update()
    """
    try:
        # Get only 1 latest interaction
        interactions = db.get_interaction_history(post_signature, limit=1)
        
        if not interactions:
            raise HTTPException(status_code=404, detail="No interactions found")
        
        latest = interactions[0]
        
        # Parse timestamp to Unix timestamp for TradingView
        try:
            if isinstance(latest.get('log_timestamp_utc'), str):
                timestamp_str = latest['log_timestamp_utc']
                if 'Z' in timestamp_str:
                    timestamp_str = timestamp_str.replace('Z', '')
                if '+' in timestamp_str:
                    timestamp_str = timestamp_str.split('+')[0]
                dt = datetime.fromisoformat(timestamp_str)
                unix_timestamp = int(dt.timestamp())
            else:
                unix_timestamp = int(datetime.now(timezone.utc).timestamp())
        except Exception as e:
            logger.warning(f"Timestamp parse error: {e}")
            unix_timestamp = int(datetime.now(timezone.utc).timestamp())
        
        return {
            "post_signature": post_signature,
            "timestamp": unix_timestamp,
            "like_count": latest.get('like_count', 0) or 0,
            "comment_count": latest.get('comment_count', 0) or 0,
            "log_timestamp_utc": latest.get('log_timestamp_utc')
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting latest interaction for {post_signature}: {e}")
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
            "database": False,
            "redis": False
        }
    }
    
    try:
        get_db()
        health["services"]["database"] = True
    except:
        health["status"] = "degraded"
    
    try:
        get_redis()
        health["services"]["redis"] = True
    except:
        health["status"] = "degraded"
    
    return health


@app.get("/health")
async def simple_health_check():
    """Simple health check endpoint for monitoring and load balancers"""
    return {"status": "ok"}


# Background task để listen Redis Pub/Sub và broadcast
async def redis_listener():
    """
    Background task lắng nghe Redis Pub/Sub cho real-time updates
    """
    try:
        redis = get_redis()
    except Exception:
        logger.warning("⚠️ Redis not available, skipping Redis listener")
        return
    
    logger.info("👂 Starting Redis Pub/Sub listener...")
    
    try:
        pubsub = redis.pubsub()
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
    try:
        get_redis()
        # Start Redis listener trong background
        asyncio.create_task(redis_listener())
    except Exception:
        logger.warning("⚠️ Redis not available, skipping Redis listener startup")


# Development server
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )




