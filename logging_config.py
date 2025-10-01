#!/usr/bin/env python3
"""
Centralized Logging Configuration for Facebook Post Monitor
SOLUTION: Replace 22+ duplicate logging.basicConfig calls

Usage:
    from logging_config_fixed import get_logger, setup_application_logging
    
    # At application startup (once)
    setup_application_logging()
    
    # In any module
    logger = get_logger(__name__)
    logger.info("Message")
"""

import logging
import sys
import os
from pathlib import Path
from typing import Optional, Dict, Any, Union
import threading
from datetime import datetime


class LoggingConfig:
    """Centralized logging configuration manager"""
    
    def __init__(self):
        self._logger_cache: Dict[str, logging.Logger] = {}
        self._lock = threading.RLock()
        self._initialized = False
        self._log_dir = Path("logs")
        self._setup_log_directory()
    
    def _setup_log_directory(self):
        """Create logs directory"""
        try:
            self._log_dir.mkdir(exist_ok=True)
        except Exception as e:
            print(f"Warning: Could not create logs directory: {e}")
            self._log_dir = Path(".")
    
    def create_logger(
        self,
        name: str,
        level: Union[str, int] = "INFO",
        log_file: Optional[str] = None,
        console_output: bool = True,
        file_output: bool = True,
        format_type: str = "standard"
    ) -> logging.Logger:
        """Create a logger with specified configuration"""
        
        with self._lock:
            cache_key = f"{name}_{level}_{format_type}_{console_output}_{file_output}"
            
            # Return cached logger if available
            if cache_key in self._logger_cache:
                return self._logger_cache[cache_key]
            
            # Create new logger
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.propagate = False
            
            # Set level
            if isinstance(level, str):
                level = getattr(logging, level.upper())
            logger.setLevel(level)
            
            # Get formatter
            formatter = self._get_formatter(format_type)
            
            # Console handler with Windows console compatibility
            if console_output:
                console_handler = logging.StreamHandler(sys.stdout)
                # Use a custom formatter that strips Unicode emojis for Windows console
                console_formatter = self._get_safe_console_formatter(format_type)
                console_handler.setFormatter(console_formatter)
                logger.addHandler(console_handler)
            
            # File handler
            if file_output:
                if not log_file:
                    safe_name = name.replace('.', '_').replace(os.sep, '_')
                    log_file = self._log_dir / f"{safe_name}.log"
                else:
                    log_file = self._log_dir / log_file
                
                try:
                    log_file.parent.mkdir(parents=True, exist_ok=True)
                    # Use UTF-8 encoding with BOM for better Windows compatibility
                    file_handler = logging.FileHandler(log_file, encoding='utf-8-sig', errors='replace')
                    file_handler.setFormatter(formatter)
                    logger.addHandler(file_handler)
                except Exception as e:
                    print(f"Warning: Could not create file handler for {log_file}: {e}")
            
            # Cache the logger
            self._logger_cache[cache_key] = logger
            return logger
    
    def _get_safe_console_formatter(self, format_type: str) -> logging.Formatter:
        """Get formatter for console output that strips Unicode emojis on Windows"""

        class SafeConsoleFormatter(logging.Formatter):
            def __init__(self, fmt=None, datefmt=None):
                super().__init__(fmt, datefmt)

            def format(self, record):
                formatted = super().format(record)
                # Strip ONLY emojis, KEEP Vietnamese characters
                import re
                # Remove emojis (U+1F000 to U+1F9FF, U+2600 to U+26FF, etc.)
                # But KEEP Vietnamese (Latin Extended, Vietnamese diacritics)
                emoji_pattern = re.compile(
                    "["
                    "\U0001F600-\U0001F64F"  # emoticons
                    "\U0001F300-\U0001F5FF"  # symbols & pictographs
                    "\U0001F680-\U0001F6FF"  # transport & map symbols
                    "\U0001F700-\U0001F77F"  # alchemical symbols
                    "\U0001F780-\U0001F7FF"  # Geometric Shapes Extended
                    "\U0001F800-\U0001F8FF"  # Supplemental Arrows-C
                    "\U0001F900-\U0001F9FF"  # Supplemental Symbols and Pictographs
                    "\U0001FA00-\U0001FA6F"  # Chess Symbols
                    "\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
                    "\U00002702-\U000027B0"  # Dingbats
                    "\U000024C2-\U0001F251" 
                    "]+", flags=re.UNICODE)
                formatted = emoji_pattern.sub('', formatted)
                return formatted

        formatters = {
            "standard": SafeConsoleFormatter(
                fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ),
            "simple": SafeConsoleFormatter(
                fmt='%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ),
            "message_only": SafeConsoleFormatter(
                fmt='%(message)s'
            ),
            "debug": SafeConsoleFormatter(
                fmt='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        }

        return formatters.get(format_type, formatters["standard"])

    def _get_formatter(self, format_type: str) -> logging.Formatter:
        """Get formatter based on type"""
        
        formatters = {
            "standard": logging.Formatter(
                fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            ),
            "simple": logging.Formatter(
                fmt='%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'  
            ),
            "message_only": logging.Formatter(
                fmt='%(message)s'
            ),
            "debug": logging.Formatter(
                fmt='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
        }
        
        return formatters.get(format_type, formatters["standard"])
    
    def setup_application_logging(self, config: Optional[Dict[str, Any]] = None):
        """Setup application-wide logging configuration"""
        
        if self._initialized:
            return
            
        # Default configuration for discovered modules
        default_config = {
            'root_level': 'WARNING',
            'loggers': {
                # Core components - CRITICAL PRIORITY
                'database_manager': {'level': 'INFO', 'format_type': 'standard'},
                'session_manager': {'level': 'INFO', 'format_type': 'standard'},
                'worker': {'level': 'INFO', 'format_type': 'standard'},
                'scheduler': {'level': 'INFO', 'format_type': 'standard'},
                'proxy_manager': {'level': 'INFO', 'format_type': 'standard'},
                'scraper_worker': {'level': 'INFO', 'format_type': 'debug'},
                
                # System components - HIGH PRIORITY
                'run_realtime_system': {'level': 'INFO', 'format_type': 'standard'},
                'run_multi_queue_system': {'level': 'INFO', 'format_type': 'standard'},
                'data_broadcaster': {'level': 'INFO', 'format_type': 'standard'},
                'circuit_breaker': {'level': 'DEBUG', 'format_type': 'debug'},
                
                # API & Web - MEDIUM PRIORITY
                'api.main': {'level': 'INFO', 'format_type': 'simple'},
                'webapp_streamlit.app': {'level': 'INFO', 'format_type': 'simple'},
                
                # Utilities - LOW PRIORITY
                'manage_targets': {'level': 'INFO', 'format_type': 'message_only'},
                'validation_helpers': {'level': 'WARNING', 'format_type': 'standard'},
            }
        }
        
        # Merge with provided config
        if config:
            default_config.update(config)
        
        # Set root logger level
        logging.getLogger().setLevel(
            getattr(logging, default_config['root_level'].upper())
        )
        
        self._initialized = True
        
        # Log successful initialization
        init_logger = self.get_logger('logging_config')
        init_logger.info("Centralized logging system initialized")
        init_logger.info(f"Log directory: {self._log_dir.absolute()}")
    
    def get_logger(self, name: str, level: str = "INFO", **kwargs) -> logging.Logger:
        """Get a logger instance (primary interface)"""
        return self.create_logger(name, level, **kwargs)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get logging system statistics"""
        return {
            'total_loggers': len(self._logger_cache),
            'log_directory': str(self._log_dir.absolute()),
            'initialized': self._initialized
        }


# Global logging configuration instance
_logging_config = LoggingConfig()

# Public API functions
def setup_application_logging(config: Optional[Dict[str, Any]] = None):
    """Setup application-wide logging (call once at startup)"""
    _logging_config.setup_application_logging(config)

def get_logger(name: str, level: str = "INFO", **kwargs) -> logging.Logger:
    """
    Get a logger instance - Primary interface for all modules
    
    Args:
        name: Logger name (usually __name__)
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL) 
        **kwargs: Additional configuration options
        
    Returns:
        Configured logger instance
        
    Example:
        from logging_config_fixed import get_logger
        logger = get_logger(__name__)
        logger.info("This is a log message")
    """
    return _logging_config.get_logger(name, level, **kwargs)

def get_debug_logger(name: str) -> logging.Logger:
    """Get a debug-level logger with detailed formatting"""
    return _logging_config.get_logger(name, level="DEBUG", format_type="debug")

def get_simple_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Get a simple logger (for utilities)"""
    return _logging_config.get_logger(name, level=level, format_type="simple")

def get_message_only_logger(name: str) -> logging.Logger:
    """Get a message-only logger (like manage_targets.py)"""
    return _logging_config.get_logger(name, format_type="message_only")

def get_logging_stats() -> Dict[str, Any]:
    """Get logging system statistics"""
    return _logging_config.get_stats()


if __name__ == "__main__":
    print("Testing Centralized Logging System...")
    
    # Setup application logging
    setup_application_logging()
    
    # Test different logger types
    test_loggers = [
        ("Standard Logger", get_logger(__name__)),
        ("Debug Logger", get_debug_logger(__name__ + ".debug")),
        ("Simple Logger", get_simple_logger(__name__ + ".simple")),
        ("Message Only", get_message_only_logger(__name__ + ".msg")),
    ]
    
    for test_name, logger in test_loggers:
        print(f"\nTesting {test_name}:")
        logger.debug("Debug message")
        logger.info("Info message") 
        logger.warning("Warning message")
        logger.error("Error message")
    
    # Performance test
    print("\nPerformance Test:")
    import time
    start_time = time.time()
    
    # Create 50 loggers to test caching
    loggers = [get_logger(f"test_logger_{i}") for i in range(50)]
    
    elapsed = time.time() - start_time
    print(f"Created 50 loggers in {elapsed:.3f}s")
    
    # Display stats
    stats = get_logging_stats()
    print("\nLogging Stats:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\nCentralized logging system test completed!")
    print(f"Check logs in: {stats['log_directory']}")