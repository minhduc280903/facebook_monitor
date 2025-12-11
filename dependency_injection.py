#!/usr/bin/env python3
"""
Dependency Injection Container for Facebook Post Monitor
🔧 SOLUTION: Replace global variables with proper dependency injection

This module provides a clean dependency injection system to eliminate
global state and improve testability.
"""

import asyncio
from typing import Dict, Any, Optional, TypeVar, Type, Callable, Union
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar('T')

class DIContainer:
    """Dependency Injection Container"""
    
    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable] = {}
        self._singletons: Dict[str, Any] = {}
        self._initialized = False
    
    def register_singleton(self, name: str, instance: Any):
        """Register a singleton instance"""
        self._singletons[name] = instance
        logger.debug(f"📋 Registered singleton: {name}")
    
    def register_factory(self, name: str, factory: Callable):
        """Register a factory function"""
        self._factories[name] = factory
        logger.debug(f"🏭 Registered factory: {name}")
    
    def register_service(self, name: str, service_class: Type[T], **kwargs) -> None:
        """Register a service class with dependencies"""
        self._services[name] = {
            'class': service_class,
            'kwargs': kwargs,
            'instance': None
        }
        logger.debug(f"🔧 Registered service: {name}")
    
    def get(self, name: str) -> Any:
        """Get a service instance"""
        # Check singletons first
        if name in self._singletons:
            return self._singletons[name]
        
        # Check factories
        if name in self._factories:
            instance = self._factories[name]()
            logger.debug(f"🏭 Created instance from factory: {name}")
            return instance
        
        # Check services
        if name in self._services:
            service_config = self._services[name]
            
            # Return existing instance if available
            if service_config['instance'] is not None:
                return service_config['instance']
            
            # Create new instance
            service_class = service_config['class']
            kwargs = service_config['kwargs']
            
            # Resolve dependencies in kwargs
            resolved_kwargs = {}
            for key, value in kwargs.items():
                if isinstance(value, str) and value.startswith('@'):
                    # Dependency reference (e.g., '@database_manager')
                    dep_name = value[1:]
                    resolved_kwargs[key] = self.get(dep_name)
                else:
                    resolved_kwargs[key] = value
            
            instance = service_class(**resolved_kwargs)
            service_config['instance'] = instance
            
            logger.debug(f"🔧 Created service instance: {name}")
            return instance
        
        raise ValueError(f"❌ Service not found: {name}")
    
    def get_optional(self, name: str) -> Optional[Any]:
        """Get a service instance or None if not found"""
        try:
            return self.get(name)
        except ValueError:
            return None
    
    async def initialize_async_services(self):
        """Initialize async services"""
        if self._initialized:
            return
        
        logger.info("🚀 Initializing async services...")
        
        # Initialize services that need async setup
        for name, service_config in self._services.items():
            instance = service_config.get('instance')
            if instance and hasattr(instance, 'initialize_async'):
                try:
                    await instance.initialize_async()
                    logger.debug(f"✅ Async initialized: {name}")
                except Exception as e:
                    logger.error(f"❌ Failed to initialize {name}: {e}")
                    raise
        
        self._initialized = True
        logger.info("✅ All async services initialized")
    
    async def shutdown(self):
        """Shutdown all services gracefully"""
        logger.info("⏹️ Shutting down services...")
        
        # Shutdown services in reverse order
        service_names = list(self._services.keys())
        service_names.reverse()
        
        for name in service_names:
            service_config = self._services[name]
            instance = service_config.get('instance')
            
            if instance and hasattr(instance, 'shutdown'):
                try:
                    if asyncio.iscoroutinefunction(instance.shutdown):
                        await instance.shutdown()
                    else:
                        instance.shutdown()
                    logger.debug(f"✅ Shutdown: {name}")
                except Exception as e:
                    logger.error(f"❌ Error shutting down {name}: {e}")
        
        # Clear singletons
        for name, instance in self._singletons.items():
            if hasattr(instance, 'close'):
                try:
                    if asyncio.iscoroutinefunction(instance.close):
                        await instance.close()
                    else:
                        instance.close()
                    logger.debug(f"✅ Closed singleton: {name}")
                except Exception as e:
                    logger.error(f"❌ Error closing {name}: {e}")
        
        self._initialized = False
        logger.info("✅ All services shutdown complete")

# Global container instance
container = DIContainer()

class ServiceManager:
    """High-level service management"""
    
    def __init__(self):
        self.container = container
        self._setup_core_services()
    
    def _setup_core_services(self):
        """Setup core application services"""
        
        # Configuration
        from config import settings
        self.container.register_singleton('config', settings)
        
        # Database Manager (gets config from settings internally)
        from core.database_manager import DatabaseManager
        self.container.register_singleton('database_manager', DatabaseManager())
        
        # Session Manager  
        from core.session_manager import SessionManager
        self.container.register_service(
            'session_manager',
            SessionManager,
            status_file='sessions/session_status.json',
            sessions_dir='sessions'
        )
        
        # Proxy Manager - NOW WITH DATABASE!
        from core.proxy_manager import ProxyManager
        db_manager = self.container.get('database_manager')
        self.container.register_factory(
            'proxy_manager',
            lambda: ProxyManager(db_manager=db_manager)  # Inject db_manager
        )
        
        # Circuit Breaker
        from utils.circuit_breaker import CircuitBreaker
        self.container.register_factory(
            'circuit_breaker',
            lambda: CircuitBreaker()
        )
        
        logger.info("🔧 Core services registered")
    
    async def start_application(self):
        """Start the application with dependency injection"""
        try:
            # Initialize async services
            await self.container.initialize_async_services()
            
            # Get core services to ensure they're initialized
            db_manager = self.container.get('database_manager')
            session_manager = self.container.get('session_manager')
            proxy_manager = self.container.get('proxy_manager')
            
            logger.info("✅ Application started with dependency injection")
            return {
                'database_manager': db_manager,
                'session_manager': session_manager,
                'proxy_manager': proxy_manager
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to start application: {e}")
            await self.shutdown_application()
            raise
    
    async def shutdown_application(self):
        """Shutdown the application"""
        await self.container.shutdown()
    
    @asynccontextmanager
    async def application_context(self):
        """Context manager for application lifecycle"""
        services = None
        try:
            services = await self.start_application()
            yield services
        finally:
            await self.shutdown_application()

# Convenience functions
def get_service(name: str) -> Any:
    """Get a service from the global container"""
    return container.get(name)

def get_database_manager():
    """Get database manager instance"""
    return container.get('database_manager')

def get_session_manager():
    """Get session manager instance"""
    return container.get('session_manager')

def get_proxy_manager():
    """Get proxy manager instance"""
    return container.get('proxy_manager')

# Decorators for dependency injection
def inject(**dependencies):
    """Decorator to inject dependencies into functions"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Inject dependencies
            for name, service_name in dependencies.items():
                if name not in kwargs:
                    kwargs[name] = container.get(service_name)
            return func(*args, **kwargs)
        return wrapper
    return decorator

def async_inject(**dependencies):
    """Async version of inject decorator"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Inject dependencies
            for name, service_name in dependencies.items():
                if name not in kwargs:
                    kwargs[name] = container.get(service_name)
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Example usage patterns
class BaseService(ABC):
    """Base class for services with dependency injection"""
    
    def __init__(self, **kwargs):
        # Auto-inject dependencies based on type hints
        self._inject_dependencies(**kwargs)
    
    def _inject_dependencies(self, **kwargs):
        """Auto-inject dependencies based on constructor parameters"""
        # Implementation would use type hints to auto-resolve dependencies
        pass
    
    @abstractmethod
    async def initialize_async(self):
        """Async initialization hook"""
        pass
    
    @abstractmethod
    async def shutdown(self):
        """Shutdown hook"""
        pass

if __name__ == "__main__":
    async def test_dependency_injection():
        """Test dependency injection system"""
        service_manager = ServiceManager()
        
        async with service_manager.application_context() as services:
            print("✅ Services initialized:")
            for name, service in services.items():
                print(f"  - {name}: {type(service).__name__}")
            
            # Test service access
            db_manager = get_database_manager()
            session_manager = get_session_manager()
            
            print(f"📊 Database manager: {type(db_manager).__name__}")
            print(f"🔐 Session manager: {type(session_manager).__name__}")
    
    asyncio.run(test_dependency_injection())