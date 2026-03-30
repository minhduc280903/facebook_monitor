# Session-Proxy Binding System Guide

## Overview
The Facebook Post Monitor implements a **hybrid session-proxy binding system** that combines the flexibility of worker pools with the security of fixed session-proxy relationships.

## Architecture Benefits

### ✅ Advantages
- **Consistent Identity**: Each Facebook session always uses the same proxy IP
- **Reduced Detection Risk**: Stable IP patterns appear more natural to Facebook
- **Load Balancing**: Workers remain flexible and can handle any scraping task
- **Resource Efficiency**: Intelligent resource management with quarantine system
- **High Availability**: System continues operating even if some resources fail

## Key Components

### 1. SessionManager (`core/session_manager.py`)
- Manages pool of Facebook sessions with role-based assignment
- Integrates with SessionProxyBinder for consistent proxy binding
- Implements intelligent resource selection and quarantine logic

### 2. ProxyManager (`core/proxy_manager.py`) 
- Manages pool of proxy servers with health checking
- Tracks performance metrics and response times
- Automatic quarantine for underperforming proxies

### 3. SessionProxyBinder (`core/session_proxy_binder.py`)
- Creates and maintains persistent session-proxy mappings
- Deterministic proxy assignment based on session hash
- Cross-process file locking for consistency

## Production Usage

### Primary Method (Recommended)
```python
# Worker gets session-proxy pair
result = session_manager.checkout_session_with_proxy(proxy_manager, timeout=60)
if result:
    session_name, proxy_config = result
    
    # Do scraping work...
    
    # Return both resources together
    session_manager.checkin_session_with_proxy(
        session_name, proxy_config, proxy_manager
    )
```

### Legacy Methods (Deprecated)
```python
# ⚠️ DEPRECATED - Only for unit testing and backward compatibility
session = session_manager.checkout_session()
proxy = proxy_manager.checkout_proxy()
```

## Binding Persistence

### Automatic Binding Creation
- When a session is first used, system automatically assigns an available proxy
- Assignment is deterministic based on session name hash
- Binding is stored persistently in `session_proxy_bindings.json`

### Binding File Format
```json
{
  "_metadata": {
    "created": "2025-09-21T06:24:24.355944",
    "version": "1.0",
    "description": "Session-Proxy bindings for consistent Facebook scraping"
  },
  "bindings": {
    "session_name_1": "proxy_1",
    "session_name_2": "proxy_2"
  }
}
```

## Error Handling and Fallbacks

### Resource Unavailability
- If bound proxy is unavailable, system tries to assign a new proxy
- If no proxies available, checkout returns None
- Workers implement retry logic with exponential backoff

### Emergency Fallback
```python
try:
    # Primary: Unified checkin
    session_manager.checkin_session_with_proxy(session, proxy, proxy_manager)
except Exception:
    # Emergency: Separate checkin to preserve resources
    session_manager.checkin_session(session)
    proxy_manager.checkin_proxy(proxy)
```

## Monitoring and Diagnostics

### Check Binding Stats
```python
binder = SessionProxyBinder()
stats = binder.get_binding_stats()
print(f"Total bindings: {stats['total_bindings']}")
print(f"Unique proxies used: {stats['unique_proxies_used']}")
```

### Check Resource Health
```python
# Session pool health
session_stats = session_manager.get_stats()
print(f"Sessions ready: {session_stats['ready']}")
print(f"Sessions quarantined: {session_stats['quarantined']}")

# Proxy pool health  
proxy_stats = proxy_manager.get_stats()
print(f"Proxies ready: {proxy_stats['ready']}")
print(f"Avg response time: {proxy_stats['performance']['avg_response_time']}")
```

## Best Practices

### 1. Always Use Unified Methods in Production
- Use `checkout_session_with_proxy()` instead of separate checkout
- Use `checkin_session_with_proxy()` for consistent resource return

### 2. Handle Resource Scarcity Gracefully
- Implement timeout and retry logic
- Monitor resource pool health
- Alert when resources consistently unavailable

### 3. Monitor Binding Effectiveness
- Track how often bindings are reused vs recreated
- Monitor proxy distribution across sessions
- Watch for binding conflicts or inconsistencies

### 4. Maintain Resource Pool Health
- Regular health checks on proxies
- Quarantine management for underperforming resources
- Periodic cleanup of invalid bindings

## Testing

### Unit Tests
- Individual components can still be tested with legacy methods
- Deprecation warnings guide developers to new patterns

### Integration Tests
- `TestSessionProxyBinding` class covers end-to-end binding scenarios
- Tests cover binding persistence, consistency, and error handling

### Load Testing
- Concurrent access patterns tested with thread-safe operations
- Cross-process consistency verified with file locking

## Migration Guide

### From Separate Checkout/Checkin
```python
# Old pattern
session = session_manager.checkout_session()
proxy = proxy_manager.checkout_proxy()
# ... work ...
session_manager.checkin_session(session)
proxy_manager.checkin_proxy(proxy)

# New pattern  
result = session_manager.checkout_session_with_proxy(proxy_manager)
if result:
    session, proxy = result
    # ... work ...
    session_manager.checkin_session_with_proxy(session, proxy, proxy_manager)
```

### Handling Deprecation Warnings
- Update production code to use unified methods
- Legacy methods remain for unit tests and utilities
- Set warnings filters in test environments if needed