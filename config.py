#!/usr/bin/env python3
"""
Production Configuration for Facebook Post Monitor
🔧 FINAL PRODUCTION VERSION - Matches deployment requirements

Features:
- Environment-based configuration with .env support
- Type validation with Pydantic
- Production/development profiles
- Docker-friendly environment variable support
"""

import os
from typing import Any, Optional

# Direct Pydantic v2 imports
from pydantic_settings import BaseSettings
from pydantic import Field


class DatabaseConfig(BaseSettings):
    """PostgreSQL database configuration settings"""

    # PostgreSQL Configuration - Docker-aware
    host: str = Field(
        default="postgres",  # Docker service name (fallback localhost for local)
        description="PostgreSQL server host"
    )
    port: int = Field(
        default=5432,
        description="PostgreSQL server port"
    )
    user: str = Field(
        default="postgres",
        description="PostgreSQL username"
    )
    password: str = Field(
        default="simple123",
        description="PostgreSQL password"
    )
    name: str = Field(
        default="facebook_monitor",
        description="PostgreSQL database name"
    )
    
    # Connection Settings
    connection_timeout: int = Field(
        default=30,
        description="Database connection timeout in seconds"
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of database retry attempts"
    )
    pool_size: int = Field(
        default=10,
        description="Database connection pool size"
    )
    max_overflow: int = Field(
        default=20,
        description="Maximum overflow connections"
    )

    model_config = {
        "env_prefix": "DB_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }


class SessionConfig(BaseSettings):
    """Session management configuration"""

    failure_threshold: int = Field(
        default=3,
        description="Session failure threshold"
    )
    checkout_timeout: int = Field(
        default=30,
        description="Session checkout timeout in seconds"
    )
    max_sessions: int = Field(
        default=10,
        description="Maximum number of concurrent sessions"
    )

    model_config = {
        "env_prefix": "SESSION_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }


class WorkerConfig(BaseSettings):
    """Worker configuration settings"""

    headless: bool = Field(
        default=True,
        description="Run browser in headless mode"
    )
    concurrency: int = Field(
        default=0,
        description="Number of concurrent workers (0 = auto-detect from sessions)"
    )
    max_tasks_per_cleanup: int = Field(
        default=1000,
        description="Maximum tasks before cleanup"
    )
    stats_log_interval: int = Field(
        default=5,
        description="Statistics logging interval in minutes"
    )
    backoff_base_delay: float = Field(
        default=1.0,
        description="Base delay for exponential backoff"
    )
    backoff_max_delay: float = Field(
        default=30.0,
        description="Maximum delay for exponential backoff"
    )

    model_config = {
        "env_prefix": "WORKER_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }


class ResourceManagementConfig(BaseSettings):
    """Configuration cho Session và Proxy resource management"""
    
    # Session thresholds
    session_failure_threshold: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Consecutive failures before session quarantine"
    )
    session_success_rate_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum success rate for sessions"
    )
    session_quarantine_minutes: int = Field(
        default=60,
        ge=1,
        description="Session quarantine duration in minutes"
    )
    
    # Proxy thresholds (có thể khác session)
    proxy_failure_threshold: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Consecutive failures before proxy quarantine"
    )
    proxy_success_rate_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum success rate for proxies"
    )
    proxy_quarantine_minutes: int = Field(
        default=30,
        ge=1,
        description="Proxy quarantine duration in minutes"
    )
    
    # Common thresholds
    min_tasks_for_rate_calc: int = Field(
        default=10,
        ge=1,
        description="Minimum tasks before calculating success rate"
    )
    
    # File sync optimization
    file_sync_interval_seconds: int = Field(
        default=5,
        ge=1,
        description="Maximum interval between file syncs"
    )
    file_sync_change_threshold: int = Field(
        default=10,
        ge=1,
        description="Number of changes before forcing file sync"
    )

    model_config = {
        "env_prefix": "RESOURCE_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }


class CircuitBreakerConfig(BaseSettings):
    """Circuit breaker configuration"""

    database_failure_threshold: int = Field(
        default=3,
        description="Database failure threshold for circuit breaker"
    )
    database_recovery_timeout: int = Field(
        default=30,
        description="Database recovery timeout in seconds"
    )
    session_failure_threshold: int = Field(
        default=5,
        description="Session failure threshold for circuit breaker"
    )
    session_recovery_timeout: int = Field(
        default=60,
        description="Session recovery timeout in seconds"
    )
    browser_failure_threshold: int = Field(
        default=3,
        description="Browser failure threshold for circuit breaker"
    )
    browser_recovery_timeout: int = Field(
        default=45,
        description="Browser recovery timeout in seconds"
    )
    scraper_failure_threshold: int = Field(
        default=4,
        description="Scraper failure threshold for circuit breaker"
    )
    scraper_recovery_timeout: int = Field(
        default=120,
        description="Scraper recovery timeout in seconds"
    )

    model_config = {
        "env_prefix": "CB_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }


class RedisConfig(BaseSettings):
    """Redis configuration settings"""

    host: str = Field(
        default="redis",  # Docker service name (fallback localhost for local)
        description="Redis server host"
    )
    port: int = Field(
        default=6379,
        description="Redis server port"
    )
    db: int = Field(
        default=0,
        description="Redis database number"
    )
    queue_name: str = Field(
        default="fb_scrape_tasks",
        description="Redis queue name"
    )
    socket_connect_timeout: int = Field(
        default=5,
        description="Redis connection timeout in seconds"
    )
    socket_timeout: int = Field(
        default=30,
        description="Redis socket timeout in seconds"
    )
    max_connections: int = Field(
        default=20,
        description="Maximum Redis connections"
    )

    model_config = {
        "env_prefix": "REDIS_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }


class TimeoutConfig(BaseSettings):
    """
    ✅ CENTRALIZED TIMEOUTS - No more magic numbers!
    
    All timeout/delay constants in one place for easy tuning.
    """
    
    # Browser operation timeouts
    browser_launch_timeout: int = Field(
        default=60,
        description="Timeout for browser launch (seconds)"
    )
    page_navigation_timeout: int = Field(
        default=30,
        description="Timeout for page navigation (seconds)"
    )
    element_wait_timeout: int = Field(
        default=5,
        description="Timeout for waiting for elements (seconds)"
    )
    
    # Session/Proxy checkout timeouts
    session_checkout_timeout: int = Field(
        default=60,
        description="Timeout for session-proxy checkout (seconds)"
    )
    
    # Human-like delays (anti-detection)
    warmup_delay_min: float = Field(
        default=2.0,
        description="Minimum warmup delay (seconds)"
    )
    warmup_delay_max: float = Field(
        default=5.0,
        description="Maximum warmup delay (seconds)"
    )
    
    # Scroll delays
    scroll_delay_min: float = Field(
        default=0.5,
        description="Minimum scroll delay (seconds)"
    )
    scroll_delay_max: float = Field(
        default=1.5,
        description="Maximum scroll delay (seconds)"
    )
    
    model_config = {
        "env_prefix": "TIMEOUT_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }


class ScrapingConfig(BaseSettings):
    """Scraping configuration settings"""

    post_tracking_days: int = Field(
        default=7,
        description="Number of days to track posts"
    )
    max_posts_per_page: int = Field(
        default=20,
        description="Maximum posts to process per page"
    )
    
    # Unlimited scraping settings for date-based collection
    unlimited_mode: bool = Field(
        default=False,  # ⚡ TEMP: Disabled for testing extraction
        description="Enable unlimited scraping based on start_date only"
    )
    max_posts_safety_limit: int = Field(
        default=999999,
        description="Safety limit for posts when unlimited_mode=True"
    )
    max_scroll_hours: int = Field(
        default=24,
        description="Maximum hours to scroll when unlimited_mode=True"
    )
    
    # Rate limiting to avoid Facebook detection/blocking
    min_delay_between_requests: float = Field(
        default=2.0,
        description="Minimum delay between requests to avoid rate limiting (seconds)"
    )
    max_requests_per_minute: int = Field(
        default=20,
        description="Maximum requests per minute per session"
    )
    
    post_processing_delay_min: float = Field(
        default=0.5,
        description="Minimum delay between post processing"
    )
    post_processing_delay_max: float = Field(
        default=1.5,
        description="Maximum delay between post processing"
    )
    navigation_retries: int = Field(
        default=3,
        description="Number of navigation retry attempts"
    )
    navigation_retry_delay: int = Field(
        default=5,
        description="Delay between navigation retries in seconds"
    )

    model_config = {
        "env_prefix": "SCRAPING_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }


class Settings(BaseSettings):
    """Main application settings"""

    # Environment
    environment: str = Field(
        default="development",
        description="Application environment"
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode"
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )

    # Component configurations
    database: DatabaseConfig = DatabaseConfig()
    session: SessionConfig = SessionConfig()
    worker: WorkerConfig = WorkerConfig()
    circuit_breaker: CircuitBreakerConfig = CircuitBreakerConfig()
    redis: RedisConfig = RedisConfig()
    scraping: ScrapingConfig = ScrapingConfig()
    resource_management: ResourceManagementConfig = ResourceManagementConfig()
    timeouts: TimeoutConfig = TimeoutConfig()  # ✅ Centralized timeouts

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore"
    }


# Global settings instance
settings = Settings()


def get_production_config() -> Settings:
    """Get production-optimized configuration"""
    production_config = Settings()
    production_config.environment = "production"
    production_config.debug = False
    production_config.log_level = "WARNING"
    production_config.worker.headless = True
    return production_config


def get_development_config() -> Settings:
    """Get development-friendly configuration"""
    development_config = Settings()
    development_config.environment = "development"
    development_config.debug = True
    development_config.log_level = "DEBUG"
    development_config.worker.headless = False
    development_config.scraping.max_posts_per_page = 5
    return development_config


# Configuration validation
def validate_config(config_instance: Settings) -> bool:
    """
    Comprehensive configuration validation with detailed error messages.
    
    ✅ SAFE: Only validates, doesn't change anything
    
    Checks:
    - Database connection parameters
    - Required directories exist
    - Port numbers are valid
    - Threshold values are reasonable
    - File paths are accessible
    
    Returns:
        bool: True if config is valid, False otherwise
    """
    import os
    
    validation_errors = []
    
    try:
        # ===== DATABASE VALIDATION =====
        # Check database config values
        if config_instance.database.port < 1 or config_instance.database.port > 65535:
            validation_errors.append(f"Invalid database port: {config_instance.database.port} (must be 1-65535)")
        
        if not config_instance.database.host:
            validation_errors.append("Database host is empty")
        
        if not config_instance.database.name:
            validation_errors.append("Database name is empty")
        
        if config_instance.database.connection_timeout < 1:
            validation_errors.append(f"Database connection timeout too low: {config_instance.database.connection_timeout}s")
        
        # ===== REDIS VALIDATION =====
        if config_instance.redis.port < 1 or config_instance.redis.port > 65535:
            validation_errors.append(f"Invalid Redis port: {config_instance.redis.port}")
        
        if config_instance.redis.socket_connect_timeout < 1:
            validation_errors.append("Redis socket_connect_timeout must be >= 1")
        
        # ===== THRESHOLD VALIDATION =====
        if config_instance.circuit_breaker.database_failure_threshold < 1:
            validation_errors.append("Circuit breaker database_failure_threshold must be >= 1")
        
        if config_instance.session.failure_threshold < 1:
            validation_errors.append("Session failure_threshold must be >= 1")
        
        if config_instance.resource_management.session_failure_threshold < 1:
            validation_errors.append("Resource management session_failure_threshold must be >= 1")
        
        if config_instance.resource_management.session_success_rate_threshold < 0 or \
           config_instance.resource_management.session_success_rate_threshold > 1:
            validation_errors.append("Session success_rate_threshold must be between 0 and 1")
        
        # ===== DIRECTORY VALIDATION =====
        required_dirs = ['sessions', 'logs']
        for dir_name in required_dirs:
            if not os.path.exists(dir_name):
                validation_errors.append(f"Required directory missing: {dir_name}/")
        
        # ===== FILE VALIDATION =====
        # Check if critical config files exist (warn, don't fail)
        config_files = {
            'proxies.txt': 'Proxy configuration file',
            'targets.json': 'Target URLs configuration',
            'selectors.json': 'CSS selectors configuration'
        }
        
        for file_path, description in config_files.items():
            if not os.path.exists(file_path):
                print(f"⚠️ WARNING: {description} not found: {file_path}")
                # Don't add to errors - these can be created on first run
        
        # ===== SCRAPING VALIDATION =====
        if config_instance.scraping.post_tracking_days < 1:
            validation_errors.append("Post tracking days must be >= 1")
        
        if config_instance.scraping.max_posts_per_page < 1:
            validation_errors.append("Max posts per page must be >= 1")
        
        # ===== REPORT VALIDATION RESULTS =====
        if validation_errors:
            print("❌ Configuration validation FAILED:")
            for i, error in enumerate(validation_errors, 1):
                print(f"  {i}. {error}")
            return False
        
        print("✅ Configuration validation PASSED")
        return True
        
    except Exception as e:
        print(f"❌ Configuration validation error: {e}")
        return False


if __name__ == "__main__":
    # Test configuration loading
    import sys
    import io
    
    # Fix Windows console encoding for emoji
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    print("🔧 Testing Configuration Loading...")

    main_config = settings
    print(f"Environment: {main_config.environment}")
    print(f"Database host: {main_config.database.host}:{main_config.database.port}/{main_config.database.name}")
    print(f"Session failure threshold: {main_config.session.failure_threshold}")
    print(f"Circuit breaker DB threshold: {main_config.circuit_breaker.database_failure_threshold}")

    # Validate
    print("\n" + "="*60)
    print("CONFIGURATION VALIDATION")
    print("="*60)
    is_valid = validate_config(main_config)
    print(f"\nFinal result: {'VALID ✅' if is_valid else 'INVALID ❌'}")
    print("="*60)
