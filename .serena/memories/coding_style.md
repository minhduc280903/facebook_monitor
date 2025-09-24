# Coding Style and Conventions

## Code Style
- **Language**: Python 3.13+
- **Encoding**: UTF-8 with Vietnamese comments supported
- **Imports**: Standard library first, then third-party, then local imports
- **Type Hints**: Comprehensive type annotations using `typing` module
- **Docstrings**: Multi-line docstrings with Vietnamese descriptions

## Naming Conventions
- **Classes**: PascalCase (e.g., `SessionManager`, `MultiQueueWorker`)
- **Functions/Methods**: snake_case (e.g., `checkout_session`, `get_stats`)
- **Variables**: snake_case (e.g., `session_name`, `proxy_config`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `FILELOCK_AVAILABLE`)
- **Files**: snake_case (e.g., `session_manager.py`)

## Architecture Patterns
- **Resource Management**: ManagedResource pattern with performance tracking
- **Thread Safety**: Explicit locking with threading.Lock and FileLock
- **Error Handling**: Comprehensive try-catch with logging
- **Configuration**: Pydantic models for type validation
- **Dependency Injection**: Service locator pattern in `dependency_injection.py`

## Logging Conventions
- **Emojis**: Used in log messages for visual distinction
  - 🔐 for initialization
  - ✅ for success operations  
  - ❌ for errors
  - ⚠️ for warnings
  - 🎯 for intelligent selection
  - 🔓 for resource checkin
  - 🚨 for quarantine actions
- **Levels**: DEBUG for detailed info, INFO for operations, WARNING for issues, ERROR for failures

## File Organization
- **Core modules**: Business logic in `core/` directory
- **Utilities**: Helper functions in `utils/` directory  
- **Tests**: Mirror structure in `tests/` directory
- **Configuration**: JSON files for runtime configuration
- **Status tracking**: JSON files for resource state persistence