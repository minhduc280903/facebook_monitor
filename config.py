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

    # PostgreSQL Configuration
    host: str = Field(
        default="postgres",
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
        default="redis",
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
        default=True,
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
    """Validate configuration settings"""
    try:
        # Check critical values
        if config_instance.circuit_breaker.database_failure_threshold < 1:
            return False
        if config_instance.session.failure_threshold < 1:
            return False
        if config_instance.redis.socket_connect_timeout < 1:
            return False
        return True
    except Exception:
        return False


if __name__ == "__main__":
    # Test configuration loading
    print("🔧 Testing Configuration Loading...")

    main_config = settings
    print(f"Environment: {main_config.environment}")
    print(f"Database host: {main_config.database.host}:{main_config.database.port}/{main_config.database.name}")
    print(
        f"Session failure threshold: {main_config.session.failure_threshold}"
    )
    print(
        "Circuit breaker DB threshold: "
        f"{main_config.circuit_breaker.database_failure_threshold}"
    )

    # Validate
    is_valid = validate_config(main_config)
    print(f"Configuration valid: {is_valid}")

    print("✅ Configuration loading test completed!")
