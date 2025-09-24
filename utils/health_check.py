#!/usr/bin/env python3
"""
Health Check Service for Facebook Post Monitor
🔧 PRODUCTION FIX: Health monitoring and metrics endpoint

Features:
- Comprehensive health checks for all components
- Prometheus-compatible metrics
- FastAPI-based REST endpoints
- Circuit breaker status monitoring
"""

import time
import logging
from typing import Dict, Any
from datetime import datetime

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import PlainTextResponse
except ImportError:
    # Fallback for systems without FastAPI
    FastAPI = None
    HTTPException = None
    PlainTextResponse = None

try:
    from core.database_manager import DatabaseManager
    from core.session_manager import SessionManager
    from utils.circuit_breaker import circuit_breaker_registry
    from config import settings
    import redis
except ImportError as e:
    logging.warning(f"Some dependencies not available for health checks: {e}")


logger = logging.getLogger(__name__)


class HealthChecker:
    """Comprehensive health checking for all system components"""
    
    def __init__(self):
        self.db_manager = None
        self.session_manager = None
        self.redis_client = None
        
        # Initialize components
        self._initialize_components()
    
    def _initialize_components(self):
        """Initialize health check components"""
        try:
            self.db_manager = DatabaseManager()
            logger.info("✅ Database manager initialized for health checks")
        except Exception as e:
            logger.error("❌ Failed to initialize database manager: %s", e)
        
        try:
            self.session_manager = SessionManager()
            logger.info("✅ Session manager initialized for health checks")
        except Exception as e:
            logger.error("❌ Failed to initialize session manager: %s", e)
        
        try:
            self.redis_client = redis.Redis(
                host=settings.redis.host,
                port=settings.redis.port,
                db=settings.redis.db,
                socket_connect_timeout=settings.redis.socket_connect_timeout
            )
            logger.info("✅ Redis client initialized for health checks")
        except Exception as e:
            logger.error("❌ Failed to initialize Redis client: %s", e)
    
    def check_database_connection(self) -> Dict[str, Any]:
        """Check database connectivity and basic operations"""
        if not self.db_manager:
            return {
                "status": "ERROR",
                "message": "Database manager not initialized",
                "response_time_ms": 0
            }
        
        start_time = time.time()
        try:
            # Test basic database operation
            stats = self.db_manager.get_stats()
            response_time_ms = (time.time() - start_time) * 1000
            
            return {
                "status": "UP",
                "response_time_ms": round(response_time_ms, 2),
                "database_type": "PostgreSQL",
                "stats": stats,
                "last_check": datetime.now().isoformat()
            }
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            return {
                "status": "DOWN",
                "message": str(e),
                "response_time_ms": round(response_time_ms, 2),
                "last_check": datetime.now().isoformat()
            }
    
    def check_redis_connection(self) -> Dict[str, Any]:
        """Check Redis connectivity and queue status"""
        if not self.redis_client:
            return {
                "status": "ERROR",
                "message": "Redis client not initialized",
                "response_time_ms": 0
            }
        
        start_time = time.time()
        try:
            # Test Redis ping
            ping_result = self.redis_client.ping()
            
            # Check queue length
            queue_length = self.redis_client.llen(settings.redis.queue_name)
            
            response_time_ms = (time.time() - start_time) * 1000
            
            return {
                "status": "UP" if ping_result else "DOWN",
                "response_time_ms": round(response_time_ms, 2),
                "queue_length": queue_length,
                "queue_name": settings.redis.queue_name,
                "host": settings.redis.host,
                "port": settings.redis.port,
                "last_check": datetime.now().isoformat()
            }
        except Exception as e:
            response_time_ms = (time.time() - start_time) * 1000
            return {
                "status": "DOWN",
                "message": str(e),
                "response_time_ms": round(response_time_ms, 2),
                "last_check": datetime.now().isoformat()
            }
    
    def get_session_pool_status(self) -> Dict[str, Any]:
        """Get session pool health and availability"""
        if not self.session_manager:
            return {
                "status": "ERROR",
                "message": "Session manager not initialized"
            }
        
        try:
            stats = self.session_manager.get_stats()
            
            # Determine overall health
            ready_sessions = stats.get('ready_sessions', 0)
            total_sessions = stats.get('total_sessions', 0)
            
            if total_sessions == 0:
                status = "DOWN"
            elif ready_sessions == 0:
                status = "DEGRADED"
            elif ready_sessions < total_sessions * 0.3:  # Less than 30% available
                status = "DEGRADED"
            else:
                status = "UP"
            
            return {
                "status": status,
                "ready_sessions": ready_sessions,
                "total_sessions": total_sessions,
                "availability_ratio": round(ready_sessions / max(total_sessions, 1), 2),
                "session_details": stats,
                "last_check": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "status": "DOWN",
                "message": str(e),
                "last_check": datetime.now().isoformat()
            }
    
    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """Get circuit breaker states and metrics"""
        breakers_status = {}
        overall_status = "UP"
        
        try:
            for name, breaker in circuit_breaker_registry.breakers.items():
                state = breaker.get_state()
                
                breaker_info = {
                    "state": state.name,
                    "failure_count": breaker.failure_count,
                    "failure_threshold": breaker.config.failure_threshold,
                    "last_failure_time": breaker.last_failure_time.isoformat() if breaker.last_failure_time else None,
                    "last_state_change": breaker.last_state_change_time
                }
                
                # Check if breaker is affecting system health
                if state.name == "OPEN":
                    overall_status = "DEGRADED"
                elif state.name == "HALF_OPEN" and overall_status == "UP":
                    overall_status = "WARNING"
                
                breakers_status[name] = breaker_info
            
            return {
                "status": overall_status,
                "circuit_breakers": breakers_status,
                "total_breakers": len(breakers_status),
                "open_breakers": sum(1 for b in breakers_status.values() if b["state"] == "OPEN"),
                "last_check": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "message": str(e),
                "last_check": datetime.now().isoformat()
            }
    
    def get_overall_health(self) -> Dict[str, Any]:
        """Get comprehensive system health status"""
        # Check all components
        db_health = self.check_database_connection()
        redis_health = self.check_redis_connection()
        session_health = self.get_session_pool_status()
        circuit_breaker_health = self.get_circuit_breaker_status()
        
        # Determine overall status
        component_statuses = [
            db_health["status"],
            redis_health["status"],
            session_health["status"],
            circuit_breaker_health["status"]
        ]
        
        if any(status == "DOWN" for status in component_statuses):
            overall_status = "DOWN"
        elif any(status == "DEGRADED" for status in component_statuses):
            overall_status = "DEGRADED"
        elif any(status == "WARNING" for status in component_statuses):
            overall_status = "WARNING"
        else:
            overall_status = "UP"
        
        return {
            "status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "environment": settings.environment,
            "components": {
                "database": db_health,
                "redis": redis_health,
                "session_pool": session_health,
                "circuit_breakers": circuit_breaker_health
            },
            "summary": {
                "healthy_components": sum(1 for status in component_statuses if status == "UP"),
                "total_components": len(component_statuses),
                "degraded_components": sum(1 for status in component_statuses if status in ["DEGRADED", "WARNING"]),
                "failed_components": sum(1 for status in component_statuses if status == "DOWN")
            }
        }
    
    def get_simple_status(self) -> str:
        """Get simple UP/DOWN status for load balancers"""
        health = self.get_overall_health()
        return "UP" if health["status"] in ["UP", "WARNING"] else "DOWN"


# Global health checker instance
health_checker = HealthChecker()


# FastAPI app for health endpoints
if FastAPI is not None:
    app = FastAPI(title="Facebook Monitor Health Check", version="1.0.0")
    
    @app.get("/health")
    async def health_check_endpoint():
        """Comprehensive health check endpoint"""
        health = health_checker.get_overall_health()
        
        # Return appropriate HTTP status
        if health["status"] == "DOWN":
            raise HTTPException(status_code=503, detail=health)
        elif health["status"] in ["DEGRADED", "WARNING"]:
            raise HTTPException(status_code=200, detail=health)  # Still responding
        else:
            return health
    
    @app.get("/health/simple")
    async def simple_health_check():
        """Simple UP/DOWN health check for load balancers"""
        status = health_checker.get_simple_status()
        return {"status": status}
    
    @app.get("/health/database")
    async def database_health():
        """Database-specific health check"""
        return health_checker.check_database_connection()
    
    @app.get("/health/redis")
    async def redis_health():
        """Redis-specific health check"""
        return health_checker.check_redis_connection()
    
    @app.get("/health/sessions")
    async def session_health():
        """Session pool health check"""
        return health_checker.get_session_pool_status()
    
    @app.get("/health/circuit-breakers")
    async def circuit_breaker_health():
        """Circuit breaker status check"""
        return health_checker.get_circuit_breaker_status()
    
    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics_endpoint():
        """Prometheus-compatible metrics endpoint"""
        return generate_prometheus_metrics()


def generate_prometheus_metrics() -> str:
    """Generate Prometheus-compatible metrics"""
    health = health_checker.get_overall_health()
    
    metrics = []
    
    # Overall system health
    status_value = 1 if health["status"] == "UP" else 0
    metrics.append(f'facebook_monitor_health_status{{environment="{settings.environment}"}} {status_value}')
    
    # Database metrics
    db_health = health["components"]["database"]
    db_status = 1 if db_health["status"] == "UP" else 0
    metrics.append(f'facebook_monitor_database_status {{}} {db_status}')
    if "response_time_ms" in db_health:
        metrics.append(f'facebook_monitor_database_response_time_ms {{}} {db_health["response_time_ms"]}')
    
    # Redis metrics
    redis_health = health["components"]["redis"]
    redis_status = 1 if redis_health["status"] == "UP" else 0
    metrics.append(f'facebook_monitor_redis_status {{}} {redis_status}')
    if "queue_length" in redis_health:
        metrics.append(f'facebook_monitor_redis_queue_length {{}} {redis_health["queue_length"]}')
    
    # Session pool metrics
    session_health = health["components"]["session_pool"]
    if "ready_sessions" in session_health:
        metrics.append(f'facebook_monitor_sessions_ready {{}} {session_health["ready_sessions"]}')
        metrics.append(f'facebook_monitor_sessions_total {{}} {session_health["total_sessions"]}')
    
    # Circuit breaker metrics
    cb_health = health["components"]["circuit_breakers"]
    if "circuit_breakers" in cb_health:
        for name, breaker in cb_health["circuit_breakers"].items():
            state_value = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}.get(breaker["state"], -1)
            metrics.append(f'facebook_monitor_circuit_breaker_state{{name="{name}"}} {state_value}')
            metrics.append(f'facebook_monitor_circuit_breaker_failures{{name="{name}"}} {breaker["failure_count"]}')
    
    return "\n".join(metrics) + "\n"


if __name__ == "__main__":
    # Test health checker
    print("🏥 Testing Health Checker...")
    
    checker = HealthChecker()
    health = checker.get_overall_health()
    
    print(f"Overall Status: {health['status']}")
    print(f"Database: {health['components']['database']['status']}")
    print(f"Redis: {health['components']['redis']['status']}")
    print(f"Sessions: {health['components']['session_pool']['status']}")
    print(f"Circuit Breakers: {health['components']['circuit_breakers']['status']}")
    
    print("\n📊 Prometheus Metrics:")
    print(generate_prometheus_metrics())
    
    print("✅ Health checker test completed!")