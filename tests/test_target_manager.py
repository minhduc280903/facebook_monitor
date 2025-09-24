#!/usr/bin/env python3
"""
Unit tests for TargetManager module
Tests target loading, filtering, and management functionality
"""

import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
from datetime import datetime, timedelta

from core.target_manager import TargetManager


@pytest.mark.unit
class TestTargetManager:
    """Test cases for TargetManager class"""
    
    @pytest.fixture
    def sample_targets_file(self, tmp_path):
        """Create a temporary targets.json file with test data"""
        targets_data = {
            "targets": [
                {
                    "id": "group1",
                    "url": "https://www.facebook.com/groups/test1",
                    "name": "Test Group 1",
                    "type": "group",
                    "enabled": True,
                    "priority": 1,
                    "check_interval_hours": 1,
                    "last_checked": None,
                    "metadata": {"members": 1000}
                },
                {
                    "id": "page1",
                    "url": "https://www.facebook.com/page1",
                    "name": "Test Page 1",
                    "type": "page",
                    "enabled": True,
                    "priority": 2,
                    "check_interval_hours": 2,
                    "last_checked": "2024-01-01T12:00:00Z",
                    "metadata": {"followers": 5000}
                },
                {
                    "id": "disabled_group",
                    "url": "https://www.facebook.com/groups/disabled",
                    "name": "Disabled Group",
                    "type": "group",
                    "enabled": False,
                    "priority": 3,
                    "check_interval_hours": 4,
                    "last_checked": None,
                    "metadata": {}
                },
                {
                    "id": "high_priority",
                    "url": "https://www.facebook.com/vip",
                    "name": "VIP Page",
                    "type": "page",
                    "enabled": True,
                    "priority": 1,
                    "check_interval_hours": 0.5,
                    "last_checked": None,
                    "metadata": {"vip": True}
                }
            ],
            "settings": {
                "max_concurrent_targets": 5,
                "default_check_interval_hours": 4
            }
        }
        
        targets_file = tmp_path / "targets.json"
        with open(targets_file, 'w', encoding='utf-8') as f:
            json.dump(targets_data, f, indent=2)
        
        return targets_file
    
    def test_load_targets_success(self, sample_targets_file):
        """Test successfully loading targets from file"""
        manager = TargetManager(config_file=str(sample_targets_file))
        
        # Check that targets were loaded
        assert len(manager.targets) == 4
        assert manager.settings["max_concurrent_targets"] == 5
        
        # Verify specific target data
        group1 = next((t for t in manager.targets if t["id"] == "group1"), None)
        assert group1 is not None
        assert group1["name"] == "Test Group 1"
        assert group1["enabled"] is True
        assert group1["priority"] == 1
    
    def test_load_targets_file_not_found(self):
        """Test handling of missing targets file"""
        with patch('os.path.exists', return_value=False):
            manager = TargetManager(config_file="nonexistent.json")
            
            # Should initialize with empty targets
            assert len(manager.targets) == 0
            assert manager.settings == {}
    
    def test_load_targets_invalid_json(self, tmp_path):
        """Test handling of invalid JSON in targets file"""
        invalid_file = tmp_path / "invalid.json"
        with open(invalid_file, 'w') as f:
            f.write("{ invalid json content")
        
        manager = TargetManager(config_file=str(invalid_file))
        
        # Should handle gracefully and initialize empty
        assert len(manager.targets) == 0
    
    def test_get_active_targets(self, sample_targets_file):
        """Test filtering to get only enabled targets"""
        manager = TargetManager(config_file=str(sample_targets_file))
        active_targets = manager.get_active_targets()
        
        # Should return only enabled targets
        assert len(active_targets) == 3
        
        # Verify all returned targets are enabled
        for target in active_targets:
            assert target["enabled"] is True
        
        # Verify disabled target is not included
        disabled_ids = [t["id"] for t in active_targets]
        assert "disabled_group" not in disabled_ids
    
    def test_get_targets_by_priority(self, sample_targets_file):
        """Test filtering targets by priority level"""
        manager = TargetManager(config_file=str(sample_targets_file))
        
        # Get priority 1 targets
        priority_1 = manager.get_targets_by_priority(1)
        assert len(priority_1) == 2
        for target in priority_1:
            assert target["priority"] == 1
        
        # Get priority 2 targets
        priority_2 = manager.get_targets_by_priority(2)
        assert len(priority_2) == 1
        assert priority_2[0]["id"] == "page1"
        
        # Get non-existent priority
        priority_99 = manager.get_targets_by_priority(99)
        assert len(priority_99) == 0
    
    def test_get_targets_by_type(self, sample_targets_file):
        """Test filtering targets by type (group/page)"""
        manager = TargetManager(config_file=str(sample_targets_file))
        
        # Get group targets
        groups = manager.get_targets_by_type("group")
        assert len(groups) == 2
        for target in groups:
            assert target["type"] == "group"
        
        # Get page targets
        pages = manager.get_targets_by_type("page")
        assert len(pages) == 2
        for target in pages:
            assert target["type"] == "page"
        
        # Get non-existent type
        other = manager.get_targets_by_type("profile")
        assert len(other) == 0
    
    def test_get_target_by_id(self, sample_targets_file):
        """Test retrieving a specific target by ID"""
        manager = TargetManager(config_file=str(sample_targets_file))
        
        # Get existing target
        target = manager.get_target_by_id("group1")
        assert target is not None
        assert target["name"] == "Test Group 1"
        
        # Get non-existent target
        target = manager.get_target_by_id("nonexistent")
        assert target is None
    
    def test_update_last_checked(self, sample_targets_file):
        """Test updating the last_checked timestamp for a target"""
        manager = TargetManager(config_file=str(sample_targets_file))
        
        # Update timestamp
        target_id = "group1"
        new_timestamp = datetime.now().isoformat()
        success = manager.update_last_checked(target_id, new_timestamp)
        
        assert success is True
        
        # Verify update
        target = manager.get_target_by_id(target_id)
        assert target["last_checked"] == new_timestamp
    
    def test_update_last_checked_invalid_target(self, sample_targets_file):
        """Test updating timestamp for non-existent target"""
        manager = TargetManager(config_file=str(sample_targets_file))
        
        success = manager.update_last_checked("nonexistent", datetime.now().isoformat())
        assert success is False
    
    def test_get_targets_due_for_check(self, sample_targets_file):
        """Test getting targets that are due for checking"""
        manager = TargetManager(config_file=str(sample_targets_file))
        
        # Mock current time
        with patch('core.target_manager.datetime') as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 1, 2, 0, 0, 0)
            mock_datetime.fromisoformat = datetime.fromisoformat
            
            due_targets = manager.get_targets_due_for_check()
            
            # Should include targets never checked and those past interval
            assert len(due_targets) > 0
            
            # Verify page1 is due (last checked 12 hours ago with 2-hour interval)
            page1_due = any(t["id"] == "page1" for t in due_targets)
            assert page1_due is True
    
    def test_reload_config(self, sample_targets_file):
        """Test reloading configuration from file"""
        manager = TargetManager(config_file=str(sample_targets_file))
        original_count = len(manager.targets)
        
        # Modify the file
        with open(sample_targets_file, 'r') as f:
            data = json.load(f)
        
        # Add a new target
        data["targets"].append({
            "id": "new_target",
            "url": "https://www.facebook.com/new",
            "name": "New Target",
            "type": "page",
            "enabled": True,
            "priority": 1,
            "check_interval_hours": 1,
            "last_checked": None,
            "metadata": {}
        })
        
        with open(sample_targets_file, 'w') as f:
            json.dump(data, f)
        
        # Reload configuration
        manager.reload_config()
        
        # Verify new target was loaded
        assert len(manager.targets) == original_count + 1
        new_target = manager.get_target_by_id("new_target")
        assert new_target is not None
        assert new_target["name"] == "New Target"
    
    def test_enable_disable_target(self, sample_targets_file):
        """Test enabling and disabling targets"""
        manager = TargetManager(config_file=str(sample_targets_file))
        
        # Disable an enabled target
        success = manager.set_target_enabled("group1", False)
        assert success is True
        target = manager.get_target_by_id("group1")
        assert target["enabled"] is False
        
        # Enable a disabled target
        success = manager.set_target_enabled("disabled_group", True)
        assert success is True
        target = manager.get_target_by_id("disabled_group")
        assert target["enabled"] is True
        
        # Try to modify non-existent target
        success = manager.set_target_enabled("nonexistent", True)
        assert success is False
    
    def test_save_config(self, tmp_path):
        """Test saving configuration back to file"""
        targets_file = tmp_path / "test_save.json"
        
        # Create initial file
        initial_data = {
            "targets": [
                {
                    "id": "test1",
                    "url": "https://facebook.com/test1",
                    "name": "Test 1",
                    "type": "page",
                    "enabled": True,
                    "priority": 1,
                    "check_interval_hours": 1,
                    "last_checked": None,
                    "metadata": {}
                }
            ],
            "settings": {}
        }
        
        with open(targets_file, 'w') as f:
            json.dump(initial_data, f)
        
        # Load, modify, and save
        manager = TargetManager(config_file=str(targets_file))
        manager.set_target_enabled("test1", False)
        manager.update_last_checked("test1", "2024-01-01T12:00:00Z")
        success = manager.save_config()
        
        assert success is True
        
        # Verify saved changes
        with open(targets_file, 'r') as f:
            saved_data = json.load(f)
        
        assert saved_data["targets"][0]["enabled"] is False
        assert saved_data["targets"][0]["last_checked"] == "2024-01-01T12:00:00Z"
    
    def test_get_statistics(self, sample_targets_file):
        """Test getting statistics about targets"""
        manager = TargetManager(config_file=str(sample_targets_file))
        stats = manager.get_statistics()
        
        assert stats["total_targets"] == 4
        assert stats["enabled_targets"] == 3
        assert stats["disabled_targets"] == 1
        assert stats["groups"] == 2
        assert stats["pages"] == 2
        assert "targets_by_priority" in stats
        assert stats["targets_by_priority"][1] == 2
        assert stats["targets_by_priority"][2] == 1
        assert stats["targets_by_priority"][3] == 1
    
    def test_validate_target_url(self, sample_targets_file):
        """Test URL validation for targets"""
        manager = TargetManager(config_file=str(sample_targets_file))
        
        # Valid Facebook URLs
        assert manager.validate_target_url("https://www.facebook.com/groups/test") is True
        assert manager.validate_target_url("https://facebook.com/pages/test/123") is True
        assert manager.validate_target_url("https://m.facebook.com/profile.php?id=123") is True
        
        # Invalid URLs
        assert manager.validate_target_url("https://google.com") is False
        assert manager.validate_target_url("not_a_url") is False
        assert manager.validate_target_url("") is False
        assert manager.validate_target_url(None) is False
    
    def test_add_new_target(self, sample_targets_file):
        """Test adding a new target"""
        manager = TargetManager(config_file=str(sample_targets_file))
        initial_count = len(manager.targets)
        
        new_target = {
            "id": "new_group",
            "url": "https://www.facebook.com/groups/newgroup",
            "name": "New Group",
            "type": "group",
            "enabled": True,
            "priority": 2,
            "check_interval_hours": 3,
            "metadata": {"description": "Newly added group"}
        }
        
        success = manager.add_target(new_target)
        assert success is True
        assert len(manager.targets) == initial_count + 1
        
        # Verify the new target
        added = manager.get_target_by_id("new_group")
        assert added is not None
        assert added["name"] == "New Group"
        assert added["last_checked"] is None  # Should be initialized as None
    
    def test_add_duplicate_target(self, sample_targets_file):
        """Test preventing duplicate target IDs"""
        manager = TargetManager(config_file=str(sample_targets_file))
        
        duplicate_target = {
            "id": "group1",  # Already exists
            "url": "https://www.facebook.com/groups/duplicate",
            "name": "Duplicate",
            "type": "group",
            "enabled": True,
            "priority": 1,
            "check_interval_hours": 1
        }
        
        success = manager.add_target(duplicate_target)
        assert success is False
    
    def test_remove_target(self, sample_targets_file):
        """Test removing a target"""
        manager = TargetManager(config_file=str(sample_targets_file))
        initial_count = len(manager.targets)
        
        # Remove existing target
        success = manager.remove_target("group1")
        assert success is True
        assert len(manager.targets) == initial_count - 1
        assert manager.get_target_by_id("group1") is None
        
        # Try to remove non-existent target
        success = manager.remove_target("nonexistent")
        assert success is False