#!/usr/bin/env python3
"""
Pytest configuration file for Facebook Post Monitor tests

Chứa fixtures và configuration chung cho tất cả tests
"""

import pytest
import tempfile
import os
import sys
from unittest.mock import Mock

# Add project root to Python path để import modules
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


@pytest.fixture
def temp_directory():
    """Tạo temporary directory cho tests"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_config():
    """Mock configuration object"""
    config = Mock()
    config.database = Mock()
    config.database.host = "localhost"
    config.database.port = 5432
    config.database.user = "test_user"
    config.database.password = "test_pass"
    config.database.name = "test_db"
    config.database.connection_timeout = 10
    config.database.max_retries = 3
    
    config.scraping = Mock()
    config.scraping.post_tracking_days = 7
    
    return config


@pytest.fixture
def mock_logger():
    """Mock logger để tránh spam console trong tests"""
    return Mock()

@pytest.fixture
def temp_files(temp_directory):
    """Tạo temporary files cho tests."""
    files = {}
    
    def create_file(name, content=""):
        file_path = os.path.join(temp_directory, name)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        files[name] = file_path
        return file_path

    yield create_file

    # Cleanup is handled by temp_directory fixture

@pytest.fixture
def temp_dirs(temp_directory):
    """Tạo temporary directories cho tests."""
    dirs = {}

    def create_dir(name):
        dir_path = os.path.join(temp_directory, name)
        os.makedirs(dir_path, exist_ok=True)
        dirs[name] = dir_path
        return dir_path

    yield create_dir

    # Cleanup is handled by temp_directory fixture


# Markers cho different test types
def pytest_configure(config):
    """Configure pytest markers"""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests "
        "(may need external services)"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests (fast, isolated)"
    )


# Skip integration tests by default unless explicitly requested
def pytest_collection_modifyitems(config, items):
    """Auto-skip integration tests unless --integration flag is used"""
    if config.getoption("--integration"):
        return
    
    skip_integration = pytest.mark.skip(
        reason="Integration test - use --integration to run"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


def pytest_addoption(parser):
    """Add custom command line options"""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests that require external services"
    )




