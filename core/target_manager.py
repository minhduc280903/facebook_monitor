#!/usr/bin/env python3
"""
Target Manager for Facebook Post Monitor - Enterprise Edition

🎯 MỤC ĐÍCH:
- Quản lý danh sách target URLs từ file JSON thay vì hardcode
- Hỗ trợ hot-reload configuration mà không cần restart scheduler
- Validation và error handling cho target configuration
- Priority-based target scheduling

🚀 SỬ DỤNG:
target_manager = TargetManager("targets.json")
active_targets = target_manager.get_active_targets()
"""

import json
from logging_config import get_logger
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path

logger = get_logger(__name__)


class Target:
    """Đại diện cho một Facebook target (page/group)"""
    
    def __init__(self, data: dict):
        self.id = data.get("id", "")
        self.name = data.get("name", "")
        self.url = data.get("url", "")
        self.type = data.get("type", "unknown")  # page, group, profile
        self.enabled = data.get("enabled", True)
        self.priority = data.get("priority", "medium")  # high, medium, low
        self.notes = data.get("notes", "")
        self.last_scraped = data.get("last_scraped", None)  # ✅ FIX: Add missing attribute
        
        # Validation
        if not self.url or not self.id:
            raise ValueError(f"Target must have id and url: {data}")
        
        if not self.url.startswith("https://www.facebook.com/"):
            raise ValueError(f"Invalid Facebook URL: {self.url}")
    
    def __str__(self):
        status = "✅" if self.enabled else "❌"
        return f"{status} {self.name} ({self.type}) - {self.priority} priority"
    
    def __repr__(self):
        return f"Target(id='{self.id}', url='{self.url}', enabled={self.enabled})"


class TargetManager:
    """
    🔧 PRODUCTION FIX: Externalized Target Management
    
    Quản lý danh sách targets từ file JSON thay vì hardcode trong scheduler
    """
    
    def __init__(self, config_file: str = "targets.json"):
        self.config_file = Path(config_file)
        self.targets: List[Target] = []
        self.config_data: dict = {}
        self.last_modified: Optional[datetime] = None
        
        # Load initial configuration
        self.reload_config()
    
    def reload_config(self) -> bool:
        """
        Reload configuration từ file JSON
        
        Returns:
            True nếu config thay đổi, False nếu không có thay đổi
        """
        try:
            if not self.config_file.exists():
                logger.error(f"❌ Target config file not found: {self.config_file}")
                self._create_default_config()
                return True
            
            # Kiểm tra modification time
            current_mtime = datetime.fromtimestamp(self.config_file.stat().st_mtime)
            if self.last_modified and current_mtime <= self.last_modified:
                return False  # No changes
            
            # Load configuration
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            
            # Parse targets
            self.targets = []
            targets_data = self.config_data.get("targets", [])
            
            for target_data in targets_data:
                try:
                    target = Target(target_data)
                    self.targets.append(target)
                except ValueError as e:
                    logger.error(f"❌ Invalid target configuration: {e}")
                    continue
            
            self.last_modified = current_mtime
            
            active_count = len(self.get_active_targets())
            total_count = len(self.targets)
            
            logger.info(f"🎯 Loaded {total_count} targets ({active_count} active) from {self.config_file}")
            
            # Log targets by priority
            high_priority = len([t for t in self.targets if t.enabled and t.priority == "high"])
            medium_priority = len([t for t in self.targets if t.enabled and t.priority == "medium"]) 
            low_priority = len([t for t in self.targets if t.enabled and t.priority == "low"])
            
            logger.info(f"📊 Priority distribution: High={high_priority}, Medium={medium_priority}, Low={low_priority}")
            
            return True
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in config file: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error loading config: {e}")
            return False
    
    def _create_default_config(self):
        """Tạo file config mặc định nếu không tồn tại"""
        default_config = {
            "version": "1.0",
            "description": "Facebook monitoring targets configuration - AUTO GENERATED",
            "last_updated": datetime.now().isoformat(),
            "targets": [
                {
                    "id": "example_page_1",
                    "name": "Example Facebook Page 1",
                    "url": "https://www.facebook.com/example.page.1",
                    "type": "page",
                    "enabled": False,
                    "priority": "medium",
                    "notes": "PLACEHOLDER - Thay đổi URL và enable để sử dụng"
                }
            ],
            "settings": {
                "default_priority": "medium",
                "max_concurrent_targets": 10,
                "retry_failed_targets": True,
                "retry_delay_minutes": 30
            }
        }
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            
            logger.warning(f"⚠️ Created default config file: {self.config_file}")
            logger.warning("📝 Please edit this file and add your actual Facebook URLs")
            
        except Exception as e:
            logger.error(f"❌ Could not create default config: {e}")
    
    def get_active_targets(self) -> List[Target]:
        """Lấy danh sách targets đang enabled"""
        return [target for target in self.targets if target.enabled]
    
    def get_active_urls(self) -> List[str]:
        """Lấy danh sách URLs của targets đang enabled"""
        return [target.url for target in self.get_active_targets()]
    
    def get_targets_by_priority(self, priority: str) -> List[Target]:
        """Lấy targets theo priority"""
        return [target for target in self.get_active_targets() if target.priority == priority]
    
    def get_target_by_id(self, target_id: str) -> Optional[Target]:
        """Lấy target theo ID"""
        for target in self.targets:
            if target.id == target_id:
                return target
        return None
    
    def get_target_by_url(self, url: str) -> Optional[Target]:
        """Lấy target theo URL"""
        for target in self.targets:
            if target.url == url:
                return target
        return None
    
    def get_config_setting(self, key: str, default=None):
        """Lấy setting từ config"""
        return self.config_data.get("settings", {}).get(key, default)
    
    def validate_all_targets(self) -> Dict[str, List[str]]:
        """
        Validate tất cả targets
        
        Returns:
            Dict với 'valid' và 'invalid' lists
        """
        result = {"valid": [], "invalid": []}
        
        for target in self.targets:
            if self._validate_target(target):
                result["valid"].append(target.url)
            else:
                result["invalid"].append(target.url)
        
        return result
    
    def _validate_target(self, target: Target) -> bool:
        """Validate một target"""
        try:
            # Basic URL validation
            if not target.url.startswith("https://www.facebook.com/"):
                return False
            
            # Type validation
            if target.type not in ["page", "group", "profile"]:
                logger.warning(f"⚠️ Unknown target type: {target.type} for {target.id}")
            
            # Priority validation
            if target.priority not in ["high", "medium", "low"]:
                logger.warning(f"⚠️ Unknown priority: {target.priority} for {target.id}")
            
            return True
            
        except Exception:
            return False
    
    def get_stats(self) -> Dict[str, int]:
        """Thống kê targets"""
        active_targets = self.get_active_targets()
        
        return {
            "total_targets": len(self.targets),
            "active_targets": len(active_targets),
            "disabled_targets": len(self.targets) - len(active_targets),
            "high_priority": len([t for t in active_targets if t.priority == "high"]),
            "medium_priority": len([t for t in active_targets if t.priority == "medium"]),
            "low_priority": len([t for t in active_targets if t.priority == "low"]),
            "pages": len([t for t in active_targets if t.type == "page"]),
            "groups": len([t for t in active_targets if t.type == "group"]),
            "profiles": len([t for t in active_targets if t.type == "profile"])
        }
    
    def print_status(self):
        """In trạng thái của tất cả targets"""
        print("\n🎯 TARGET MANAGER STATUS")
        print("=" * 50)
        
        if not self.targets:
            print("❌ No targets configured")
            return
        
        stats = self.get_stats()
        
        print(f"📊 Total: {stats['total_targets']} | Active: {stats['active_targets']} | Disabled: {stats['disabled_targets']}")
        print(f"🎯 Priority: High={stats['high_priority']} | Medium={stats['medium_priority']} | Low={stats['low_priority']}")
        print(f"📄 Types: Pages={stats['pages']} | Groups={stats['groups']} | Profiles={stats['profiles']}")
        print()
        
        # List all targets
        for target in self.targets:
            print(f"  {target}")

    def get_statistics(self) -> Dict[str, Any]:
        """
        Lấy thống kê về targets cho diagnostic
        
        Returns:
            Dict chứa thông tin thống kê về targets
        """
        active_count = 0
        inactive_count = 0
        priority_counts = {"high": 0, "medium": 0, "low": 0}
        
        for target in self.targets:
            if target.enabled:
                active_count += 1
                priority_counts[target.priority] += 1
            else:
                inactive_count += 1
        
        return {
            "total": len(self.targets),
            "active": active_count,
            "inactive": inactive_count,
            "priority_distribution": priority_counts,
            "targets": [
                {
                    "url": target.url,
                    "priority": target.priority,
                    "enabled": target.enabled,
                    "last_scraped": target.last_scraped
                }
                for target in self.targets
            ]
        }


def test_target_manager():
    """Test function cho TargetManager"""
    manager = TargetManager("targets.json")
    
    print("🧪 TESTING TARGET MANAGER")
    print("=" * 40)
    
    manager.print_status()
    
    print(f"\n✅ Active URLs: {len(manager.get_active_urls())}")
    for url in manager.get_active_urls():
        print(f"  - {url}")
    
    # Test validation
    validation = manager.validate_all_targets()
    print(f"\n🔍 Validation: {len(validation['valid'])} valid, {len(validation['invalid'])} invalid")


if __name__ == "__main__":
    # Test khi chạy trực tiếp
    test_target_manager()
