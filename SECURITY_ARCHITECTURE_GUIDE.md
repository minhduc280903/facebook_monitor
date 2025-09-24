# 🔐 HƯỚNG DẪN BẢO MẬT VÀ KIẾN TRÚC - FACEBOOK POST MONITOR

## 📋 TỔNG QUAN

Tài liệu này cung cấp hướng dẫn chi tiết để khắc phục các vấn đề bảo mật và kiến trúc đã được xác định trong hệ thống Facebook Post Monitor. Tất cả các thay đổi được thiết kế để duy trì tính nhất quán logic và không gây ra lỗi mới.

## 🎯 MỤC TIÊU CỐT LÕI

1. **Loại bỏ Single Points of Failure**
2. **Tăng cường bảo mật ứng dụng**
3. **Cải thiện Error Handling**
4. **Tối ưu Resource Management**
5. **Đảm bảo Production Security**

---

## 🏗️ PHẦN 1: KHẮC PHỤC VẤN ĐỀ KIẾN TRÚC

### 1.1 Database High Availability

#### Vấn đề hiện tại:
- Single PostgreSQL instance
- Không có replication
- Không có backup strategy

#### Giải pháp: PostgreSQL Master-Slave Setup

**1.1.1 Tạo file `docker-compose.ha.yml`:**

```yaml
version: '3.8'

services:
  postgres-master:
    image: postgres:15-alpine
    container_name: facebook-monitor-postgres-master
    restart: unless-stopped
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: simple123
      POSTGRES_DB: facebook_monitor
      POSTGRES_REPLICATION_USER: replicator
      POSTGRES_REPLICATION_PASSWORD: repl_password
    volumes:
      - postgres_master_data:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d
      - ./ha-scripts/master-setup.sh:/docker-entrypoint-initdb.d/01-master-setup.sh
    ports:
      - "5432:5432"
    command: |
      postgres
      -c wal_level=replica
      -c max_wal_senders=3
      -c wal_keep_size=64MB
      -c hot_standby=on
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d facebook_monitor"]
      interval: 10s
      timeout: 5s
      retries: 5

  postgres-slave:
    image: postgres:15-alpine
    container_name: facebook-monitor-postgres-slave
    restart: unless-stopped
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: simple123
      POSTGRES_DB: facebook_monitor
      POSTGRES_MASTER_HOST: postgres-master
      POSTGRES_REPLICATION_USER: replicator
      POSTGRES_REPLICATION_PASSWORD: repl_password
    volumes:
      - postgres_slave_data:/var/lib/postgresql/data
      - ./ha-scripts/slave-setup.sh:/docker-entrypoint-initdb.d/01-slave-setup.sh
    ports:
      - "5433:5432"
    depends_on:
      postgres-master:
        condition: service_healthy
    command: |
      bash -c "
      if [ ! -s /var/lib/postgresql/data/PG_VERSION ]; then
        pg_basebackup -h postgres-master -D /var/lib/postgresql/data -U replicator -W
        echo 'standby_mode = on' >> /var/lib/postgresql/data/recovery.conf
        echo 'primary_conninfo = \"host=postgres-master port=5432 user=replicator\"' >> /var/lib/postgresql/data/recovery.conf
      fi
      postgres -c hot_standby=on
      "

  # Redis Cluster Setup
  redis-master:
    image: redis:7-alpine
    container_name: facebook-monitor-redis-master
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_master_data:/data
    command: |
      redis-server
      --appendonly yes
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
      --save 900 1
      --save 300 10
      --save 60 10000

  redis-slave:
    image: redis:7-alpine
    container_name: facebook-monitor-redis-slave
    restart: unless-stopped
    ports:
      - "6380:6379"
    volumes:
      - redis_slave_data:/data
    command: |
      redis-server
      --replicaof redis-master 6379
      --appendonly yes
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
    depends_on:
      - redis-master

volumes:
  postgres_master_data:
    driver: local
  postgres_slave_data:
    driver: local
  redis_master_data:
    driver: local
  redis_slave_data:
    driver: local
```

**1.1.2 Tạo script thiết lập Master: `ha-scripts/master-setup.sh`:**

```bash
#!/bin/bash
set -e

# Create replication user
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER replicator REPLICATION LOGIN ENCRYPTED PASSWORD 'repl_password';
EOSQL

# Configure pg_hba.conf for replication
echo "host replication replicator 0.0.0.0/0 md5" >> /var/lib/postgresql/data/pg_hba.conf

# Reload configuration
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT pg_reload_conf();
EOSQL
```

**1.1.3 Cập nhật Database Manager để support failover:**

```python
# core/database_manager_ha.py
import psycopg2
from psycopg2 import pool
from typing import Optional, List
import logging
import time

class HADatabaseManager:
    """High Availability Database Manager with automatic failover"""

    def __init__(self):
        self.master_config = {
            'host': 'postgres-master',
            'port': 5432,
            'database': 'facebook_monitor',
            'user': 'postgres',
            'password': 'simple123'
        }

        self.slave_config = {
            'host': 'postgres-slave',
            'port': 5432,
            'database': 'facebook_monitor',
            'user': 'postgres',
            'password': 'simple123'
        }

        self.master_pool = None
        self.slave_pool = None
        self.current_master = 'master'
        self.logger = logging.getLogger(__name__)

        self._initialize_pools()

    def _initialize_pools(self):
        """Initialize connection pools for both master and slave"""
        try:
            self.master_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=10,
                **self.master_config
            )
            self.logger.info("✅ Master database pool initialized")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize master pool: {e}")

        try:
            self.slave_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=10,
                **self.slave_config
            )
            self.logger.info("✅ Slave database pool initialized")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize slave pool: {e}")

    def get_write_connection(self):
        """Get connection for write operations (always master)"""
        if self.current_master == 'master' and self.master_pool:
            try:
                return self.master_pool.getconn()
            except Exception as e:
                self.logger.error(f"❌ Master connection failed: {e}")
                return self._failover_to_slave()

        # If master is down, try slave
        return self._failover_to_slave()

    def get_read_connection(self):
        """Get connection for read operations (prefer slave)"""
        if self.slave_pool:
            try:
                return self.slave_pool.getconn()
            except Exception as e:
                self.logger.warning(f"⚠️ Slave connection failed: {e}")

        # Fallback to master
        if self.master_pool:
            try:
                return self.master_pool.getconn()
            except Exception as e:
                self.logger.error(f"❌ Both master and slave connections failed: {e}")
                raise

    def _failover_to_slave(self):
        """Perform failover to slave database"""
        self.logger.warning("🔄 Performing database failover to slave")
        self.current_master = 'slave'

        if self.slave_pool:
            return self.slave_pool.getconn()
        else:
            raise Exception("Both master and slave databases are unavailable")

    def return_connection(self, conn, pool_type='read'):
        """Return connection to appropriate pool"""
        if pool_type == 'write':
            if self.current_master == 'master' and self.master_pool:
                self.master_pool.putconn(conn)
            elif self.slave_pool:
                self.slave_pool.putconn(conn)
        else:  # read
            if self.slave_pool:
                self.slave_pool.putconn(conn)
            elif self.master_pool:
                self.master_pool.putconn(conn)
```

### 1.2 Redis High Availability

**1.2.1 Cập nhật Redis Configuration để support Sentinel:**

```python
# core/redis_manager_ha.py
import redis.asyncio as redis
from redis.sentinel import Sentinel
import logging
from typing import Optional, List

class HARedisManger:
    """High Availability Redis Manager with Sentinel"""

    def __init__(self):
        self.sentinel_hosts = [
            ('redis-sentinel-1', 26379),
            ('redis-sentinel-2', 26379),
            ('redis-sentinel-3', 26379)
        ]
        self.sentinel = None
        self.master = None
        self.slaves = []
        self.logger = logging.getLogger(__name__)

        self._initialize_sentinel()

    def _initialize_sentinel(self):
        """Initialize Redis Sentinel connection"""
        try:
            self.sentinel = Sentinel(
                self.sentinel_hosts,
                socket_timeout=0.1,
                socket_connect_timeout=5
            )

            # Get master connection
            self.master = self.sentinel.master_for(
                'facebook-monitor',
                socket_timeout=0.1,
                decode_responses=True
            )

            # Get slave connections
            self.slaves = [
                self.sentinel.slave_for(
                    'facebook-monitor',
                    socket_timeout=0.1,
                    decode_responses=True
                )
            ]

            self.logger.info("✅ Redis Sentinel initialized successfully")

        except Exception as e:
            self.logger.error(f"❌ Failed to initialize Redis Sentinel: {e}")
            # Fallback to direct connection
            self._initialize_direct_connection()

    def _initialize_direct_connection(self):
        """Fallback to direct Redis connection"""
        try:
            self.master = redis.from_url(
                "redis://redis-master:6379",
                decode_responses=True,
                socket_connect_timeout=5
            )
            self.logger.info("✅ Direct Redis connection established")
        except Exception as e:
            self.logger.error(f"❌ All Redis connections failed: {e}")

    async def get_write_client(self) -> redis.Redis:
        """Get Redis client for write operations"""
        if self.master:
            return self.master
        raise Exception("No Redis master available")

    async def get_read_client(self) -> redis.Redis:
        """Get Redis client for read operations"""
        if self.slaves:
            # Use round-robin for slave selection
            return self.slaves[0]
        elif self.master:
            return self.master
        raise Exception("No Redis instance available")
```

### 1.3 Application Load Balancing

**1.3.1 Thêm HAProxy configuration: `haproxy/haproxy.cfg`:**

```
global
    daemon
    maxconn 4096
    log stdout local0

defaults
    mode http
    timeout connect 5000ms
    timeout client 50000ms
    timeout server 50000ms
    option httplog
    option dontlognull
    retries 3

frontend api_frontend
    bind *:80
    option httplog
    default_backend api_backend

backend api_backend
    balance roundrobin
    option httpchk GET /health
    http-check expect status 200
    server api1 api-1:8000 check
    server api2 api-2:8000 check
    server api3 api-3:8000 check

frontend streamlit_frontend
    bind *:8501
    default_backend streamlit_backend

backend streamlit_backend
    balance roundrobin
    option httpchk GET /healthz
    server streamlit1 streamlit-1:8501 check
    server streamlit2 streamlit-2:8501 check
```

**1.3.2 Cập nhật docker-compose với multiple API instances:**

```yaml
# Thêm vào docker-compose.ha.yml
  haproxy:
    image: haproxy:2.8-alpine
    container_name: facebook-monitor-haproxy
    restart: unless-stopped
    ports:
      - "80:80"
      - "8501:8501"
      - "8404:8404"  # HAProxy stats
    volumes:
      - ./haproxy/haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
    depends_on:
      - api-1
      - api-2
      - api-3

  api-1:
    build: .
    container_name: facebook-monitor-api-1
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./logs:/app/logs
    depends_on:
      postgres-master:
        condition: service_healthy
      redis-master:
        condition: service_started

  api-2:
    build: .
    container_name: facebook-monitor-api-2
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./logs:/app/logs
    depends_on:
      postgres-master:
        condition: service_healthy
      redis-master:
        condition: service_started

  api-3:
    build: .
    container_name: facebook-monitor-api-3
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./logs:/app/logs
    depends_on:
      postgres-master:
        condition: service_healthy
      redis-master:
        condition: service_started
```

---

## 🔒 PHẦN 2: KHẮC PHỤC VẤN ĐỀ BẢO MẬT

### 2.1 Input Validation và Rate Limiting

**2.1.1 Tạo Validation Middleware: `api/middleware/validation.py`:**

```python
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
import re
from typing import Any, Dict
import logging
from datetime import datetime, timedelta
import asyncio

class ValidationMiddleware:
    """Comprehensive input validation middleware"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

        # Validation patterns
        self.patterns = {
            'post_signature': re.compile(r'^[a-zA-Z0-9_\-]{10,100}$'),
            'limit': re.compile(r'^[1-9]\d{0,2}$'),  # 1-999
            'status': re.compile(r'^(TRACKING|EXPIRED|PENDING)$'),
            'client_id': re.compile(r'^[a-zA-Z0-9_\-]{3,50}$')
        }

        # Dangerous patterns to block
        self.dangerous_patterns = [
            re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL),
            re.compile(r'javascript:', re.IGNORECASE),
            re.compile(r'on\w+\s*=', re.IGNORECASE),
            re.compile(r'eval\s*\(', re.IGNORECASE),
            re.compile(r'expression\s*\(', re.IGNORECASE),
            re.compile(r'@import', re.IGNORECASE),
            re.compile(r'<!--[\s\S]*?-->', re.IGNORECASE),
        ]

    def validate_post_signature(self, signature: str) -> bool:
        """Validate post signature format"""
        if not signature or len(signature) > 100:
            return False
        return bool(self.patterns['post_signature'].match(signature))

    def validate_limit(self, limit: int) -> bool:
        """Validate limit parameter"""
        return 1 <= limit <= 1000

    def validate_status(self, status: str) -> bool:
        """Validate status parameter"""
        return bool(self.patterns['status'].match(status))

    def check_xss(self, value: str) -> bool:
        """Check for XSS attempts"""
        for pattern in self.dangerous_patterns:
            if pattern.search(value):
                return True
        return False

    def sanitize_string(self, value: str, max_length: int = 1000) -> str:
        """Sanitize input string"""
        if not isinstance(value, str):
            raise ValueError("Input must be a string")

        # Truncate if too long
        if len(value) > max_length:
            value = value[:max_length]

        # Check for XSS
        if self.check_xss(value):
            raise ValueError("Potentially malicious input detected")

        # Basic sanitization
        value = value.strip()
        value = re.sub(r'[<>"\']', '', value)  # Remove dangerous chars

        return value

# Rate limiting implementation
class RateLimiter:
    """Redis-based rate limiter"""

    def __init__(self, redis_client):
        self.redis = redis_client
        self.logger = logging.getLogger(__name__)

    async def is_allowed(self, key: str, limit: int, window: int) -> bool:
        """
        Check if request is within rate limit

        Args:
            key: Rate limit key (e.g., IP address)
            limit: Maximum requests allowed
            window: Time window in seconds
        """
        try:
            current_time = int(datetime.now().timestamp())
            window_start = current_time - window

            # Use sliding window log
            pipeline = self.redis.pipeline()

            # Remove old entries
            pipeline.zremrangebyscore(key, 0, window_start)

            # Count current requests
            pipeline.zcard(key)

            # Add current request
            pipeline.zadd(key, {str(current_time): current_time})

            # Set expiry
            pipeline.expire(key, window)

            results = await pipeline.execute()
            current_requests = results[1]

            return current_requests < limit

        except Exception as e:
            self.logger.error(f"Rate limiting error: {e}")
            # Fail open - allow request if rate limiter fails
            return True

# FastAPI middleware integration
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import time

class SecurityMiddleware:
    """Combined security middleware"""

    def __init__(self, app: FastAPI, redis_client):
        self.app = app
        self.validator = ValidationMiddleware()
        self.rate_limiter = RateLimiter(redis_client)
        self.logger = logging.getLogger(__name__)

        # Rate limiting rules
        self.rate_limits = {
            'api_general': {'limit': 100, 'window': 60},  # 100 req/min
            'api_intensive': {'limit': 10, 'window': 60}, # 10 req/min for heavy ops
            'websocket': {'limit': 50, 'window': 60}      # 50 connections/min
        }

    async def __call__(self, request: Request, call_next):
        """Process security checks"""
        start_time = time.time()

        try:
            # Get client IP
            client_ip = self._get_client_ip(request)

            # Rate limiting
            await self._check_rate_limits(request, client_ip)

            # Input validation for specific endpoints
            await self._validate_request(request)

            # Security headers
            response = await call_next(request)
            self._add_security_headers(response)

            # Log request
            process_time = time.time() - start_time
            self.logger.info(
                f"Request: {request.method} {request.url.path} "
                f"IP: {client_ip} Time: {process_time:.3f}s"
            )

            return response

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Security middleware error: {e}")
            raise HTTPException(status_code=500, detail="Internal security error")

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP address"""
        # Check for forwarded headers
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()

        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip

        return request.client.host if request.client else 'unknown'

    async def _check_rate_limits(self, request: Request, client_ip: str):
        """Apply rate limiting"""
        path = request.url.path

        # Determine rate limit type
        if path.startswith('/api/posts') and request.method == 'POST':
            rule = self.rate_limits['api_intensive']
        elif path.startswith('/ws/'):
            rule = self.rate_limits['websocket']
        else:
            rule = self.rate_limits['api_general']

        key = f"rate_limit:{client_ip}:{path}"

        if not await self.rate_limiter.is_allowed(key, rule['limit'], rule['window']):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(rule['window'])}
            )

    async def _validate_request(self, request: Request):
        """Validate request parameters"""
        path = request.url.path

        # Validate query parameters
        for key, value in request.query_params.items():
            if key == 'limit':
                try:
                    limit = int(value)
                    if not self.validator.validate_limit(limit):
                        raise HTTPException(400, f"Invalid limit: {value}")
                except ValueError:
                    raise HTTPException(400, f"Invalid limit format: {value}")

            elif key == 'status':
                if not self.validator.validate_status(value):
                    raise HTTPException(400, f"Invalid status: {value}")

            # Check for XSS in all string parameters
            elif isinstance(value, str) and self.validator.check_xss(value):
                raise HTTPException(400, "Potentially malicious input detected")

        # Validate path parameters for post signatures
        if '/posts/' in path:
            parts = path.split('/')
            for i, part in enumerate(parts):
                if parts[i-1] == 'posts' and part:
                    if not self.validator.validate_post_signature(part):
                        raise HTTPException(400, f"Invalid post signature: {part}")

    def _add_security_headers(self, response):
        """Add security headers to response"""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
```

**2.1.2 Cập nhật API main.py để sử dụng security middleware:**

```python
# api/main.py - Thêm vào phần imports
from api.middleware.validation import SecurityMiddleware

# Thêm vào phần khởi tạo app
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager cho FastAPI app"""
    global redis_client, db_manager

    # ... existing code ...

    # Initialize security middleware
    if redis_client:
        security_middleware = SecurityMiddleware(app, redis_client)
        app.middleware("http")(security_middleware)

    yield

    # ... existing cleanup code ...

# Cập nhật CORS để restrict origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",  # Streamlit local
        "http://streamlit:8501",  # Streamlit container
        "https://yourdomain.com", # Production domain
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

### 2.2 Error Handling Improvements

**2.2.1 Tạo Custom Exception Handler: `utils/exceptions.py`:**

```python
"""
Custom exceptions and error handling for Facebook Post Monitor
Replaces 200+ generic 'except Exception' statements
"""

import logging
from typing import Optional, Dict, Any
from enum import Enum

class ErrorCode(Enum):
    """Standardized error codes"""
    DATABASE_CONNECTION_FAILED = "DB_CONN_001"
    DATABASE_QUERY_FAILED = "DB_QUERY_002"
    REDIS_CONNECTION_FAILED = "REDIS_001"
    REDIS_OPERATION_FAILED = "REDIS_002"
    BROWSER_LAUNCH_FAILED = "BROWSER_001"
    BROWSER_NAVIGATION_FAILED = "BROWSER_002"
    SESSION_CHECKOUT_FAILED = "SESSION_001"
    SESSION_EXPIRED = "SESSION_002"
    SCRAPING_BLOCKED = "SCRAPE_001"
    CAPTCHA_DETECTED = "SCRAPE_002"
    PROXY_CONNECTION_FAILED = "PROXY_001"
    VALIDATION_FAILED = "VALID_001"
    RATE_LIMIT_EXCEEDED = "RATE_001"

class BaseMonitorException(Exception):
    """Base exception for all monitor-specific errors"""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        details: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.original_exception = original_exception
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/API responses"""
        return {
            'error_code': self.error_code.value,
            'message': self.message,
            'details': self.details,
            'original_error': str(self.original_exception) if self.original_exception else None
        }

class DatabaseError(BaseMonitorException):
    """Database-related errors"""
    pass

class RedisError(BaseMonitorException):
    """Redis-related errors"""
    pass

class BrowserError(BaseMonitorException):
    """Browser automation errors"""
    pass

class SessionError(BaseMonitorException):
    """Session management errors"""
    pass

class ScrapingError(BaseMonitorException):
    """Web scraping errors"""
    pass

class ProxyError(BaseMonitorException):
    """Proxy-related errors"""
    pass

class ValidationError(BaseMonitorException):
    """Input validation errors"""
    pass

class RateLimitError(BaseMonitorException):
    """Rate limiting errors"""
    pass

# Exception handler decorator
import functools
from typing import Callable, Type, Union

def handle_exceptions(
    *exception_types: Type[Exception],
    error_code: ErrorCode,
    message: str = "An error occurred",
    reraise_as: Type[BaseMonitorException] = None,
    log_level: int = logging.ERROR
) -> Callable:
    """
    Decorator to handle specific exceptions and convert them to monitor exceptions

    Usage:
        @handle_exceptions(psycopg2.Error, error_code=ErrorCode.DATABASE_QUERY_FAILED)
        def database_operation():
            # code that might raise psycopg2.Error
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exception_types as e:
                logger = logging.getLogger(func.__module__)

                # Create appropriate exception
                monitor_exception = (reraise_as or BaseMonitorException)(
                    message=f"{message}: {str(e)}",
                    error_code=error_code,
                    original_exception=e,
                    details={
                        'function': func.__name__,
                        'args': str(args)[:200],  # Truncate for logging
                        'kwargs': str(kwargs)[:200]
                    }
                )

                # Log the error
                logger.log(log_level, f"Exception in {func.__name__}: {monitor_exception.to_dict()}")

                raise monitor_exception

        return wrapper
    return decorator

# Async version
def handle_exceptions_async(
    *exception_types: Type[Exception],
    error_code: ErrorCode,
    message: str = "An error occurred",
    reraise_as: Type[BaseMonitorException] = None,
    log_level: int = logging.ERROR
) -> Callable:
    """Async version of handle_exceptions decorator"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except exception_types as e:
                logger = logging.getLogger(func.__module__)

                monitor_exception = (reraise_as or BaseMonitorException)(
                    message=f"{message}: {str(e)}",
                    error_code=error_code,
                    original_exception=e,
                    details={
                        'function': func.__name__,
                        'args': str(args)[:200],
                        'kwargs': str(kwargs)[:200]
                    }
                )

                logger.log(log_level, f"Exception in {func.__name__}: {monitor_exception.to_dict()}")
                raise monitor_exception

        return wrapper
    return decorator

# Context manager for exception handling
from contextlib import contextmanager

@contextmanager
def exception_context(
    error_code: ErrorCode,
    message: str = "Operation failed",
    reraise_as: Type[BaseMonitorException] = None
):
    """
    Context manager for exception handling

    Usage:
        with exception_context(ErrorCode.DATABASE_QUERY_FAILED, "Database query failed"):
            # code that might fail
    """
    try:
        yield
    except BaseMonitorException:
        # Re-raise monitor exceptions as-is
        raise
    except Exception as e:
        logger = logging.getLogger(__name__)

        monitor_exception = (reraise_as or BaseMonitorException)(
            message=f"{message}: {str(e)}",
            error_code=error_code,
            original_exception=e
        )

        logger.error(f"Exception in context: {monitor_exception.to_dict()}")
        raise monitor_exception
```

**2.2.2 Cập nhật Database Manager với improved error handling:**

```python
# core/database_manager_secure.py
import psycopg2
from psycopg2 import pool, errors
from utils.exceptions import (
    DatabaseError, ErrorCode, handle_exceptions, exception_context
)
import logging

class SecureDatabaseManager:
    """Database manager with improved error handling and security"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.connection_pool = None
        self._initialize_connection_pool()

    @handle_exceptions(
        psycopg2.Error,
        error_code=ErrorCode.DATABASE_CONNECTION_FAILED,
        message="Failed to initialize database connection pool",
        reraise_as=DatabaseError
    )
    def _initialize_connection_pool(self):
        """Initialize database connection pool with error handling"""
        self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=settings.database.host,
            port=settings.database.port,
            database=settings.database.name,
            user=settings.database.user,
            password=settings.database.password,
            connect_timeout=settings.database.connection_timeout
        )
        self.logger.info("✅ Database connection pool initialized")

    @handle_exceptions(
        (psycopg2.Error, psycopg2.pool.PoolError),
        error_code=ErrorCode.DATABASE_CONNECTION_FAILED,
        message="Failed to get database connection",
        reraise_as=DatabaseError
    )
    def get_connection(self):
        """Get database connection from pool"""
        if not self.connection_pool:
            raise DatabaseError(
                "Connection pool not initialized",
                ErrorCode.DATABASE_CONNECTION_FAILED
            )
        return self.connection_pool.getconn()

    def return_connection(self, conn):
        """Return connection to pool"""
        if self.connection_pool and conn:
            try:
                self.connection_pool.putconn(conn)
            except Exception as e:
                self.logger.error(f"Failed to return connection to pool: {e}")

    @handle_exceptions(
        psycopg2.Error,
        error_code=ErrorCode.DATABASE_QUERY_FAILED,
        message="Database query failed",
        reraise_as=DatabaseError
    )
    def execute_query(self, query: str, params: tuple = None, fetch: bool = True):
        """Execute database query with proper error handling"""
        conn = None
        try:
            conn = self.get_connection()

            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # Log query for debugging (without sensitive data)
                safe_query = query[:100] + "..." if len(query) > 100 else query
                self.logger.debug(f"Executing query: {safe_query}")

                cursor.execute(query, params)

                if fetch:
                    if query.strip().upper().startswith('SELECT'):
                        return cursor.fetchall()
                    else:
                        conn.commit()
                        return cursor.rowcount
                else:
                    conn.commit()
                    return None

        except psycopg2.Error as e:
            if conn:
                conn.rollback()

            # Categorize database errors
            if isinstance(e, errors.ConnectionException):
                error_code = ErrorCode.DATABASE_CONNECTION_FAILED
            elif isinstance(e, errors.DataError):
                error_code = ErrorCode.VALIDATION_FAILED
            else:
                error_code = ErrorCode.DATABASE_QUERY_FAILED

            raise DatabaseError(
                f"Query execution failed: {str(e)}",
                error_code,
                details={
                    'query_preview': query[:100],
                    'error_type': type(e).__name__
                },
                original_exception=e
            )
        finally:
            if conn:
                self.return_connection(conn)

    def get_post_by_signature(self, post_signature: str):
        """Get post by signature with validation"""
        if not post_signature or len(post_signature) > 100:
            raise ValidationError(
                "Invalid post signature",
                ErrorCode.VALIDATION_FAILED,
                details={'post_signature_length': len(post_signature) if post_signature else 0}
            )

        with exception_context(
            ErrorCode.DATABASE_QUERY_FAILED,
            "Failed to retrieve post by signature"
        ):
            query = """
                SELECT post_signature, post_url, source_url, author_name,
                       author_id, post_content, first_seen_utc, tracking_expires_utc,
                       status, priority_score
                FROM posts
                WHERE post_signature = %s
            """

            results = self.execute_query(query, (post_signature,))
            return results[0] if results else None
```

### 2.3 Docker Security Improvements

**2.3.1 Tạo secure Dockerfile: `Dockerfile.secure`:**

```dockerfile
# Multi-stage build for smaller, more secure image
FROM python:3.11-slim as builder

# Create non-root user
RUN groupadd -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup appuser

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set up Python environment
WORKDIR /app
COPY backend_requirements.txt webapp_streamlit/requirements.txt ./
RUN pip install --no-cache-dir --user -r backend_requirements.txt && \
    pip install --no-cache-dir --user -r requirements.txt

# Install Playwright browsers
RUN python -m playwright install --with-deps chromium

# Production stage
FROM python:3.11-slim as production

# Security updates
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup appuser

# Copy Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Set up application directory
WORKDIR /app

# Copy application code
COPY --chown=appuser:appgroup . .

# Create logs directory with proper permissions
RUN mkdir -p logs && \
    chown -R appuser:appgroup logs && \
    chmod 755 logs

# Switch to non-root user
USER appuser

# Add user's local bin to PATH
ENV PATH="/home/appuser/.local/bin:$PATH"

# Security: Remove unnecessary files
RUN find . -name "*.pyc" -delete && \
    find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Use exec form for better signal handling
ENTRYPOINT ["python"]
CMD ["-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**2.3.2 Cập nhật docker-compose với security best practices:**

```yaml
# docker-compose.production.yml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: facebook-monitor-postgres
    restart: unless-stopped

    # Security: Run as non-root
    user: postgres

    # Security: Read-only root filesystem
    read_only: true
    tmpfs:
      - /tmp
      - /var/run/postgresql

    environment:
      POSTGRES_USER_FILE: /run/secrets/postgres_user
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
      POSTGRES_DB: facebook_monitor
      POSTGRES_INITDB_ARGS: "--auth-host=scram-sha-256"

    # Use secrets instead of environment variables
    secrets:
      - postgres_user
      - postgres_password

    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d:ro

    # Security: Limit resources
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '1.0'
        reservations:
          memory: 512M
          cpus: '0.5'

    # Security: Custom network
    networks:
      - backend

    # Security: No exposed ports (only internal access)
    # ports removed

    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$(cat /run/secrets/postgres_user) -d facebook_monitor"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: facebook-monitor-redis
    restart: unless-stopped

    # Security: Run as non-root
    user: redis

    # Security: Read-only root filesystem
    read_only: true
    tmpfs:
      - /tmp

    volumes:
      - redis_data:/data
      - ./redis-config/redis.conf:/etc/redis/redis.conf:ro

    command: redis-server /etc/redis/redis.conf

    # Security: Limit resources
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'
        reservations:
          memory: 256M
          cpus: '0.25'

    networks:
      - backend

    healthcheck:
      test: ["CMD", "redis-cli", "--no-auth-warning", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build:
      context: .
      dockerfile: Dockerfile.secure
    container_name: facebook-monitor-api
    restart: unless-stopped

    # Security: Read-only root filesystem (except for logs)
    read_only: true
    tmpfs:
      - /tmp

    volumes:
      - ./logs:/app/logs:rw

    # Security: Use secrets for sensitive data
    secrets:
      - postgres_password
      - redis_password

    environment:
      # Non-sensitive environment variables only
      ENVIRONMENT: production
      LOG_LEVEL: WARNING
      DB_HOST: postgres
      DB_PORT: 5432
      DB_NAME: facebook_monitor
      REDIS_HOST: redis
      REDIS_PORT: 6379

    # Security: Limit resources
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: '1.0'
        reservations:
          memory: 1G
          cpus: '0.5'

    # Security: Custom networks
    networks:
      - frontend
      - backend

    ports:
      - "127.0.0.1:8000:8000"  # Bind to localhost only

    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

    # Security: Capabilities
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE

    # Security: No new privileges
    security_opt:
      - no-new-privileges:true

# Security: Define custom networks
networks:
  frontend:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/24
  backend:
    driver: bridge
    internal: true  # No external access
    ipam:
      config:
        - subnet: 172.21.0.0/24

# Security: Use Docker secrets
secrets:
  postgres_user:
    file: ./secrets/postgres_user.txt
  postgres_password:
    file: ./secrets/postgres_password.txt
  redis_password:
    file: ./secrets/redis_password.txt

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
```

**2.3.3 Tạo Redis security config: `redis-config/redis.conf`:**

```
# Redis Security Configuration

# Network security
bind 127.0.0.1
protected-mode yes
port 6379

# Authentication
requirepass ${REDIS_PASSWORD}

# Command security
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command KEYS ""
rename-command PEXPIRE ""
rename-command DEL "DEL_RENAMED_COMMAND"
rename-command CONFIG "CONFIG_RENAMED_COMMAND"
rename-command SHUTDOWN SHUTDOWN_RENAMED_COMMAND
rename-command DEBUG ""
rename-command EVAL ""

# Memory and persistence
maxmemory 512mb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
appendonly yes
appendfsync everysec

# Security limits
timeout 300
tcp-keepalive 300
maxclients 100

# Logging
loglevel notice
logfile /var/log/redis/redis-server.log
```

---

## 📝 PHẦN 3: IMPLEMENTATION CHECKLIST

### 3.1 Pre-Implementation Steps

**Backup hiện tại:**
```bash
# Backup database
docker exec facebook-monitor-postgres pg_dump -U postgres facebook_monitor > backup_$(date +%Y%m%d).sql

# Backup Redis
docker exec facebook-monitor-redis redis-cli BGSAVE

# Backup code
git add -A && git commit -m "Pre-security-update backup"
```

### 3.2 Implementation Order

**Phase 1: Error Handling (Low Risk)**
1. ✅ Implement custom exceptions (`utils/exceptions.py`)
2. ✅ Update database manager with new error handling
3. ✅ Update 5-10 modules at a time với new exception handling
4. ✅ Test thoroughly after each batch

**Phase 2: Security Middleware (Medium Risk)**
1. ✅ Implement validation middleware
2. ✅ Add rate limiting
3. ✅ Update CORS configuration
4. ✅ Test API endpoints extensively

**Phase 3: Database HA (High Risk)**
1. ✅ Set up staging environment first
2. ✅ Implement master-slave PostgreSQL
3. ✅ Test failover scenarios
4. ✅ Migrate production during maintenance window

**Phase 4: Docker Security (Medium Risk)**
1. ✅ Build secure Docker images
2. ✅ Create secrets files
3. ✅ Update docker-compose configuration
4. ✅ Test in staging environment

### 3.3 Testing Strategy

**Unit Tests:**
```python
# tests/test_security.py
import pytest
from api.middleware.validation import ValidationMiddleware, RateLimiter
from utils.exceptions import DatabaseError, ErrorCode

class TestValidationMiddleware:
    def test_post_signature_validation(self):
        validator = ValidationMiddleware()

        # Valid signatures
        assert validator.validate_post_signature("valid_sig_123")
        assert validator.validate_post_signature("another-valid-sig")

        # Invalid signatures
        assert not validator.validate_post_signature("")
        assert not validator.validate_post_signature("a" * 101)  # Too long
        assert not validator.validate_post_signature("invalid@sig")  # Invalid chars

    def test_xss_detection(self):
        validator = ValidationMiddleware()

        # Malicious inputs
        assert validator.check_xss("<script>alert('xss')</script>")
        assert validator.check_xss("javascript:alert(1)")
        assert validator.check_xss("<img onerror=alert(1) src=x>")

        # Safe inputs
        assert not validator.check_xss("normal text")
        assert not validator.check_xss("user@example.com")

class TestDatabaseErrorHandling:
    def test_custom_exceptions(self):
        with pytest.raises(DatabaseError) as exc_info:
            raise DatabaseError(
                "Test error",
                ErrorCode.DATABASE_QUERY_FAILED,
                details={'test': 'data'}
            )

        assert exc_info.value.error_code == ErrorCode.DATABASE_QUERY_FAILED
        assert exc_info.value.details['test'] == 'data'
```

**Integration Tests:**
```python
# tests/test_api_security.py
import pytest
from fastapi.testclient import TestClient
from api.main import app

class TestAPISecurity:
    def setUp(self):
        self.client = TestClient(app)

    def test_rate_limiting(self):
        """Test rate limiting functionality"""
        # Make multiple requests rapidly
        responses = []
        for i in range(105):  # Exceed limit of 100/min
            response = self.client.get("/api/stats")
            responses.append(response.status_code)

        # Should have some 429 responses
        assert 429 in responses

    def test_input_validation(self):
        """Test input validation"""
        # Test invalid post signature
        response = self.client.get("/api/posts/invalid@signature/interactions")
        assert response.status_code == 400
        assert "Invalid post signature" in response.json()["detail"]

        # Test XSS attempt
        response = self.client.get("/api/posts?search=<script>alert(1)</script>")
        assert response.status_code == 400
        assert "malicious input" in response.json()["detail"]

    def test_cors_restrictions(self):
        """Test CORS restrictions"""
        response = self.client.options(
            "/api/stats",
            headers={"Origin": "https://malicious-site.com"}
        )
        # Should not include malicious origin in allowed origins
        assert "https://malicious-site.com" not in response.headers.get("Access-Control-Allow-Origin", "")
```

### 3.4 Monitoring và Alerting

**3.4.1 Tạo monitoring script: `monitoring/security_monitor.py`:**

```python
#!/usr/bin/env python3
"""
Security monitoring script for Facebook Post Monitor
Monitor for security events and send alerts
"""

import logging
import time
import json
import smtplib
from email.mime.text import MimeText
from datetime import datetime, timedelta
from typing import Dict, List, Any
import redis
import psycopg2

class SecurityMonitor:
    """Monitor security events and send alerts"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)
        self.alerts = []

        # Thresholds
        self.thresholds = {
            'failed_logins': 10,      # per hour
            'rate_limit_hits': 100,   # per hour
            'database_errors': 50,    # per hour
            'captcha_detections': 20  # per hour
        }

    def check_security_events(self):
        """Check for security events in the last hour"""
        current_time = datetime.now()
        hour_ago = current_time - timedelta(hours=1)

        events = {
            'failed_logins': self._count_failed_logins(hour_ago, current_time),
            'rate_limit_hits': self._count_rate_limit_hits(hour_ago, current_time),
            'database_errors': self._count_database_errors(hour_ago, current_time),
            'captcha_detections': self._count_captcha_detections(hour_ago, current_time)
        }

        # Check thresholds
        for event_type, count in events.items():
            if count > self.thresholds[event_type]:
                self._create_alert(event_type, count, self.thresholds[event_type])

        return events

    def _count_rate_limit_hits(self, start_time: datetime, end_time: datetime) -> int:
        """Count rate limit hits in time range"""
        try:
            # Get all rate limit keys
            rate_limit_keys = self.redis_client.keys("rate_limit:*")
            total_hits = 0

            for key in rate_limit_keys:
                # Count entries in time range
                start_timestamp = int(start_time.timestamp())
                end_timestamp = int(end_time.timestamp())

                hits = self.redis_client.zcount(key, start_timestamp, end_timestamp)
                total_hits += hits

            return total_hits
        except Exception as e:
            self.logger.error(f"Failed to count rate limit hits: {e}")
            return 0

    def _create_alert(self, event_type: str, count: int, threshold: int):
        """Create security alert"""
        alert = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            'count': count,
            'threshold': threshold,
            'severity': 'HIGH' if count > threshold * 2 else 'MEDIUM'
        }

        self.alerts.append(alert)
        self.logger.warning(f"Security Alert: {alert}")

        # Send notification
        self._send_alert_notification(alert)

    def _send_alert_notification(self, alert: Dict[str, Any]):
        """Send alert notification via email/webhook"""
        # Email notification
        try:
            self._send_email_alert(alert)
        except Exception as e:
            self.logger.error(f"Failed to send email alert: {e}")

        # Webhook notification (if configured)
        try:
            self._send_webhook_alert(alert)
        except Exception as e:
            self.logger.error(f"Failed to send webhook alert: {e}")

    def _send_email_alert(self, alert: Dict[str, Any]):
        """Send email alert"""
        # Email configuration (use environment variables in production)
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        smtp_user = "alerts@yourdomain.com"
        smtp_password = "your_app_password"

        to_email = "admin@yourdomain.com"

        subject = f"Security Alert: {alert['event_type']} - {alert['severity']}"
        body = f"""
Security Alert Detected:

Event Type: {alert['event_type']}
Count: {alert['count']}
Threshold: {alert['threshold']}
Severity: {alert['severity']}
Timestamp: {alert['timestamp']}

Please investigate immediately.
        """

        msg = MimeText(body)
        msg['Subject'] = subject
        msg['From'] = smtp_user
        msg['To'] = to_email

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

# Cron job script
if __name__ == "__main__":
    monitor = SecurityMonitor()
    events = monitor.check_security_events()
    print(f"Security events in last hour: {events}")
```

### 3.5 Production Deployment Script

**3.5.1 Tạo deployment script: `scripts/deploy_secure.sh`:**

```bash
#!/bin/bash
# Secure deployment script for Facebook Post Monitor

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Configuration
BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
LOG_FILE="./logs/deployment_$(date +%Y%m%d_%H%M%S).log"
COMPOSE_FILE="docker-compose.production.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}" | tee -a "$LOG_FILE"
    exit 1
}

# Pre-flight checks
preflight_checks() {
    log "Running pre-flight checks..."

    # Check if running as root
    if [[ $EUID -eq 0 ]]; then
        error "This script should not be run as root"
    fi

    # Check Docker
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed"
    fi

    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        error "Docker Compose is not installed"
    fi

    # Check secrets files
    required_secrets=("postgres_user.txt" "postgres_password.txt" "redis_password.txt")
    for secret in "${required_secrets[@]}"; do
        if [[ ! -f "./secrets/$secret" ]]; then
            error "Missing secret file: ./secrets/$secret"
        fi
    done

    # Check disk space (need at least 5GB)
    available_space=$(df . | awk 'NR==2 {print $4}')
    if [[ $available_space -lt 5000000 ]]; then
        error "Insufficient disk space. Need at least 5GB free."
    fi

    log "Pre-flight checks passed ✅"
}

# Create backup
create_backup() {
    log "Creating backup..."

    mkdir -p "$BACKUP_DIR"

    # Backup database
    if docker ps | grep -q facebook-monitor-postgres; then
        log "Backing up PostgreSQL database..."
        docker exec facebook-monitor-postgres pg_dump -U postgres facebook_monitor > "$BACKUP_DIR/database_backup.sql"
    fi

    # Backup Redis
    if docker ps | grep -q facebook-monitor-redis; then
        log "Backing up Redis data..."
        docker exec facebook-monitor-redis redis-cli BGSAVE
        docker cp facebook-monitor-redis:/data/dump.rdb "$BACKUP_DIR/redis_backup.rdb"
    fi

    # Backup configuration
    cp -r . "$BACKUP_DIR/source_backup"

    log "Backup created at $BACKUP_DIR ✅"
}

# Deploy new version
deploy() {
    log "Starting deployment..."

    # Pull latest images
    log "Pulling latest Docker images..."
    docker-compose -f "$COMPOSE_FILE" pull

    # Build new images
    log "Building application images..."
    docker-compose -f "$COMPOSE_FILE" build --no-cache

    # Stop old containers gracefully
    log "Stopping old containers..."
    docker-compose -f "$COMPOSE_FILE" down --timeout 30

    # Start new containers
    log "Starting new containers..."
    docker-compose -f "$COMPOSE_FILE" up -d

    # Wait for services to be healthy
    log "Waiting for services to be healthy..."
    sleep 30

    # Health checks
    health_check

    log "Deployment completed ✅"
}

# Health checks
health_check() {
    log "Running health checks..."

    # Check API health
    for i in {1..30}; do
        if curl -f http://localhost:8000/health &>/dev/null; then
            log "API health check passed ✅"
            break
        fi
        if [[ $i -eq 30 ]]; then
            error "API health check failed after 30 attempts"
        fi
        sleep 2
    done

    # Check database connectivity
    if docker exec facebook-monitor-api python -c "
from core.database_manager import DatabaseManager
try:
    db = DatabaseManager()
    stats = db.get_stats()
    print('Database connectivity: OK')
except Exception as e:
    print(f'Database connectivity: FAILED - {e}')
    exit(1)
"; then
        log "Database connectivity check passed ✅"
    else
        error "Database connectivity check failed"
    fi

    # Check Redis connectivity
    if docker exec facebook-monitor-redis redis-cli --no-auth-warning ping | grep -q PONG; then
        log "Redis connectivity check passed ✅"
    else
        error "Redis connectivity check failed"
    fi
}

# Rollback function
rollback() {
    warn "Rolling back to previous version..."

    # Stop current containers
    docker-compose -f "$COMPOSE_FILE" down

    # Restore from backup
    if [[ -n "${BACKUP_DIR:-}" && -d "$BACKUP_DIR" ]]; then
        # Restore database
        if [[ -f "$BACKUP_DIR/database_backup.sql" ]]; then
            log "Restoring database..."
            docker-compose -f "$COMPOSE_FILE" up -d postgres
            sleep 10
            docker exec -i facebook-monitor-postgres psql -U postgres facebook_monitor < "$BACKUP_DIR/database_backup.sql"
        fi

        # Restore Redis
        if [[ -f "$BACKUP_DIR/redis_backup.rdb" ]]; then
            log "Restoring Redis..."
            docker cp "$BACKUP_DIR/redis_backup.rdb" facebook-monitor-redis:/data/dump.rdb
        fi
    fi

    # Start old version
    docker-compose -f "$COMPOSE_FILE" up -d

    log "Rollback completed"
}

# Signal handlers for graceful shutdown
trap 'error "Deployment interrupted by user"' INT TERM

# Main execution
main() {
    log "Starting secure deployment process..."

    # Create logs directory
    mkdir -p ./logs

    # Run deployment steps
    preflight_checks
    create_backup

    # Deploy with error handling
    if ! deploy; then
        error "Deployment failed, initiating rollback..."
        rollback
        exit 1
    fi

    log "🚀 Secure deployment completed successfully!"
    log "Backup location: $BACKUP_DIR"
    log "Log file: $LOG_FILE"

    # Clean up old backups (keep last 5)
    log "Cleaning up old backups..."
    ls -t ./backups/ | tail -n +6 | xargs -r rm -rf
}

# Run main function
main "$@"
```

### 3.6 Final Security Checklist

**Pre-Production:**
- [ ] All secrets moved to Docker secrets
- [ ] Database running with non-root user
- [ ] Redis password authentication enabled
- [ ] CORS restricted to known domains
- [ ] Rate limiting configured and tested
- [ ] Input validation implemented for all endpoints
- [ ] Error handling replaced throughout codebase
- [ ] Security headers added to all responses
- [ ] Container capabilities dropped
- [ ] Network segmentation implemented
- [ ] Monitoring và alerting configured
- [ ] Backup and restore procedures tested
- [ ] Security testing completed

**Post-Deployment:**
- [ ] Monitor logs for security events
- [ ] Verify rate limiting is working
- [ ] Check that database replication is functioning
- [ ] Confirm all services are healthy
- [ ] Run security scan on deployed application
- [ ] Test failover scenarios
- [ ] Document any issues found
- [ ] Schedule regular security reviews

---

## 🎯 KẾT LUẬN

Tài liệu này cung cấp hướng dẫn toàn diện để khắc phục các vấn đề bảo mật và kiến trúc đã được xác định. Việc implementation phải được thực hiện theo từng phase một cách cẩn thận, với testing đầy đủ ở mỗi giai đoạn.

**Lưu ý quan trọng:**
- Luôn backup trước khi thực hiện thay đổi
- Test trong staging environment trước
- Triển khai vào production trong maintenance window
- Monitor hệ thống sát sao sau deployment
- Chuẩn bị rollback plan cho mọi tình huống

Việc áp dụng đầy đủ các recommendations này sẽ:
- Loại bỏ single points of failure
- Tăng cường bảo mật ứng dụng đáng kể
- Cải thiện error handling và debugging
- Đảm bảo production readiness
- Tạo foundation vững chắc cho việc scale trong tương lai