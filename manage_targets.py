#!/usr/bin/env python3
"""
Target Management CLI for Facebook Post Monitor - Enterprise Edition

🎯 MỤC ĐÍCH:
- Command-line interface để quản lý targets
- Add/remove/enable/disable targets
- Validate configurations
- Import/export target lists

🚀 SỬ DỤNG:
python manage_targets.py --list
python manage_targets.py --add --url "https://facebook.com/page" --name "Page Name"
python manage_targets.py --enable --id "page_id"
python manage_targets.py --validate
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from core.target_manager import TargetManager
from urllib.parse import urlparse
import logging
from logging_config import get_message_only_logger

# Use message-only logger for clean target management output
logger = get_message_only_logger(__name__)


class TargetCLI:
    """Command Line Interface cho Target Management"""
    
    def __init__(self, config_file: str = "targets.json"):
        self.target_manager = TargetManager(config_file)
        self.config_file = Path(config_file)
    
    def list_targets(self, show_all: bool = False):
        """Liệt kê tất cả targets"""
        targets = self.target_manager.targets if show_all else self.target_manager.get_active_targets()
        
        if not targets:
            logger.info("❌ Không có targets nào được cấu hình")
            return
        
        stats = self.target_manager.get_stats()
        logger.info("\n🎯 TARGET LIST (%d targets shown)", len(targets))
        logger.info("=" * 80)
        logger.info("📊 Total: %d | Active: %d | Disabled: %d", stats['total_targets'], stats['active_targets'], stats['disabled_targets'])
        logger.info("")
        
        # Group by priority
        for priority in ["high", "medium", "low"]:
            priority_targets = [t for t in targets if t.priority == priority]
            if priority_targets:
                priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}[priority]
                logger.info("%s %s PRIORITY (%d targets)", priority_emoji, priority.upper(), len(priority_targets))
                
                for target in priority_targets:
                    status = "✅" if target.enabled else "❌"
                    type_emoji = {"page": "📄", "group": "👥", "profile": "👤"}.get(target.type, "❓")
                    logger.info("  %s %s %s", status, type_emoji, target.name)
                    logger.info("      ID: %s", target.id)
                    logger.info("      URL: %s", target.url)
                    if target.notes:
                        logger.info("      Notes: %s", target.notes)
                    logger.info("")
    
    def add_target(self, url: str, name: str = "", target_type: str = "", 
                  priority: str = "medium", enabled: bool = True, notes: str = ""):
        """Thêm target mới"""
        try:
            # Validate URL
            if not url.startswith("https://www.facebook.com/"):
                logger.error("❌ URL phải bắt đầu bằng https://www.facebook.com/")
                return False
            
            # Auto-detect type if not provided
            if not target_type:
                if "/groups/" in url:
                    target_type = "group"
                elif "/profile.php" in url or url.count('/') == 3:
                    target_type = "profile"
                else:
                    target_type = "page"
            
            # Generate ID if name not provided
            if not name:
                # Extract from URL
                parsed = urlparse(url)
                path_parts = parsed.path.strip('/').split('/')
                if path_parts:
                    name = path_parts[-1].replace('.', '_')
                else:
                    name = "unnamed_target"
            
            # Generate unique ID
            target_id = name.lower().replace(' ', '_').replace('-', '_')
            
            # Check if already exists
            if self.target_manager.get_target_by_url(url):
                logger.error("❌ Target với URL %s đã tồn tại", url)
                return False
            
            if self.target_manager.get_target_by_id(target_id):
                # Add timestamp to make unique
                timestamp = datetime.now().strftime('%m%d')
                target_id = f"{target_id}_{timestamp}"
            
            # Create new target data
            target_data = {
                "id": target_id,
                "name": name,
                "url": url,
                "type": target_type,
                "enabled": enabled,
                "priority": priority,
                "notes": notes
            }
            
            # Load current config
            config = self.target_manager.config_data.copy()
            config["targets"].append(target_data)
            config["last_updated"] = datetime.now().isoformat()
            
            # Save config
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            
            logger.info("✅ Đã thêm target: %s", name)
            logger.info("   ID: %s", target_id)
            logger.info("   Type: %s", target_type)
            logger.info("   Priority: %s", priority)
            logger.info("   Status: %s", 'Enabled' if enabled else 'Disabled')
            
            return True
            
        except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
            logger.error("❌ Lỗi file khi thêm target: %s", e)
            return False
        except (KeyError, ValueError, AttributeError) as e:
            logger.error("❌ Lỗi dữ liệu khi thêm target: %s", e)
            return False
        except Exception as e:
            logger.error("❌ Lỗi không xác định khi thêm target: %s", e)
            return False
    
    def remove_target(self, target_id: str = "", url: str = ""):
        """Xóa target"""
        if not target_id and not url:
            logger.error("❌ Phải cung cấp --id hoặc --url")
            return False
        
        try:
            # Find target
            target = None
            if target_id:
                target = self.target_manager.get_target_by_id(target_id)
            elif url:
                target = self.target_manager.get_target_by_url(url)
            
            if not target:
                logger.error("❌ Không tìm thấy target: %s", target_id or url)
                return False
            
            # Confirm deletion
            confirm = input(f"❓ Xóa target '{target.name}' ({target.url})? (y/N): ").strip().lower()
            if confirm != 'y':
                logger.info("❌ Hủy xóa target")
                return False
            
            # Remove from config
            config = self.target_manager.config_data.copy()
            config["targets"] = [t for t in config["targets"] if t.get("id") != target.id]
            config["last_updated"] = datetime.now().isoformat()
            
            # Save config
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            
            logger.info("✅ Đã xóa target: %s", target.name)
            return True
            
        except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
            logger.error("❌ Lỗi file khi xóa target: %s", e)
            return False
        except (KeyError, ValueError, AttributeError) as e:
            logger.error("❌ Lỗi dữ liệu khi xóa target: %s", e)
            return False
        except Exception as e:
            logger.error("❌ Lỗi không xác định khi xóa target: %s", e)
            return False
    
    def toggle_target(self, target_id: str = "", url: str = "", enable: bool = None):
        """Enable/disable target"""
        if not target_id and not url:
            logger.error("❌ Phải cung cấp --id hoặc --url")
            return False
        
        try:
            # Find target
            target = None
            if target_id:
                target = self.target_manager.get_target_by_id(target_id)
            elif url:
                target = self.target_manager.get_target_by_url(url)
            
            if not target:
                logger.error("❌ Không tìm thấy target: %s", target_id or url)
                return False
            
            # Update config
            config = self.target_manager.config_data.copy()
            for t in config["targets"]:
                if t.get("id") == target.id:
                    if enable is not None:
                        t["enabled"] = enable
                    else:
                        t["enabled"] = not t.get("enabled", True)
                    break
            
            config["last_updated"] = datetime.now().isoformat()
            
            # Save config
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            
            new_status = "enabled" if enable is not False and (enable or not target.enabled) else "disabled"
            logger.info("✅ Target '%s' đã %s", target.name, new_status)
            return True
            
        except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
            logger.error("❌ Lỗi file khi toggle target: %s", e)
            return False
        except (KeyError, ValueError, AttributeError) as e:
            logger.error("❌ Lỗi dữ liệu khi toggle target: %s", e)
            return False
        except Exception as e:
            logger.error("❌ Lỗi không xác định khi toggle target: %s", e)
            return False
    
    def validate_targets(self):
        """Validate tất cả targets"""
        logger.info("🔍 VALIDATING TARGETS")
        logger.info("=" * 50)
        
        validation = self.target_manager.validate_all_targets()
        stats = self.target_manager.get_stats()
        
        logger.info("📊 Total targets: %d", stats['total_targets'])
        logger.info("✅ Valid: %d", len(validation['valid']))
        logger.info("❌ Invalid: %d", len(validation['invalid']))
        logger.info("")
        
        if validation["invalid"]:
            logger.info("❌ INVALID TARGETS:")
            for url in validation["invalid"]:
                logger.info("  - %s", url)
            logger.info("")
        
        # Check for duplicates
        urls = [t.url for t in self.target_manager.targets]
        duplicates = [url for url in urls if urls.count(url) > 1]
        if duplicates:
            logger.info("⚠️ DUPLICATE URLs:")
            for url in set(duplicates):
                logger.info("  - %s", url)
            logger.info("")
        
        # Check configuration issues
        issues = []
        for target in self.target_manager.targets:
            if not target.name:
                issues.append("Target %s: Missing name" % target.id)
            if target.priority not in ["high", "medium", "low"]:
                issues.append("Target %s: Invalid priority '%s'" % (target.id, target.priority))
            if target.type not in ["page", "group", "profile"]:
                issues.append("Target %s: Unknown type '%s'" % (target.id, target.type))
        
        if issues:
            logger.info("⚠️ CONFIGURATION ISSUES:")
            for issue in issues:
                logger.info("  - %s", issue)
        else:
            logger.info("✅ No configuration issues found")
        
        return len(validation["invalid"]) == 0 and len(issues) == 0
    
    def export_targets(self, output_file: str):
        """Export targets to file"""
        try:
            export_data = {
                "export_timestamp": datetime.now().isoformat(),
                "exported_by": "manage_targets.py",
                "targets": [
                    {
                        "id": t.id,
                        "name": t.name,
                        "url": t.url,
                        "type": t.type,
                        "enabled": t.enabled,
                        "priority": t.priority,
                        "notes": t.notes
                    }
                    for t in self.target_manager.targets
                ]
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=4, ensure_ascii=False)
            
            logger.info("✅ Đã export %d targets to %s", len(self.target_manager.targets), output_file)
            return True
            
        except (FileNotFoundError, PermissionError) as e:
            logger.error("❌ Lỗi file khi export: %s", e)
            return False
        except (KeyError, ValueError, AttributeError) as e:
            logger.error("❌ Lỗi dữ liệu khi export: %s", e)
            return False
        except Exception as e:
            logger.error("❌ Lỗi không xác định khi export: %s", e)
            return False
    
    def import_targets(self, input_file: str, merge: bool = True):
        """Import targets from file"""
        try:
            with open(input_file, 'r', encoding='utf-8') as f:
                import_data = json.load(f)
            
            imported_targets = import_data.get("targets", [])
            if not imported_targets:
                logger.error("❌ Không có targets trong file import")
                return False
            
            logger.info("📥 Importing %d targets...", len(imported_targets))
            
            current_config = self.target_manager.config_data.copy()
            
            if not merge:
                # Replace all targets
                current_config["targets"] = imported_targets
            else:
                # Merge targets
                existing_urls = {t.get("url") for t in current_config.get("targets", [])}
                new_targets = [t for t in imported_targets if t.get("url") not in existing_urls]
                
                current_config["targets"].extend(new_targets)
                logger.info("📊 Added %d new targets (skipped %d duplicates)", len(new_targets), len(imported_targets) - len(new_targets))
            
            current_config["last_updated"] = datetime.now().isoformat()
            
            # Save config
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(current_config, f, indent=4, ensure_ascii=False)
            
            logger.info("✅ Import completed successfully")
            return True
            
        except (FileNotFoundError, PermissionError, json.JSONDecodeError) as e:
            logger.error("❌ Lỗi file khi import: %s", e)
            return False
        except (KeyError, ValueError, AttributeError) as e:
            logger.error("❌ Lỗi dữ liệu khi import: %s", e)
            return False
        except Exception as e:
            logger.error("❌ Lỗi không xác định khi import: %s", e)
            return False


def main():
    parser = argparse.ArgumentParser(description='Facebook Post Monitor - Target Management')
    
    # General options
    parser.add_argument('--config', default='targets.json', help='Config file path')
    
    # Actions
    parser.add_argument('--list', action='store_true', help='List targets')
    parser.add_argument('--list-all', action='store_true', help='List all targets (including disabled)')
    parser.add_argument('--add', action='store_true', help='Add new target')
    parser.add_argument('--remove', action='store_true', help='Remove target')
    parser.add_argument('--enable', action='store_true', help='Enable target')
    parser.add_argument('--disable', action='store_true', help='Disable target')
    parser.add_argument('--validate', action='store_true', help='Validate all targets')
    parser.add_argument('--export', help='Export targets to file')
    parser.add_argument('--import', dest='import_file', help='Import targets from file')
    parser.add_argument('--replace', action='store_true', help='Replace all targets when importing')
    
    # Target details for add/remove/enable/disable
    parser.add_argument('--url', help='Target URL')
    parser.add_argument('--name', help='Target name')
    parser.add_argument('--id', help='Target ID')
    parser.add_argument('--type', choices=['page', 'group', 'profile'], help='Target type')
    parser.add_argument('--priority', choices=['high', 'medium', 'low'], default='medium', help='Target priority')
    parser.add_argument('--notes', default='', help='Target notes')
    
    args = parser.parse_args()
    
    if len(sys.argv) == 1:
        parser.print_help()
        return
    
    cli = TargetCLI(args.config)
    
    try:
        if args.list:
            cli.list_targets(show_all=False)
        elif args.list_all:
            cli.list_targets(show_all=True)
        elif args.add:
            if not args.url:
                logger.error("❌ --add requires --url")
                return
            cli.add_target(args.url, args.name, args.type, args.priority, True, args.notes)
        elif args.remove:
            cli.remove_target(args.id, args.url)
        elif args.enable:
            cli.toggle_target(args.id, args.url, enable=True)
        elif args.disable:
            cli.toggle_target(args.id, args.url, enable=False)
        elif args.validate:
            cli.validate_targets()
        elif args.export:
            cli.export_targets(args.export)
        elif args.import_file:
            cli.import_targets(args.import_file, merge=not args.replace)
        else:
            parser.print_help()
    
    except KeyboardInterrupt:
        logger.info("\n❌ Cancelled by user")
    except Exception as e:
        logger.error("❌ Unexpected error: %s", e)


if __name__ == "__main__":
    main()
